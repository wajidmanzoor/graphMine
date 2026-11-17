#!/usr/bin/env python3
"""Compare semantic routing on a frozen suite; never execute an algorithm."""

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def evaluate(args):
    sys.path.insert(0, str(args.application_source))
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest, family_catalog, route_catalog, route_schema
    from graphmine_agent.config import Settings

    suite = json.loads(args.suite.read_text())
    native = json.loads(subprocess.check_output([str(args.binary.resolve()), "catalog"], text=True))
    cards = native["operations"]
    problems = json.loads((ROOT / "catalog/problems.json").read_text())
    operation_family = {op: family for family, group in problems.items()
                        for problem in group.values() for op in problem["operation_ids"]}
    settings = replace(Settings.from_env(ROOT), llm_enabled=True)
    sources = {str(path): sha(path) for path in args.application_source.rglob("*.py")}
    sources.update({str(args.suite): sha(args.suite), str(Path(__file__)): sha(Path(__file__))})
    report = {"scope": suite["scope"], "pipeline": args.pipeline,
              "suite_sha256": sha(args.suite), "sources": sources,
              "model": settings.analytics_router_model or settings.llm_model,
              "native_implementation_sha256": native["implementation_sha256"],
              "family_metric": "Explicit family decision for hierarchical routing; family inferred from the selected operation for the previous flat router. Both are scored in the new taxonomy.",
              "cases": []}
    planner = AnalyticsPlanner(settings, SimpleNamespace(database=SimpleNamespace(capture=None)), None)
    for case in suite["cases"]:
        trace, calls = [], []
        original = planner._generate

        async def record(stage, payload, schema, catalog=None):
            calls.append({"stage": stage,
                          "catalog_characters": len(json.dumps(catalog, ensure_ascii=False)) if catalog else 0,
                          "payload_characters": len(json.dumps(payload, ensure_ascii=False))})
            return await original(stage, payload, schema, catalog=catalog)

        async def remember(stage, decision):
            trace.append({"stage": stage, **decision})

        planner._generate = record
        row = {"id": case["id"], "question": case["question"], "expected_family": case["family"],
               "acceptable_operations": case["operations"]}
        started = time.monotonic()
        try:
            payload = {"question": case["question"], "removed_operations": [], "operation_hints": {},
                       "selection_context": "Choose the mathematical task only; required datasets and parameters will be supplied in later planning."}
            if args.pipeline == "hierarchical":
                decision, _operations = await planner._route_problems(
                    PlanningRequest(message=case["question"]), payload, cards, cards,
                    facts=[], targets=None, input_facts=[], lookups=[], sources=[], remember=remember)
                families = [step["family_id"] for step in trace if step["stage"] == "family"]
                row["initial_family"] = families[0] if families else None
                row["selected_family"] = families[-1] if families else None
            else:
                decision = await planner._generate("route", payload, route_schema(cards),
                                                   catalog=route_catalog(cards, family_catalog(cards)))
                selected = decision.get("operations", [])
                row["selected_family"] = operation_family.get(selected[0]) if selected else None
                row["initial_family"] = row["selected_family"]
            row["decision"] = decision
            row["family_correct"] = row["selected_family"] == case["family"]
            row["operation_correct"] = (bool(set(decision.get("operations", [])) & set(case["operations"]))
                                        if case["operations"] else None)
        except Exception as error:
            row.update(error={"type": type(error).__name__, "message": str(error)}, family_correct=False,
                       operation_correct=False if case["operations"] else None)
        finally:
            planner._generate = original
        row.update(seconds=round(time.monotonic() - started, 3), trace=trace, calls=calls)
        report["cases"].append(row)
        print(case["id"], row["family_correct"], row["operation_correct"], flush=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    report["per_family"] = {}
    for family in problems:
        rows = [row for row in report["cases"] if row["expected_family"] == family]
        operations = [row for row in rows if row["operation_correct"] is not None]
        report["per_family"][family] = {
            "family_correct": sum(row["family_correct"] for row in rows), "family_total": len(rows),
            "operation_correct": sum(row["operation_correct"] for row in operations), "operation_total": len(operations)}
    report["sources_unchanged"] = all(sha(Path(path)) == digest for path, digest in sources.items())
    args.output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-source", type=Path, default=ROOT / "agent")
    parser.add_argument("--suite", type=Path, default=ROOT / "agent/evaluation/family_routing_cases.json")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--pipeline", choices=("flat", "hierarchical"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
