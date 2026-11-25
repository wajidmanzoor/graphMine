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
    from graphmine_agent.config import Settings
    from graphmine_agent.llm_power import model_run
    settings = replace(Settings.from_env(ROOT), llm_enabled=True)
    async with model_run(settings) as power:
        return await _evaluate(args, settings, power)


async def _evaluate(args, settings, power):
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest, family_catalog, route_catalog, route_schema

    suite = json.loads(args.suite.read_text())
    native = json.loads(subprocess.check_output([str(args.binary.resolve()), "catalog"], text=True))
    cards = native["problems"]
    topics = json.loads((ROOT / "catalog/problems.json").read_text())
    problem_family = {op: family for family, group in topics.items()
                        for op in group}
    sources = {str(path): sha(path) for path in args.application_source.rglob("*.py")}
    sources.update({str(args.suite): sha(args.suite), str(Path(__file__)): sha(Path(__file__))})
    report = {"scope": suite["scope"], "pipeline": args.pipeline,
              "suite_sha256": sha(args.suite), "sources": sources,
              "model": settings.analytics_router_model or settings.llm_model,
              "native_implementation_sha256": native["implementation_sha256"],
              "family_metric": "Explicit family decision for hierarchical routing; family inferred from the selected problem for the previous flat router. Both are scored in the new taxonomy.",
              "cases": []}
    planner = AnalyticsPlanner(settings, SimpleNamespace(database=SimpleNamespace(capture=None), llm_power=power), None)
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
               "acceptable_problems": case["problems"]}
        started = time.monotonic()
        try:
            payload = {"question": case["question"], "removed_problems": [], "problem_hints": {},
                       "selection_context": "Choose the mathematical task only; required datasets and parameters will be supplied in later planning."}
            if args.pipeline == "hierarchical":
                decision, _problems = await planner._route_problems(
                    PlanningRequest(message=case["question"]), payload, cards, cards,
                    facts=[], targets=None, input_facts=[], lookups=[], sources=[], remember=remember)
                families = [step["family_id"] for step in trace if step["stage"] == "family"]
                row["initial_family"] = families[0] if families else None
                row["selected_family"] = families[-1] if families else None
            else:
                decision = await planner._generate("route", payload, route_schema(cards),
                                                   catalog=route_catalog(cards, family_catalog(cards)))
                selected = decision.get("problems", [])
                row["selected_family"] = problem_family.get(selected[0]) if selected else None
                row["initial_family"] = row["selected_family"]
            row["decision"] = decision
            row["family_correct"] = row["selected_family"] == case["family"]
            row["problem_correct"] = (bool(set(decision.get("problems", [])) & set(case["problems"]))
                                        if case["problems"] else None)
        except Exception as error:
            row.update(error={"type": type(error).__name__, "message": str(error)}, family_correct=False,
                       problem_correct=False if case["problems"] else None)
        finally:
            planner._generate = original
        row.update(seconds=round(time.monotonic() - started, 3), trace=trace, calls=calls)
        report["cases"].append(row)
        print(case["id"], row["family_correct"], row["problem_correct"], flush=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    report["per_family"] = {}
    for family in topics:
        rows = [row for row in report["cases"] if row["expected_family"] == family]
        problems = [row for row in rows if row["problem_correct"] is not None]
        report["per_family"][family] = {
            "family_correct": sum(row["family_correct"] for row in rows), "family_total": len(rows),
            "problem_correct": sum(row["problem_correct"] for row in problems), "problem_total": len(problems)}
    valid = [row for row in report["cases"] if "error" not in row]
    scored = [row for row in valid if row["problem_correct"] is not None]
    clarified = [row for row in valid if row["decision"]["intent"] == "needs_information"]
    expected_clarification = [row for row in valid if not row["acceptable_problems"]]
    report["metrics"] = {
        "completed_cases": len(valid), "unavailable_cases": len(report["cases"]) - len(valid),
        "correct_calculation_rate": sum(row["problem_correct"] for row in scored) / len(scored) if scored else None,
        "clarification_rate": len(clarified) / len(valid) if valid else None,
        "useful_clarification_rate": sum(row in clarified for row in expected_clarification) / len(expected_clarification) if expected_clarification else None,
        "model_calls_per_question": sum(len(row["calls"]) for row in valid) / len(valid) if valid else None,
        "parameter_selection_rate": None, "workflow_success_rate": None,
        "scope": "Routing only; parameter and workflow execution require the corresponding integration suites."}
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
