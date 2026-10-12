"""Capture real runtime inputs for explicitly synthetic follow-up conversations."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from dataclasses import replace
from pathlib import Path

from ..agent_service import AgentService
from ..analysis import analyst_payload
from ..answers import answer_interpretation
from ..catalog import Catalog
from ..config import Settings
from ..database import Database
from ..execution import GraphMineRunner
from ..graph_store import GraphStore
from ..history import HistoryStore
from ..jobs import EventBus, JobManager
from ..models import (
    ApplicationIntent,
    ChatRequest,
    ExecutionPlan,
    GroundedNarrative,
    JobRecord,
    JobStatus,
    LLMMode,
    PlanRequest,
    ResultRecord,
    TurnDecision,
)
from ..planning import PlanValidator
from ..visualization import answer_visualizations
from .catalog_audit import materialize_case
from .catalog_suite import digest
from .dual_teacher import CaptureModel, make_job


class CapturedTurn(RuntimeError):
    """Deliberately stop after recording an input, before any inference or work."""


class TurnCapture:
    def __init__(self, case, destination, action, variant, records):
        self.case, self.destination, self.action, self.variant, self.records = (
            case,
            destination,
            action,
            variant,
            records,
        )

    async def close(self):
        pass

    async def generate(self, *, mode, schema, user_payload, conversation=None):
        if schema is not TurnDecision:
            raise ValueError("Expected the follow-up classifier before any new work")
        row = make_job(self.case, mode, schema, user_payload, conversation)
        row["id"] += "-" + self.variant
        row["variant"] = "conversation"
        row["expected_action"] = self.action
        row["conversation_source"] = (
            "assistant_authored_simulated_user_turn; not observed human behavior"
        )
        row["sha256"] = digest(row)
        path = self.destination / (row["id"] + ".json")
        if path.exists():
            raise ValueError("A conversation input already exists")
        HistoryStore.write(path, row)
        self.records.append(row)
        raise CapturedTurn


async def augment(
    settings, root, *, final_test=False, train_count=8, validation_count=4
):
    output = root / ("final-test-inputs" if final_test else "teacher-inputs")
    manifest_path = root / (
        "final-test-conversations.json"
        if final_test
        else "conversation-input-manifest.json"
    )
    if manifest_path.exists():
        raise ValueError("Conversation capture already completed")
    isolated = replace(
        settings,
        data_root=root
        / ("final-test-conversation-store" if final_test else "conversation-store"),
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
    corpus = json.loads((root / "corpus.json").read_text())
    records = []
    sources = []
    for split, count in (
        [("test", 5)]
        if final_test
        else [("train", train_count), ("validation", validation_count)]
    ):
        eligible = []
        for case in corpus["cases"]:
            if case["split"] != split or not case["lineage"].startswith("synthetic:"):
                continue
            path = root / "references/cases" / (case["id"] + ".json")
            reference = json.loads(path.read_text())
            if reference["status"] == "verified" and reference.get("answer"):
                eligible.append((case, reference, path))
        if count > 8:
            buckets = {}
            for item in eligible:
                buckets.setdefault(item[0]["task"]["operation_id"], []).append(item)
            eligible = []
            while any(buckets.values()):
                for bucket in buckets.values():
                    if bucket:
                        eligible.append(bucket.pop(0))
        for case, reference, reference_path in eligible[:count]:
            session, graph, auxiliary = materialize_case(store, database, case)
            plan = ExecutionPlan.model_validate(reference["plan"]).model_copy(
                update={
                    "session_id": session.id,
                    "graph_id": graph.id,
                    "auxiliary_inputs": auxiliary,
                }
            )
            native_job = database.save_job(
                JobRecord(session_id=session.id, plan=plan, status=JobStatus.completed)
            )
            answer = reference["answer"]
            defaults = answer_visualizations(answer)
            result = database.save_result(
                ResultRecord(
                    session_id=session.id,
                    job_id=native_job.id,
                    operation_id=plan.operation_id,
                    payload=reference["payload"],
                    summary={},
                    answer=answer,
                    interpretation=answer_interpretation(answer, defaults),
                    interpretation_source="offline_rules",
                )
            )
            database.save_job(native_job.model_copy(update={"result_id": result.id}))
            database.add_message(
                session.id, "user", {"message": case["task"]["question"]}, "planner"
            )
            database.add_message(
                session.id,
                "assistant",
                {"message": result.interpretation.summary, "result_id": result.id},
                "analyst",
            )
            variants = [
                (
                    "explain",
                    "limitations",
                    "Explain what this result means and its main limitations.",
                ),
                (
                    "explain",
                    "visualization",
                    "Make a concise report with a custom comparison chart using these computed results. Explain what it shows.",
                ),
                (
                    "analyze",
                    "filter",
                    "Repeat the analysis using only records whose year is 2025.",
                ),
                (
                    "analyze",
                    "new_measure",
                    "Now count and list fully connected groups of exactly four records, including those inside larger groups.",
                ),
                ("clarify", "ambiguous", "Do the other one instead."),
            ]
            for action, variant, message in variants:
                await service.model.close()
                service.model = TurnCapture(case, output, action, variant, records)
                try:
                    await service.chat(
                        session.id,
                        ChatRequest(
                            message=message,
                            graph_id=graph.id,
                            result_id=result.id,
                            execute=False,
                        ),
                    )
                except CapturedTurn:
                    pass
                else:
                    raise ValueError("Follow-up input was not captured")
                if variant == "visualization":
                    row = make_job(
                        case,
                        LLMMode.analyst,
                        GroundedNarrative,
                        analyst_payload(
                            answer, defaults, catalog, case["domain_id"], message
                        ),
                        database.messages(session.id),
                    )
                    row["id"] += "-custom-comparison"
                    row["variant"] = "conversation"
                    row["reference_path"] = str(reference_path.relative_to(root))
                    row["reference_sha256"] = HistoryStore.digest(reference_path)
                    row["sha256"] = digest(row)
                    HistoryStore.write(output / (row["id"] + ".json"), row)
                    records.append(row)
            # A complete clarification exchange uses production pending-request
            # state, not labels hidden in the student's prompt.
            if case["task"]["operation_id"] != "betweenness-centrality":
                continue
            session, graph, _ = materialize_case(store, database, case)
            ambiguous = copy.deepcopy(case)
            ambiguous["id"] += "-clarification-first"
            ambiguous["tags"] = ["ambiguous", "simulated_conversation"]
            ambiguous["task"] = {
                "question": "Which records should we focus on?",
                "problem_id": None,
                "operation_id": None,
                "parameters": {},
                "optional_outputs": [],
                "intent": ApplicationIntent(
                    objective="Which records should we focus on?"
                ).model_dump(mode="json"),
                "expected_status": "needs_information",
            }
            ambiguous["sha256"] = digest(
                {k: v for k, v in ambiguous.items() if k != "sha256"}
            )
            first = CaptureModel(catalog, ambiguous, output)
            await service.model.close()
            service.model = first
            outcome = await service.plan(
                session.id,
                PlanRequest(message=ambiguous["task"]["question"], graph_id=graph.id),
            )
            if outcome.status != "needs_information":
                raise ValueError("The ambiguous turn must clarify before execution")
            reply = copy.deepcopy(case)
            reply["id"] += "-clarification-reply"
            reply["task"]["question"] = (
                "Focus on records that sit on shortest routes connecting other records. Split credit between equally short routes, treat links equally, and rank everyone. Include normalized scores."
            )
            reply["task"]["intent"]["objective"] = reply["task"]["question"]
            reply["sha256"] = digest({k: v for k, v in reply.items() if k != "sha256"})
            follow = CaptureModel(catalog, reply, output)
            service.model = follow
            outcome = await service.plan(
                session.id,
                PlanRequest(message=reply["task"]["question"], graph_id=graph.id),
            )
            if outcome.status != "ready":
                raise ValueError("The clarified request must be ready")
            for row in first.records + follow.records:
                row.pop("sha256")
                row["variant"] = "conversation"
                row["sha256"] = digest(row)
                HistoryStore.write(output / (row["id"] + ".json"), row)
                records.append(row)
            sources.extend([ambiguous, reply])
    await service.close()
    manifest = {
        "version": "dual-conversations-v1",
        "rows": [
            {
                k: row[k]
                for k in (
                    "id",
                    "case_id",
                    "split",
                    "lineage",
                    "adapter",
                    "schema",
                    "sha256",
                )
            }
            for row in records
        ],
        "additional_scenarios": sources,
        "provenance": "Simulated conversations based only on public/synthetic records and verified computations; no observed human feedback.",
    }
    HistoryStore.write(manifest_path, manifest)
    return {"rows": len(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--final-test", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                augment(Settings.from_env(), args.root, final_test=args.final_test)
            )
        )
    )


if __name__ == "__main__":
    main()
