from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from . import __version__
from .api import build_runtime, create_app
from .benchmarking import (
    evaluate_backend_policy,
    run_benchmarks,
    train_backend_policy,
    write_json,
)
from .config import Settings
from .evaluation import run_evaluation, run_planning_evaluation
from .models import (
    ChatRequest,
    ChatResponse,
    ExecutionPlan,
    FeedbackCreate,
    FeedbackRecord,
    Interpretation,
    PlanningOutcome,
    PlanRequest,
    ResultRecord,
)
from .smoke import run_live_smoke_test

SCHEMAS = {
    "execution-plan": ExecutionPlan,
    "plan-request": PlanRequest,
    "planning-outcome": PlanningOutcome,
    "interpretation": Interpretation,
    "chat-request": ChatRequest,
    "chat-response": ChatResponse,
    "result-record": ResultRecord,
    "feedback-create": FeedbackCreate,
    "feedback-record": FeedbackRecord,
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
    from .learning.cli import add_parser

    result = argparse.ArgumentParser(
        prog="graphmine-agent",
        description="GraphMine's private-LAN agent and API service",
    )
    subcommands = result.add_subparsers(dest="command")
    add_parser(subcommands)
    chat = subcommands.add_parser(
        "chat", help="converse with the agent; upload graphs and save feedback"
    )
    chat.add_argument(
        "--base-url", help="connect to an existing API instead of running locally"
    )
    chat.add_argument(
        "--data-dir",
        type=Path,
        help="local store (default: .graphmine-cli in the repository)",
    )
    chat.add_argument("--session", help="resume an existing session")
    chat.add_argument(
        "--domain", default="general", help="domain ID; use /domains to list choices"
    )
    chat.add_argument("--title")
    chat.add_argument("--graph", type=Path)
    chat.add_argument(
        "--directed", action="store_true", help="edge-list connections have a direction"
    )
    chat.add_argument(
        "--message",
        action="append",
        help="send a question or slash command, then exit; repeat for multiple turns",
    )
    chat.add_argument(
        "--script", type=Path, help="read questions and slash commands, one per line"
    )
    chat.add_argument(
        "--json", action="store_true", help="emit JSONL records for scripting"
    )
    chat.add_argument("--timeout-seconds", type=float, default=600)
    usability = subcommands.add_parser(
        "evaluate-usability",
        help="run live application-language workflows and save linked feedback",
    )
    usability.add_argument("--cases", type=Path)
    usability.add_argument("--output", type=Path, required=True)
    usability.add_argument("--data-dir", type=Path)
    usability.add_argument("--case-id", action="append")
    usability.add_argument("--timeout-seconds", type=float, default=600)
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
    evaluation.add_argument("--concurrency", type=int, default=8)
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
    benchmark = subcommands.add_parser(
        "benchmark", help="run a correctness-gated backend benchmark manifest"
    )
    benchmark.add_argument("manifest", type=Path)
    benchmark.add_argument(
        "--output", type=Path, default=Path("benchmark-results/report.json")
    )
    benchmark.add_argument("--warmups", type=int, default=1)
    benchmark.add_argument("--repetitions", type=int, default=3)
    benchmark.add_argument("--timeout-seconds", type=int, default=600)
    train_selector = subcommands.add_parser(
        "train-selector", help="create a deterministic backend policy from a report"
    )
    train_selector.add_argument("report", type=Path)
    train_selector.add_argument("--output", type=Path)
    evaluate_selector = subcommands.add_parser(
        "evaluate-selector", help="measure policy regret on a benchmark report"
    )
    evaluate_selector.add_argument("report", type=Path)
    evaluate_selector.add_argument("--policy", type=Path)
    evaluate_selector.add_argument("--output", type=Path)
    smoke = subcommands.add_parser(
        "smoke-test", help="exercise the live v1 API, GPUs, model, and follow-up flow"
    )
    smoke.add_argument("--base-url")
    smoke.add_argument("--graph", type=Path)
    smoke.add_argument("--timeout-seconds", type=int, default=300)
    smoke.add_argument("--allow-llm-disabled", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    settings = Settings.from_env()
    if arguments.command == "learning":
        from .learning.cli import run_learning

        return run_learning(arguments, settings)
    if arguments.command == "evaluate-usability":
        from .usability import run_application_evaluation

        if arguments.timeout_seconds <= 0:
            raise SystemExit("--timeout-seconds must be positive")
        report = run_application_evaluation(
            settings,
            cases_path=arguments.cases
            or settings.repository_root / "agent/evaluation/applications/cases.json",
            output=arguments.output,
            data_dir=arguments.data_dir or arguments.output.parent / "runtime",
            case_ids=set(arguments.case_id) if arguments.case_id else None,
            timeout_seconds=arguments.timeout_seconds,
        )
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "case_count",
                        "query_count",
                        "contract_passed",
                        "contract_failed",
                    )
                }
            )
        )
        return 0 if report["contract_failed"] == 0 else 1
    if arguments.command == "chat":
        from .terminal import chat_main

        if arguments.timeout_seconds <= 0:
            raise SystemExit("--timeout-seconds must be positive")
        if arguments.base_url and arguments.data_dir:
            raise SystemExit(
                "--data-dir applies only to local mode; omit it when using --base-url"
            )
        return chat_main(settings, arguments)
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
        return (
            0
            if report.binary_available
            and not report.error
            and report.library_version == __version__
            else 1
        )
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
            concurrency=max(1, arguments.concurrency),
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
    if arguments.command == "benchmark":
        report = run_benchmarks(
            settings,
            arguments.manifest,
            warmups=max(0, arguments.warmups),
            repetitions=max(1, arguments.repetitions),
            timeout_seconds=max(1, arguments.timeout_seconds),
        )
        write_json(arguments.output, report)
        print(
            json.dumps(
                {
                    "output": str(arguments.output),
                    "correct_records": report["correct_records"],
                    "total_records": report["total_records"],
                },
                indent=2,
            )
        )
        return 0 if report["correct_records"] == report["total_records"] else 1
    if arguments.command == "train-selector":
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        policy = train_backend_policy(report)
        destination = arguments.output or settings.backend_policy_path
        write_json(destination, policy)
        print(
            json.dumps(
                {
                    "output": str(destination),
                    "operation_count": len(policy["operations"]),
                },
                indent=2,
            )
        )
        return 0
    if arguments.command == "evaluate-selector":
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        policy_path = arguments.policy or settings.backend_policy_path
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        evaluation = evaluate_backend_policy(report, policy)
        if arguments.output:
            write_json(arguments.output, evaluation)
        print(json.dumps(evaluation, indent=2))
        return 0 if evaluation["evaluated_cases"] > 0 else 1
    if arguments.command == "smoke-test":
        if not settings.api_token:
            raise SystemExit("GRAPHMINE_API_TOKEN is required for smoke-test")
        report = run_live_smoke_test(
            base_url=arguments.base_url or f"http://127.0.0.1:{settings.api_port}",
            api_token=settings.api_token,
            graph_path=arguments.graph
            or settings.repository_root
            / "library"
            / "examples"
            / "data"
            / "triangle.json",
            timeout_seconds=max(1, arguments.timeout_seconds),
            require_llm=not arguments.allow_llm_disabled,
        )
        print(json.dumps(report, indent=2))
        return 0
    return 2
