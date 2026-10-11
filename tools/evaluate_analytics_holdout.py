#!/usr/bin/env python3
"""Freeze and run assistant-authored held-out routing/conversation cases.

This is a local held-out study, not a public NLP benchmark or human annotation.
Answers come from small independent enumerations, not the model or native core.
Freeze once before any model run; never tune on its results.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import random
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.getenv("GRAPHMINE_APPLICATION_SOURCE", str(ROOT / "agent")))
sys.path.insert(0, str(APP))


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def freeze(path):
    if path.exists():
        raise ValueError("Held-out suite already exists; refusing to replace it")
    rng = random.Random(11072026)
    vertices = [f"station-{rng.randrange(1000, 9999)}" for _ in range(7)]
    pairs = list(itertools.combinations(range(4), 2)) + [(3, 4), (4, 5)]
    graph = {
        "graph": {
            "id": "heldout-stations",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {"id": v, "attributes": {"zone": "blue" if i % 2 else "green"}}
            for i, v in enumerate(vertices)
        ],
        "edges": [
            {
                "id": f"route-{i}",
                "source": vertices[u],
                "target": vertices[v],
                "weight": rng.randrange(1, 9),
                "attributes": {"amount": rng.randrange(10, 90)},
            }
            for i, (u, v) in enumerate(pairs)
        ],
    }
    cases = []

    def add(name, question, operations, checks, *, data=graph, **extra):
        cases.append(
            {
                "id": name,
                "question": question,
                "input": data,
                "operations": operations,
                "checks": checks,
                "expected_status": "ready",
                **extra,
            }
        )

    def check(operation, port, kind, value):
        return {"operation": operation, "port": port, "kind": kind, "value": value}

    add(
        "triangles",
        "How many undirected triangles are in the whole network? Return the count only.",
        ["triangle-counting"],
        [check("triangle-counting", "count", "equal", 4)],
    )
    add(
        "maximum_clique",
        "Return one maximum clique: I need the globally largest complete group, not merely a maximal one.",
        ["maximum-clique"],
        [check("maximum-clique", "vertices", "set", vertices[:4])],
    )
    edge_set = {frozenset((vertices[u], vertices[v])) for u, v in pairs}
    subsets = [set(c) for k in range(8) for c in itertools.combinations(vertices, k)]
    independent = [s for s in subsets if all(not e <= s for e in edge_set)]
    maximum = max(map(len, independent))
    add(
        "independent_optimum",
        "Find an exact maximum independent set of the full undirected graph.",
        ["maximum-independent-set"],
        [
            check(
                "maximum-independent-set",
                "vertices",
                "one_of_sets",
                [sorted(s) for s in independent if len(s) == maximum],
            )
        ],
    )
    covers = [s for s in subsets if all(e & s for e in edge_set)]
    minimum = min(map(len, covers))
    add(
        "cover_optimum",
        "Find an exact minimum vertex cover, with no bound k.",
        ["minimum-vertex-cover"],
        [
            check(
                "minimum-vertex-cover",
                "vertices",
                "one_of_sets",
                [sorted(s) for s in covers if len(s) == minimum],
            )
        ],
    )
    add(
        "components",
        "Give the weakly connected components of this graph, including isolated vertices.",
        ["connected-components"],
        [
            check(
                "connected-components",
                "groups",
                "partition",
                [vertices[:6], vertices[6:]],
            )
        ],
    )
    start = vertices[0]
    add(
        "bfs",
        f"Run breadth-first search from string ID {start} on the whole graph without a depth limit.",
        ["breadth-first-search"],
        [check("breadth-first-search", "vertices", "set", vertices[:6])],
        required_parameters={"breadth-first-search": {"sources": [start]}},
    )
    distances = {v: math.inf for v in vertices}
    distances[start] = 0
    for _ in vertices:
        for e in graph["edges"]:
            u, v, w = e["source"], e["target"], e["weight"]
            distances[v] = min(distances[v], distances[u] + w)
            distances[u] = min(distances[u], distances[v] + w)
    add(
        "weighted_distance",
        f"Compute single-source shortest paths from string ID {start}. Edge weights are travel costs; use them, with no cutoff.",
        ["single-source-shortest-paths"],
        [
            check(
                "single-source-shortest-paths",
                "distances",
                "scores",
                {v: None if math.isinf(d) else d for v, d in distances.items()},
            )
        ],
        required_parameters={"single-source-shortest-paths": {"source": start}},
    )
    add(
        "filtered_records",
        "Show all edge records with attributes.amount greater than or equal to 50.",
        ["edge-filter"],
        [
            check(
                "edge-filter",
                "edges",
                "set",
                [e["id"] for e in graph["edges"] if e["attributes"]["amount"] >= 50],
            )
        ],
    )
    add(
        "incoming_records",
        f"Return every neighbor of {vertices[5]} at one hop, excluding that vertex itself. Respect the graph's undirected edges.",
        ["neighbors"],
        [check("neighbors", "vertices", "set", [vertices[4]])],
    )
    add(
        "vertex_filter",
        "Return all vertices with attributes.zone equal to blue.",
        ["node-lookup"],
        [check("node-lookup", "vertices", "set", vertices[1::2])],
    )
    add(
        "aggregate",
        "Sum attributes.amount over all edge records as one overall total; do not group the rows.",
        ["graph-aggregate"],
        [
            check(
                "graph-aggregate",
                "rows",
                "aggregate_total",
                sum(e["attributes"]["amount"] for e in graph["edges"]),
            )
        ],
        required_parameters={
            "graph-aggregate": {
                "scope": "edges",
                "metric": "sum",
                "field": "attributes.amount",
            }
        },
    )
    typed = {
        "graph": {
            "id": "heldout-typed",
            "directed": True,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": 0}, {"id": "0"}, {"id": 9007199254740993}],
        "edges": [],
    }
    add(
        "numeric_identity",
        "Look up just the vertex whose ID is the integer 0. Return its full record.",
        ["node-lookup"],
        [check("node-lookup", "vertices", "equal", [0])],
        data=typed,
    )
    add(
        "string_identity",
        'Look up just the vertex whose ID is the string "0". Return its full record.',
        ["node-lookup"],
        [check("node-lookup", "vertices", "equal", ["0"])],
        data=typed,
    )
    flow = {
        "graph": {
            "id": "heldout-flow",
            "directed": True,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": v} for v in ["supply", "left", "right", "demand"]],
        "edges": [
            {"id": i, "source": u, "target": v, "weight": w}
            for i, (u, v, w) in enumerate(
                [
                    ("supply", "left", 7),
                    ("supply", "right", 3),
                    ("left", "right", 2),
                    ("left", "demand", 4),
                    ("right", "demand", 6),
                ]
            )
        ],
    }
    cut = min(
        sum(
            e["weight"]
            for e in flow["edges"]
            if e["source"] in s and e["target"] not in s
        )
        for k in range(3)
        for inside in itertools.combinations(["left", "right"], k)
        for s in [{"supply", *inside}]
    )
    add(
        "flow_capacity",
        "Compute exact maximum flow from supply to demand using directed edge weights as capacities, and return the cut side.",
        ["max-flow-min-cut"],
        [check("max-flow-min-cut", "value", "equal", cut)],
        data=flow,
        required_parameters={
            "max-flow-min-cut": {
                "source": "supply",
                "sink": "demand",
                "capacity_mode": "edge_weight",
            }
        },
    )
    add(
        "derived_network",
        f"Use query-subgraph in vertex mode to induce the graph on {', '.join(vertices[:4])}, then count triangles in that derived graph only.",
        ["query-subgraph", "triangle-counting"],
        [
            check("query-subgraph", "vertices", "set", vertices[:4]),
            check("triangle-counting", "count", "equal", 4),
        ],
        required_graph_dependency={"triangle-counting": "query-subgraph"},
    )
    previous = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "reach",
                "operation": "breadth-first-search",
                "input": {"input": "main"},
                "parameters": {"sources": [start]},
            }
        ],
    }
    add(
        "followup_scope",
        "Keep that BFS source and the same input, but limit the search to two hops.",
        ["breadth-first-search"],
        [check("breadth-first-search", "vertices", "set", vertices[:5])],
        previous_plan=previous,
        required_parameters={
            "breadth-first-search": {"sources": [start], "depth_limit": 2}
        },
    )
    add(
        "wrong_family_recovery",
        "Count all triangles in this undirected graph. Only the exact count is needed.",
        ["triangle-counting"],
        [check("triangle-counting", "count", "equal", 4)],
        family_id="importance",
        require_reroute=True,
    )
    for name, question in [
        ("ambiguous_importance", "Who is most important in this network?"),
        ("ambiguous_group", "Find the best group of connected stations."),
        (
            "missing_training",
            "Train a supervised node classifier for my private labels, which I have not uploaded yet.",
        ),
    ]:
        cases.append(
            {
                "id": name,
                "question": question,
                "input": graph,
                "expected_status": "needs_information",
            }
        )
    suite = {
        "version": "native-workflow-heldout-20261011-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": 11072026,
        "scope": "20 assistant-authored held-out questions over new fictional graphs, frozen after development prompt changes and before model evaluation; no human labels, public NLP benchmark, or training use. Independent subset, cut, path-relaxation and record oracles.",
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(suite, indent=2, allow_nan=False) + "\n")
    print("Frozen", len(cases), "cases; sha256", digest(suite))


def check_value(check, port):
    if not port or not port.get("complete"):
        return False
    value, want, kind = port["value"], check["value"], check["kind"]
    # Canonical JSON hashes preserve numeric/string identity, unlike Python sets.
    typed_set = lambda rows: {digest(x) for x in rows}
    if kind == "equal":
        return digest(value) == digest(want)
    if kind == "set":
        return typed_set(value) == typed_set(want)
    if kind == "one_of_sets":
        return any(typed_set(value) == typed_set(option) for option in want)
    if kind == "partition":
        return {frozenset(typed_set(row["vertices"])) for row in value} == {
            frozenset(typed_set(row)) for row in want
        }
    if kind == "scores":
        actual = {row["vertex"]: row[port.get("score_field", "score")] for row in value}
        return actual.keys() == want.keys() and all(actual[v] == want[v] for v in want)
    if kind == "aggregate_total":
        return (
            len(value) == 1
            and value[0]["exact_value"]["numerator"] == str(want)
            and value[0]["exact_value"]["denominator"] == "1"
        )
    raise ValueError(kind)


def validate_oracles(suite, output):
    """Check fixed answers and their port parser before exposing cases to the model."""
    sys.path.insert(0, str(ROOT / "python/graphmine"))
    from graphmine.native import NativeLibrary

    library = NativeLibrary()
    rows = []
    for case in suite["cases"]:
        if case["expected_status"] != "ready":
            continue
        data, results, requests = case["input"], {}, []
        for operation in case["operations"]:
            params = dict(case.get("required_parameters", {}).get(operation, {}))
            current = data
            if operation == "edge-filter":
                params = {
                    "edge_filters": [
                        {"field": "attributes.amount", "op": "gte", "value": 50}
                    ]
                }
            if operation == "neighbors":
                params = {"entity": data["vertices"][5]["id"]}
            if operation == "node-lookup":
                params = (
                    {"vertices": [0]}
                    if case["id"] == "numeric_identity"
                    else {"vertices": ["0"]}
                    if case["id"] == "string_identity"
                    else {
                        "vertex_filters": [
                            {"field": "attributes.zone", "op": "eq", "value": "blue"}
                        ]
                    }
                )
            if operation == "query-subgraph":
                params = {
                    "mode": "vertices",
                    "vertices": [v["id"] for v in data["vertices"][:4]],
                }
            if operation == "triangle-counting" and "query-subgraph" in results:
                current = results["query-subgraph"]["ports"]["graph"]["value"]
            results[operation] = library.run(
                operation, current, parameters=params, device="cpu"
            )
            requests.append(
                {
                    "operation": operation,
                    "parameters": params,
                    "input_sha256": digest(current),
                }
            )
        checks = [
            check_value(c, results[c["operation"]]["ports"].get(c["port"]))
            for c in case["checks"]
        ]
        assert all(checks), case["id"]
        rows.append({"id": case["id"], "checks": checks, "requests": requests})
    output.write_text(
        json.dumps(
            {
                "scope": "Frozen independent answers cross-checked through native C ABI before held-out model evaluation",
                "suite_sha256": digest(suite),
                "passed": len(rows),
                "cases": rows,
                "implementation_sha256": library.catalog()["implementation_sha256"],
                "grader_source_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print("Verified independent answers and port parsing for", len(rows), "cases")


async def evaluate(settings, suite, output):
    from graphmine_agent.analytics import AnalyticsService, WorkflowRequest
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
    from graphmine_agent.database import Database
    from graphmine_agent.graph_store import GraphStore
    from graphmine_agent.jobs import EventBus
    from graphmine_agent.models import FileRole, SessionRecord

    db = Database(settings.database_path)
    store = GraphStore(settings, db)
    events = EventBus(db)
    service = AnalyticsService(settings, db, store, events)
    planner = AnalyticsPlanner(settings, service, events)
    service.open()
    rows = []
    try:
        caps = await service.capabilities()
        defaults = {
            c["id"]: {
                k: v["default"] for k, v in c["parameters"].items() if "default" in v
            }
            for c in caps["operations"]
        }
        for case in suite["cases"]:
            session = db.create_session(SessionRecord(domain_id="general"))
            file = store.ingest(
                session_id=session.id,
                role=FileRole.graph,
                filename=case["id"] + ".json",
                content=json.dumps(case["input"]).encode(),
            )
            inputs = {"main": {"file_id": file.id}}
            evaluation_id = suite["version"] + "/" + case["id"]
            previous = None
            if case.get("previous_plan"):
                previous = (
                    await service.create(
                        session.id,
                        WorkflowRequest(
                            mode="interactive",
                            plan=case["previous_plan"],
                            inputs=inputs,
                            evaluation_id=evaluation_id,
                        ),
                    )
                )["id"]
            row = {"id": case["id"], "passed": False}
            started = time.monotonic()
            try:
                proposal = await planner.plan(
                    session.id,
                    PlanningRequest(
                        message=case["question"],
                        inputs=inputs,
                        device="cpu",
                        family_id=case.get("family_id"),
                        previous_workflow_id=previous,
                        evaluation_id=evaluation_id,
                    ),
                )
                row["planning"] = proposal
                if case["expected_status"] != "ready":
                    row["passed"] = proposal["status"] == case[
                        "expected_status"
                    ] and not proposal.get("plan")
                elif proposal["status"] == "ready":
                    saved = await service.create(
                        session.id,
                        WorkflowRequest(
                            mode="normal",
                            plan=proposal["plan"],
                            inputs=inputs,
                            evaluation_id=evaluation_id,
                        ),
                    )
                    await asyncio.gather(*service.tasks.values())
                    result = service.result(saved["id"])
                    steps = {s["operation"]: s for s in result["plan"]["steps"]}
                    checks = []
                    for check in case["checks"]:
                        step = steps.get(check["operation"], {})
                        port = (
                            result["steps"]
                            .get(step.get("id"), {})
                            .get("result", {})
                            .get("ports", {})
                            .get(check["port"])
                        )
                        checks.append(
                            {
                                **check,
                                "passed": check_value(check, port),
                                "observed": port.get("value") if port else None,
                            }
                        )
                    exact_operations = sorted(
                        s["operation"] for s in result["plan"]["steps"]
                    ) == sorted(case["operations"])
                    params = all(
                        op in steps
                        and all(
                            digest({**defaults[op], **steps[op]["parameters"]}.get(k))
                            == digest(v)
                            for k, v in values.items()
                        )
                        for op, values in case.get("required_parameters", {}).items()
                    )
                    wiring = all(
                        consumer in steps
                        and source in steps
                        and steps[consumer]["input"]
                        == {"step": steps[source]["id"], "port": "graph"}
                        for consumer, source in case.get(
                            "required_graph_dependency", {}
                        ).items()
                    )
                    recovered = not case.get("require_reroute") or any(
                        t["stage"] == "operation" and t.get("status") == "reroute"
                        for t in proposal["trace"]
                    )
                    row.update(
                        operations=exact_operations,
                        required_parameters=params,
                        wiring=wiring,
                        required_reroute=recovered,
                        result_checks=checks,
                        workflow_hash=result["workflow_hash"],
                        result_sha256=digest(result),
                    )
                    row["passed"] = (
                        result["status"] == "completed"
                        and result["complete"]
                        and exact_operations
                        and params
                        and wiring
                        and recovered
                        and all(c["passed"] for c in checks)
                    )
            except (ValueError, OSError, TimeoutError) as exc:
                row["error"] = str(exc)
            row["elapsed_seconds"] = time.monotonic() - started
            rows.append(row)
            print(row["id"], "passed" if row["passed"] else "failed", flush=True)
            output.with_suffix(".partial.json").write_text(
                json.dumps(rows, indent=2, allow_nan=False) + "\n"
            )
    finally:
        await service.close()
    return {
        "scope": suite["scope"],
        "suite_sha256": digest(suite),
        "model_accuracy_measured": any(row.get("planning") is not None for row in rows),
        "reviewed_examples_excluded": True,
        "cases": rows,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "capabilities_sha256": digest(caps),
        "implementation_sha256": caps["implementation_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--check-oracles", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze(args.suite)
        return
    if args.check_oracles:
        validate_oracles(json.loads(args.suite.read_text()), args.output)
        return
    from graphmine_agent.config import Settings

    suite = json.loads(args.suite.read_text())
    files = [
        Path(__file__),
        args.suite,
        *sorted((APP / "graphmine_agent").rglob("*.py")),
        ROOT / "catalog/native_execution_evidence.json",
    ]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    settings = Settings.from_env(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="graphmine-model-heldout-") as directory:
        report = asyncio.run(
            evaluate(replace(settings, data_root=Path(directory)), suite, args.output)
        )
    report.update(
        source_files=before,
        sources_unchanged_during_run=before
        == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        model={
            "name": settings.analytics_planner_model or settings.llm_model,
            "base_revision": os.getenv("GRAPHMINE_LLM_REVISION"),
            "reasoning_effort": settings.analytics_reasoning_effort,
            "max_completion_tokens": settings.llm_plan_max_tokens,
            "temperature": 0,
            "seed": 0,
        },
    )
    assert report["sources_unchanged_during_run"]
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(report["passed"], "/", report["total"])


if __name__ == "__main__":
    main()
