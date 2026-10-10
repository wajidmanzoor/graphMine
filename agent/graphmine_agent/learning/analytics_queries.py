"""Authored review probes for query/workflow integration, kept out of training.

Reference runs execute declared plans through the real application worker.
Model runs grade constrained planning and execution separately. Neither mode
claims an external benchmark or human-reviewed labels.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from ..analytics import AnalyticsService, WorkflowRequest
from ..analytics_planning import AnalyticsPlanner, PlanningRequest
from ..database import Database, RecordNotFound
from ..graph_store import GraphStore
from ..jobs import EventBus
from ..models import FileRole, SessionRecord


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def build_suite():
    graph = {
        "graph": {
            "id": "review-query-records",
            "directed": True,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {"id": vertex, "attributes": {"branch": branch}}
            for vertex, branch in zip(
                "ABCDE", ["east", "west", "east", "west", "north"], strict=True
            )
        ],
        "edges": [
            {"id": name, "source": u, "target": v, "attributes": {"amount": amount}}
            for name, u, v, amount in [
                ("AB", "A", "B", 10),
                ("BC", "B", "C", 20),
                ("AC", "A", "C", 30),
                ("CD", "C", "D", 40),
            ]
        ],
    }
    cases = []

    def step(name, operation, parameters=None, *, source=None, bindings=None):
        return {
            "id": name,
            "operation": operation,
            "input": source or {"input": "main"},
            "parameters": parameters or {},
            "bindings": bindings or {},
        }

    def predicate(field, op, value):
        return [{"field": field, "op": op, "value": value}]

    def expect(name, port, value):
        return {"step": name, "port": port, "value": value}

    def add(name, question, steps, checks, *, slice="lookup"):
        cases.append(
            {
                "id": name,
                "question": question,
                "slice": slice,
                "input": deepcopy(graph),
                "plan": {"version": 1, "device": "cpu", "steps": steps},
                "expected": checks,
            }
        )

    add(
        "typed_lookup",
        "Look up the vertex with the string ID A and return its record.",
        [step("answer", "node-lookup", {"vertices": ["A"]})],
        [expect("answer", "vertices", ["A"])],
    )
    add(
        "branch_lookup",
        "Return the vertices whose attributes.branch equals east.",
        [
            step(
                "answer",
                "node-lookup",
                {"vertex_filters": predicate("attributes.branch", "eq", "east")},
            )
        ],
        [expect("answer", "vertices", ["A", "C"])],
    )
    add(
        "relationship_filter",
        "Return relationships whose recorded amount is at least 30.",
        [
            step(
                "answer",
                "edge-filter",
                {"edge_filters": predicate("attributes.amount", "gte", 30)},
            )
        ],
        [expect("answer", "edges", ["AC", "CD"])],
    )
    add(
        "source_record_filter",
        "Return relationships sent by vertices in the east branch.",
        [
            step(
                "answer",
                "edge-filter",
                {"source_filters": predicate("attributes.branch", "eq", "east")},
            )
        ],
        [expect("answer", "edges", ["AB", "AC", "CD"])],
    )
    add(
        "outgoing_neighbors",
        "Who is directly reachable from A following outgoing relationships? Exclude A itself.",
        [step("answer", "neighbors", {"entity": "A"})],
        [expect("answer", "vertices", ["B", "C"])],
    )
    add(
        "incoming_neighbors",
        "Who sends a relationship directly into C? Exclude C itself.",
        [step("answer", "neighbors", {"entity": "C", "direction": "in"})],
        [expect("answer", "vertices", ["A", "B"])],
    )
    add(
        "two_hops",
        "Return vertices reachable from A within two outgoing hops, excluding A.",
        [step("answer", "neighbors", {"entity": "A", "hops": 2})],
        [expect("answer", "vertices", ["B", "C", "D"])],
    )
    add(
        "shared_neighbors",
        "Which vertices receive direct relationships from both A and B?",
        [step("answer", "common-neighbors", {"source": "A", "target": "B"})],
        [expect("answer", "vertices", ["C"])],
    )
    add(
        "shortest_paths",
        "List all shortest outgoing paths by number of hops from A to D, within three hops.",
        [step("answer", "query-paths", {"source": "A", "target": "D"})],
        [
            expect(
                "answer",
                "rows",
                [{"vertices": ["A", "C", "D"], "edges": ["AC", "CD"], "hops": 2}],
            )
        ],
    )
    add(
        "all_paths",
        "List all outgoing vertex-simple paths from A to D within three hops.",
        [
            step(
                "answer",
                "query-paths",
                {"source": "A", "target": "D", "mode": "all_simple"},
            )
        ],
        [expect("answer", "count", 2)],
    )

    def extraction(name, predecessor, port="vertices"):
        return step(
            name,
            "query-subgraph",
            {"mode": "edges" if port == "edges" else "vertices"},
            bindings={
                "edge_ids" if port == "edges" else "vertices": {
                    "step": predecessor,
                    "port": port,
                }
            },
        )

    def count(name, source):
        return step(name, "graph-aggregate", source={"step": source, "port": "graph"})

    def aggregate_check(name, value):
        return expect(
            name,
            "rows",
            [
                {
                    "group": None,
                    "value": value,
                    "exact_value": {"numerator": value, "denominator": 1},
                    "rounded": False,
                    "record_count": value,
                }
            ],
        )

    add(
        "filtered_network",
        "Keep relationships with amount at least 30, extract their endpoint graph, then count its relationships.",
        [
            step(
                "filter",
                "edge-filter",
                {"edge_filters": predicate("attributes.amount", "gte", 30)},
            ),
            extraction("sub", "filter", "edges"),
            count("answer", "sub"),
        ],
        [
            expect("filter", "edges", ["AC", "CD"]),
            expect("sub", "vertices", ["A", "C", "D"]),
            aggregate_check("answer", 2),
        ],
        slice="dependent",
    )
    add(
        "branch_network",
        "Find east-branch vertices, take their induced graph, then count its relationships.",
        [
            step(
                "lookup",
                "node-lookup",
                {"vertex_filters": predicate("attributes.branch", "eq", "east")},
            ),
            extraction("sub", "lookup"),
            count("answer", "sub"),
        ],
        [
            expect("lookup", "vertices", ["A", "C"]),
            expect("sub", "edges", ["AC"]),
            aggregate_check("answer", 1),
        ],
        slice="dependent",
    )
    add(
        "neighbor_network",
        "Find vertices within two outgoing hops of A excluding A, induce their graph, then count its relationships.",
        [
            step("near", "neighbors", {"entity": "A", "hops": 2}),
            extraction("sub", "near"),
            count("answer", "sub"),
        ],
        [
            expect("near", "vertices", ["B", "C", "D"]),
            expect("sub", "edges", ["BC", "CD"]),
            aggregate_check("answer", 2),
        ],
        slice="dependent",
    )
    add(
        "isolate_network",
        "Look up E, extract its induced graph, then count its relationships.",
        [
            step("lookup", "node-lookup", {"vertices": ["E"]}),
            extraction("sub", "lookup"),
            count("answer", "sub"),
        ],
        [expect("sub", "vertices", ["E"]), aggregate_check("answer", 0)],
        slice="dependent",
    )
    add(
        "empty_network",
        "Select vertices in the south branch, extract their graph, then count its relationships. An empty selection is an answer.",
        [
            step(
                "lookup",
                "node-lookup",
                {"vertex_filters": predicate("attributes.branch", "eq", "south")},
            ),
            extraction("sub", "lookup"),
            count("answer", "sub"),
        ],
        [
            expect("lookup", "vertices", []),
            expect("sub", "vertices", []),
            aggregate_check("answer", 0),
        ],
        slice="dependent",
    )
    add(
        "path_network",
        "Find all hop-shortest A-to-D paths within three outgoing hops, induce the graph of their vertices, then count its relationships.",
        [
            step("paths", "query-paths", {"source": "A", "target": "D"}),
            extraction("sub", "paths"),
            count("answer", "sub"),
        ],
        [expect("sub", "vertices", ["A", "C", "D"]), aggregate_check("answer", 2)],
        slice="dependent",
    )
    add(
        "common_network",
        "Find the common outgoing neighbors of A and B, induce their graph, then count its relationships.",
        [
            step("shared", "common-neighbors", {"source": "A", "target": "B"}),
            extraction("sub", "shared"),
            count("answer", "sub"),
        ],
        [expect("sub", "vertices", ["C"]), aggregate_check("answer", 0)],
        slice="dependent",
    )
    add(
        "top_sender",
        "Sum outgoing relationship amounts per vertex. Look up the top vertex's record; break a tie by the smallest string ID.",
        [
            step(
                "totals",
                "graph-aggregate",
                {"metric": "sum", "field": "attributes.amount", "group_by": "vertex"},
            ),
            step(
                "answer",
                "node-lookup",
                bindings={
                    "vertices": {
                        "step": "totals",
                        "port": "scores",
                        "select": {"kind": "top_vertices", "k": 1},
                    }
                },
            ),
        ],
        [expect("answer", "vertices", ["A"])],
        slice="dependent",
    )
    add(
        "filtered_reachability",
        "Keep relationships with amount at least 20, extract their graph, then list vertices reachable from A within two outgoing hops excluding A.",
        [
            step(
                "filter",
                "edge-filter",
                {"edge_filters": predicate("attributes.amount", "gte", 20)},
            ),
            extraction("sub", "filter", "edges"),
            step(
                "answer",
                "neighbors",
                {"entity": "A", "hops": 2},
                source={"step": "sub", "port": "graph"},
            ),
        ],
        [expect("answer", "vertices", ["C", "D"])],
        slice="dependent",
    )
    add(
        "query_to_algorithm",
        "Keep relationships with amount at least 30, extract their graph, then run breadth-first search from A and return reached vertices.",
        [
            step(
                "filter",
                "edge-filter",
                {"edge_filters": predicate("attributes.amount", "gte", 30)},
            ),
            extraction("sub", "filter", "edges"),
            step(
                "answer",
                "breadth-first-search",
                {"sources": ["A"]},
                source={"step": "sub", "port": "graph"},
            ),
        ],
        [expect("answer", "vertices", ["A", "C", "D"])],
        slice="dependent",
    )
    return {
        "version": "review-query-workflows-v1",
        "scope": "20 assistant-authored development cases sharing a small fictional graph; not human labels, held-out data, an external benchmark, or training authorization",
        "cases": cases,
    }


def grade(expected, actual, result, checks):
    want, got = expected["steps"], actual["steps"]
    operation_match = Counter(s["operation"] for s in want) == Counter(
        s["operation"] for s in got
    )
    # This bundle deliberately uses each operation at most once in each plan.
    # Duplicate/unexpected model steps fail the operation stage, not get merged.
    mapping = {}
    if operation_match and all(
        n == 1 for n in Counter(s["operation"] for s in want).values()
    ):
        by_operation = {s["operation"]: s["id"] for s in got}
        mapping = {s["id"]: by_operation[s["operation"]] for s in want}
    inverse = {value: key for key, value in mapping.items()}

    def reference(value):
        value = deepcopy(value)
        if "step" in value:
            value["step"] = inverse.get(value["step"], value["step"])
        return value

    parameters, wiring = bool(mapping), bool(mapping)
    for target in want:
        source = next((s for s in got if s["id"] == mapping.get(target["id"])), None)
        if source is None:
            continue
        parameters &= (
            digest(target["parameters"]) == digest(source["parameters"])
            and target["device"] == source["device"]
        )
        wiring &= digest(target["input"]) == digest(
            reference(source["input"])
        ) and digest(target["bindings"]) == digest(
            {k: reference(v) for k, v in source["bindings"].items()}
        )
    observed = []
    for check in checks:
        step = result.get("steps", {}).get(mapping.get(check["step"]), {})
        port = step.get("result", {}).get("ports", {}).get(check["port"])
        passed = (
            step.get("status") == "completed"
            and port is not None
            and port.get("complete") is True
            and digest(port.get("value")) == digest(check["value"])
        )
        observed.append(
            {
                "step": check["step"],
                "port": check["port"],
                "passed": passed,
                "expected": check["value"],
                "observed": port.get("value") if port else None,
            }
        )
    execution = result.get("status") == "completed" and result.get("complete") is True
    return {
        "operations": operation_match,
        "parameters": parameters,
        "wiring": wiring,
        "execution": execution,
        "result_checks": observed,
        "passed": bool(
            operation_match
            and parameters
            and wiring
            and execution
            and all(row["passed"] for row in observed)
        ),
    }


async def evaluate(
    settings, *, mode="reference", suite=None, planner_factory=AnalyticsPlanner
):
    if mode not in {"reference", "model"}:
        raise ValueError("mode must be reference or model")
    if mode == "model" and not settings.llm_enabled:
        raise ValueError(
            "Model evaluation requires an explicitly enabled model endpoint"
        )
    suite = suite or build_suite()
    database = Database(settings.database_path)
    store = GraphStore(settings, database)
    events = EventBus(database)
    analytics = AnalyticsService(settings, database, store, events)
    planner = planner_factory(settings, analytics, events)
    analytics.open()
    rows = []
    try:
        caps = await analytics.capabilities()
        for case in suite["cases"]:
            started = time.monotonic()
            session = database.create_session(SessionRecord(domain_id="general"))
            file = store.ingest(
                session_id=session.id,
                role=FileRole.graph,
                filename=f"{case['id']}.json",
                content=json.dumps(case["input"]).encode(),
            )
            request = WorkflowRequest(
                mode="normal", plan=case["plan"], inputs={"main": {"file_id": file.id}}
            )
            row = {"id": case["id"], "slice": case["slice"], "planning": None}
            try:
                checked = await analytics._call(
                    {
                        "command": "validate",
                        "plan": case["plan"],
                        "inputs": analytics._inputs(session.id, request.inputs),
                    }
                )
                if mode == "model":
                    planned = await planner.plan(
                        session.id,
                        PlanningRequest(
                            message=case["question"],
                            inputs=request.inputs,
                            device="cpu",
                        ),
                    )
                    row["planning"] = planned
                    if planned["status"] != "ready":
                        row.update(
                            passed=False,
                            failure_stage="planning",
                            elapsed_seconds=time.monotonic() - started,
                        )
                        rows.append(row)
                        continue
                    request.plan = planned["plan"]
                saved = await analytics.create(session.id, request)
                await asyncio.gather(*analytics.tasks.values())
                result = analytics.result(saved["id"])
                row.update(
                    grade(checked["plan"], result["plan"], result, case["expected"])
                )
                row["workflow_id"] = saved["id"]
                row["workflow_hash"] = result["workflow_hash"]
            except (ValueError, OSError, TimeoutError, RecordNotFound) as exc:
                row.update(
                    passed=False,
                    failure_stage="validation_or_execution",
                    error=str(exc),
                )
            row["elapsed_seconds"] = time.monotonic() - started
            rows.append(row)
    finally:
        await analytics.close()
    return {
        "version": suite["version"],
        "scope": suite["scope"],
        "mode": mode,
        "model_accuracy_measured": mode == "model"
        and any(row["planning"] is not None for row in rows),
        "suite_sha256": digest(suite),
        "capabilities_sha256": digest(caps),
        "implementation_sha256": caps["implementation_sha256"],
        "cases": rows,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
        "by_slice": {
            name: {
                "passed": sum(row["passed"] for row in rows if row["slice"] == name),
                "total": sum(row["slice"] == name for row in rows),
            }
            for name in sorted({row["slice"] for row in rows})
        },
    }


def main():
    import argparse
    import tempfile

    from ..config import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("reference", "model"), default="reference")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="graphmine-query-evaluation-") as directory:
        isolated = replace(settings, data_root=Path(directory))
        report = asyncio.run(evaluate(isolated, mode=args.mode))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "mode",
                    "model_accuracy_measured",
                    "passed",
                    "total",
                    "by_slice",
                )
            }
        )
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
