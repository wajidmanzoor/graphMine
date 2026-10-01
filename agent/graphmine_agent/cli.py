from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .api import build_runtime, create_app
from .config import Settings
from .evaluation import run_evaluation, run_planning_evaluation
from .models import (
    ChatRequest,
    ChatResponse,
    ExecutionPlan,
    Interpretation,
    PlanningOutcome,
    PlanRequest,
    ResultRecord,
)

SCHEMAS = {
    "execution-plan": ExecutionPlan,
    "plan-request": PlanRequest,
    "planning-outcome": PlanningOutcome,
    "interpretation": Interpretation,
    "chat-request": ChatRequest,
    "chat-response": ChatResponse,
    "result-record": ResultRecord,
}


def export_schemas(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMAS.items():
        path = destination / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="graphmine-agent",
        description="GraphMine's private-LAN agent and API service",
    )
    subcommands = result.add_subparsers(dest="command")
    serve = subcommands.add_parser("serve", help="start the API and bundled web UI")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    subcommands.add_parser(
        "check", help="validate contracts and probe the GraphMine CLI"
    )
    schemas = subcommands.add_parser("export-schemas", help="write public JSON Schemas")
    schemas.add_argument("destination", nargs="?", type=Path)
    evaluation = subcommands.add_parser(
        "evaluate-routing", help="evaluate domain-aware problem/operation routing"
    )
    evaluation.add_argument("--cases", type=Path)
    evaluation.add_argument("--split", default="held_out_evaluation")
    evaluation.add_argument(
        "--case-id",
        action="append",
        help="evaluate only this case ID; repeat to select multiple cases",
    )
    evaluation.add_argument("--output", type=Path)
    plan_evaluation = subcommands.add_parser(
        "evaluate-planning",
        help="evaluate operation-specific parameters, outputs, and auxiliary files",
    )
    plan_evaluation.add_argument("--cases", type=Path)
    plan_evaluation.add_argument("--split", default="held_out_evaluation")
    plan_evaluation.add_argument(
        "--case-id",
        action="append",
        help="evaluate only this case ID; repeat to select multiple cases",
    )
    plan_evaluation.add_argument("--concurrency", type=int, default=2)
    plan_evaluation.add_argument("--output", type=Path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    settings = Settings.from_env()
    if arguments.command in {None, "serve"}:
        uvicorn.run(
            create_app(settings),
            host=getattr(arguments, "host", None) or settings.api_host,
            port=getattr(arguments, "port", None) or settings.api_port,
            reload=getattr(arguments, "reload", False),
        )
        return 0
    if arguments.command == "check":
        runtime = build_runtime(settings)
        report = runtime.runner.probe()
        print(
            json.dumps(
                {
                    "catalog_problem_count": len(runtime.catalog.problems),
                    "operation_count": len(runtime.catalog.instructions),
                    "domain_count": len(runtime.catalog.domains),
                    "capabilities": report.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0 if report.binary_available and not report.error else 1
    if arguments.command == "export-schemas":
        destination = (
            arguments.destination or settings.repository_root / "agent" / "schemas"
        )
        export_schemas(destination)
        print(f"Exported {len(SCHEMAS)} schemas to {destination}")
        return 0
    if arguments.command == "evaluate-routing":
        cases = arguments.cases or (
            settings.repository_root
            / "agent"
            / "evaluation"
            / "domain_query_cases.json"
        )
        report = run_evaluation(
            settings,
            cases,
            split=arguments.split,
            case_ids=set(arguments.case_id) if arguments.case_id else None,
        )
        serialized = json.dumps(report, indent=2) + "\n"
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0 if report["passed"] == report["total"] else 1
    if arguments.command == "evaluate-planning":
        cases = arguments.cases or (
            settings.repository_root
            / "agent"
            / "evaluation"
            / "domain_query_cases.json"
        )
        report = run_planning_evaluation(
            settings,
            cases,
            split=arguments.split,
            concurrency=max(1, arguments.concurrency),
            case_ids=set(arguments.case_id) if arguments.case_id else None,
        )
        serialized = json.dumps(report, indent=2) + "\n"
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0 if report["passed"] == report["total"] else 1
    return 2
