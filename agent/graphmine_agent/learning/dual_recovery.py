"""Capture bounded planning recovery after a deliberately invalid first draft.

The initial error is injected locally. Only the real runtime's recovery inputs
are exported; their supervised targets must still come from the teacher.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from ..agent_service import AgentService
from ..catalog import Catalog
from ..config import Settings
from ..database import Database
from ..execution import GraphMineRunner
from ..graph_store import GraphStore
from ..history import HistoryStore
from ..jobs import EventBus, JobManager
from ..models import PlanDraft, PlanRequest
from ..planning import PlanValidator
from .catalog_audit import materialize_case
from .catalog_suite import digest
from .dual_teacher import CaptureModel, make_job


class RecoveryCapture(CaptureModel):
    def __init__(self, catalog, case, scratch, destination):
        super().__init__(catalog, case, scratch)
        self.output = destination
        self.recovery_records = []
        self.injected = False

    async def generate(
        self, *, mode, schema, user_payload, conversation=None, **kwargs
    ):
        result = await super().generate(
            mode=mode,
            schema=schema,
            user_payload=user_payload,
            conversation=conversation,
            **kwargs,
        )
        if "routing_review" in user_payload:
            row = make_job(self.case, mode, schema, user_payload, conversation)
            row.update(
                id=f"{self.case['id']}-recovery-{schema.__name__}",
                variant="recovery",
                error_source="Injected invalid k=0 in the initial local draft; not an observed model error.",
            )
            row["sha256"] = digest(row)
            path = self.output / (row["id"] + ".json")
            if path.exists():
                raise ValueError("Recovery inputs are immutable")
            HistoryStore.write(path, row)
            self.recovery_records.append(row)
        elif schema is PlanDraft and not self.injected:
            self.injected = True
            result = result.model_copy(deep=True)
            result.plan.parameters["k"] = 0
        return result


def recovery_cases(corpus, selected_cases=None):
    """Bind recovery selections to this corpus and exclude reserved test cases."""
    selected_ids = {
        "dual-0002-k-cliques",
        "dual-0011-k-cliques",
        "dual-0045-k-cliques",
        "dual-0051-k-cliques",
        "dual-0073-k-cliques",
        "dual-0096-k-cliques",
    }
    by_id = {case["id"]: case for case in corpus["cases"]}
    cases = (
        [case for case in corpus["cases"] if case["id"] in selected_ids]
        if selected_cases is None
        else selected_cases
    )
    if (
        not cases
        or (selected_cases is None and len(cases) != len(selected_ids))
        or len({case["id"] for case in cases}) != len(cases)
        or any(
            case != by_id.get(case["id"])
            or case["split"] not in {"train", "validation"}
            or case["task"]["operation_id"] != "k-cliques"
            or case["task"]["expected_status"] != "ready"
            for case in cases
        )
    ):
        raise ValueError("Unexpected recovery selection or final-test contamination")
    return cases


async def capture_recovery(settings, root, *, selected_cases=None):
    manifest = root / "recovery-input-manifest.json"
    if manifest.exists():
        raise ValueError("Recovery capture already completed")
    cases = recovery_cases(
        json.loads((root / "corpus.json").read_text()), selected_cases
    )
    isolated = replace(
        settings,
        data_root=root / "recovery-store",
        history_directory=None,
        llm_enabled=False,
    )
    catalog = Catalog(isolated)
    database = Database(isolated.database_path)
    store = GraphStore(isolated, database)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(isolated, catalog, store, validator)
    jobs = JobManager(database, runner, EventBus(database), summary_items=20)
    service = AgentService(isolated, catalog, database, store, validator, jobs)
    rows = []
    try:
        for case in cases:
            reference = json.loads(
                (root / "references/cases" / (case["id"] + ".json")).read_text()
            )
            if (
                reference["status"] != "verified"
                or reference["case_sha256"] != case["sha256"]
            ):
                raise ValueError("Unverified recovery source")
            session, graph, _ = materialize_case(store, database, case)
            model = RecoveryCapture(
                catalog, case, root / "recovery-capture-trace", root / "teacher-inputs"
            )
            await service.model.close()
            service.model = model
            outcome = await service.plan(
                session.id,
                PlanRequest(message=case["task"]["question"], graph_id=graph.id),
            )
            if outcome.status != "ready" or len(model.recovery_records) != 2:
                raise ValueError(f"Runtime recovery was not captured for {case['id']}")
            rows.extend(
                {
                    key: row[key]
                    for key in ("id", "schema", "split", "lineage", "sha256")
                }
                for row in model.recovery_records
            )
    finally:
        await service.close()
    report = {
        "rows": rows,
        "scope": "Simulated failure, actual bounded production recovery inputs; no final-test data.",
    }
    HistoryStore.write(manifest, report)
    return {"inputs": len(rows), "cases": len(cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(capture_recovery(Settings.from_env(), args.root))))


if __name__ == "__main__":
    main()
