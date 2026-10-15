#!/usr/bin/env python3
"""Exercise the live planner on synthetic data in an isolated, temporary store.

This is a deployment smoke check, not a held-out accuracy evaluation or human
review. It uses the configured model endpoint and runs one small CPU workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))


async def check(output: Path):
    from graphmine_agent.analytics import AnalyticsService, WorkflowRequest
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
    from graphmine_agent.config import Settings
    from graphmine_agent.database import Database
    from graphmine_agent.graph_store import GraphStore
    from graphmine_agent.jobs import EventBus
    from graphmine_agent.models import FileRole, SessionRecord

    report = {
        "scope": "Synthetic live-model routing smoke check; no accuracy claim or human review",
        "created_at": datetime.now(UTC).isoformat(),
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="graphmine-routing-smoke-") as temporary:
        settings = replace(
            Settings.from_env(ROOT),
            data_root=Path(temporary),
            history_directory=None,
            accounts_enabled=False,
            backup_directory=None,
            analytics_gpu_uuids=(),
        )
        report["model"] = settings.analytics_planner_model or settings.llm_model
        database = Database(settings.database_path)
        store = GraphStore(settings, database)
        events = EventBus(database)
        service = AnalyticsService(settings, database, store, events)
        planner = AnalyticsPlanner(settings, service, events)
        service.open()
        try:
            session = database.create_session(SessionRecord(domain_id="general"))
            graph = {
                "graph": {
                    "id": "routing-smoke",
                    "directed": False,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": i} for i in range(4)],
                "edges": [
                    {"id": f"{a}-{b}", "source": a, "target": b}
                    for a, b in ((0, 1), (1, 2), (0, 2), (2, 3))
                ],
            }
            uploaded = store.ingest(
                session_id=session.id,
                role=FileRole.graph,
                filename="routing-smoke.json",
                content=json.dumps(graph).encode(),
            )
            inputs = {"main": {"file_id": uploaded.id, "kind": "graph"}}
            saved = await service.create(
                session.id,
                WorkflowRequest(
                    mode="normal",
                    evaluation_id="deployment-smoke/saved-cliques",
                    inputs=inputs,
                    plan={
                        "version": 1,
                        "device": "cpu",
                        "steps": [
                            {
                                "id": "groups",
                                "operation": "maximal-cliques",
                                "input": {"input": "main"},
                                "parameters": {},
                            }
                        ],
                    },
                ),
            )
            await asyncio.gather(*service.tasks.values())
            result = service.result(saved["id"])
            groups = result["steps"]["groups"]["result"]["ports"]["groups"]["value"]
            actual = sorted(sorted(group["vertices"]) for group in groups)
            assert actual == [[0, 1, 2], [2, 3]], actual
            report["cpu_cliques"] = actual
            memberships = service.group_memberships(
                saved["id"], "groups", "groups", [0, 2, "2"]
            )
            assert memberships["memberships"] == [
                {"vertex": 0, "groups": 1},
                {"vertex": 2, "groups": 2},
                {"vertex": "2", "groups": 0},
            ]
            report["native_memberships"] = memberships
            cases = (
                (
                    "calculate",
                    "Count all triangles in the entire graph.",
                    "ready",
                    False,
                ),
                (
                    "view",
                    "Show the largest clique from the saved result.",
                    "view",
                    True,
                ),
                (
                    "explain",
                    "How many cliques did the saved run find?",
                    "answered",
                    True,
                ),
                (
                    "clarify",
                    "Find the shortest path between two vertices.",
                    "needs_information",
                    False,
                ),
            )
            for name, question, expected, previous in cases:
                started = time.monotonic()
                row = {"case": name, "expected_status": expected, "passed": False}
                try:
                    response = await planner.plan(
                        session.id,
                        PlanningRequest(
                            message=question,
                            inputs=inputs,
                            device="cpu",
                            previous_workflow_id=saved["id"] if previous else None,
                            evaluation_id=f"deployment-smoke/{name}",
                        ),
                    )
                    row["response"] = response
                    stages = [
                        stage["stage"]
                        for stage in response["trace"]
                        if stage["stage"] in {"route", "plan"}
                    ]
                    assert response["status"] == expected, response["status"]
                    if name == "calculate":
                        assert [s["operation"] for s in response["plan"]["steps"]] == [
                            "triangle-counting"
                        ]
                        assert stages == ["route", "plan"], stages
                    else:
                        assert response["plan"] is None
                        if name in {"view", "explain"}:
                            assert stages == ["route"], stages
                    row["passed"] = True
                except Exception as error:  # noqa: BLE001 - retain failed cases in the report
                    row["error"] = {"type": type(error).__name__, "message": str(error)}
                row["seconds"] = round(time.monotonic() - started, 2)
                report["cases"].append(row)
                print(
                    json.dumps({k: v for k, v in row.items() if k != "response"}),
                    flush=True,
                )
            report["diagnostics"] = [
                event.payload
                for event in database.events(session.id)
                if event.type == "workflow.diagnostics"
            ]
        finally:
            await service.close()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n")
    return len(report["cases"]) == 4 and all(row["passed"] for row in report["cases"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return 0 if asyncio.run(check(args.output)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
