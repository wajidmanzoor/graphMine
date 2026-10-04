"""Command-line entry points for the evaluation-first learning workspace."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Settings
from .corpus import generate_corpus, load_corpus
from .inference import ModelProfile
from .pipeline import audit_native, evaluate_agent, export_candidates, run_pipeline
from .proposals import propose_candidates
from .realworld import load_realworld, prepare_realworld
from .realworld_eval import audit_realworld, evaluate_realworld, prepare_questions
from .review import compare_teachers, review_candidates
from .review_export import export_reviewed
from .teacher import generate_teacher_candidates
from .workflows import evaluate_workflows, recheck_workflows


def add_parser(subcommands) -> None:
    learning = subcommands.add_parser(
        "learning",
        help="generate and evaluate synthetic candidates and public real-data tasks",
    )
    commands = learning.add_subparsers(dest="learning_command", required=True)
    real = commands.add_parser(
        "prepare-real-world",
        help="download catalogued public datasets and create source-separated evaluation slices",
    )
    real.add_argument("--output", type=Path, required=True)
    real.add_argument(
        "--source-cache",
        type=Path,
        help="rebuild offline from a prior download manifest and hash-verified raw bytes",
    )
    real.add_argument(
        "--download",
        action="store_true",
        help="download five bounded public files; otherwise print the source/license plan without writes",
    )
    real_verify = commands.add_parser(
        "verify-real-world",
        help="rebuild public-data projections and labels from saved source bytes",
    )
    real_verify.add_argument("corpus", type=Path)
    real_questions = commands.add_parser(
        "propose-real-world",
        help="calibrate Codex reviewer and generate/review development questions; dry run by default",
    )
    real_questions.add_argument("corpus", type=Path)
    real_questions.add_argument("--output", type=Path, required=True)
    real_questions.add_argument("--execute", action="store_true")
    real_questions.add_argument(
        "--limit-cases",
        type=int,
        help="bound generation/review calls; prioritize distinct tasks and workflows over duplicate single-turn group cards",
    )
    real_questions.add_argument(
        "--allow-codex",
        action="store_true",
        help="permit public-data question calls through existing ChatGPT login; consumes plan allowance",
    )
    for name in ("audit-real-world", "evaluate-real-world"):
        real_run = commands.add_parser(
            name,
            help="check development tasks on public-data slices; never consume the held-out source",
        )
        real_run.add_argument("corpus", type=Path)
        real_run.add_argument("--output", type=Path, required=True)
        real_run.add_argument("--data-dir", type=Path, required=True)
        if name == "evaluate-real-world":
            real_run.add_argument(
                "--questions",
                type=Path,
                help="use qualified Codex questions; otherwise explicitly evaluate original contract templates",
            )
            real_run.add_argument("--repeats", type=int, default=2)
    generate = commands.add_parser(
        "generate", help="create a seeded, split-safe corpus"
    )
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--seed", type=int, default=314159)
    generate.add_argument("--graphs-per-family", type=int, default=2)
    verify = commands.add_parser(
        "verify", help="verify labels, hashes and split isolation"
    )
    verify.add_argument("corpus", type=Path)
    workflows = commands.add_parser(
        "evaluate-workflows",
        help="replay automatically derived multi-turn development cases with the local model",
    )
    workflows.add_argument("corpus", type=Path)
    workflows.add_argument("--output", type=Path, required=True)
    workflows.add_argument("--data-dir", type=Path, required=True)
    workflows.add_argument("--case-id", action="append")
    workflows.add_argument("--repeats", type=int, default=1)
    recheck = commands.add_parser(
        "recheck-workflows",
        help="regrade saved workflow evidence without any model calls",
    )
    recheck.add_argument("corpus", type=Path)
    recheck.add_argument("--report", type=Path, required=True)
    recheck.add_argument("--output", type=Path, required=True)
    for name in ("audit", "evaluate"):
        command = commands.add_parser(
            name,
            help="check native results"
            if name == "audit"
            else "evaluate the live agent on synthetic questions",
        )
        command.add_argument("corpus", type=Path)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument(
            "--split",
            choices=["all", "train", "validation", "test"],
            default="all" if name == "audit" else "test",
        )
        command.add_argument("--limit", type=int)
    export = commands.add_parser(
        "export", help="export oracle-gated intent-routing SFT candidates; never train"
    )
    export.add_argument("corpus", type=Path)
    export.add_argument("--audit", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    reviewed = commands.add_parser(
        "export-reviewed",
        help="recheck all review/replay gates and export eligible training paraphrases",
    )
    reviewed.add_argument("corpus", type=Path)
    for name in ("candidates", "review", "audit", "output"):
        reviewed.add_argument(f"--{name}", type=Path, required=True)
    reviewed.add_argument("--calibration", type=Path)
    paraphrase = commands.add_parser(
        "paraphrase", help="propose quarantined paraphrases with a local model"
    )
    paraphrase.add_argument("corpus", type=Path)
    paraphrase.add_argument("--output", type=Path, required=True)
    paraphrase.add_argument("--count", type=int, default=5)
    paraphrase.add_argument("--model")
    paraphrase.add_argument(
        "--base-url", help="loopback model URL only; no external API calls"
    )
    for name in ("compare-teachers", "review-candidates", "propose-candidates"):
        command = commands.add_parser(
            name,
            help="calibrate reviewer models (dry run by default)"
            if name == "compare-teachers"
            else "propose quarantined wording (dry run by default)"
            if name == "propose-candidates"
            else "blindly check paraphrase meaning and optionally replay it",
        )
        command.add_argument("corpus", type=Path)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument(
            "--provider", choices=["local", "openai", "codex"], default="local"
        )
        command.add_argument(
            "--model", action="append" if name == "compare-teachers" else "store"
        )
        command.add_argument("--base-url", help="local loopback model URL only")
        command.add_argument(
            "--max-output-tokens",
            type=int,
            default=4096,
            help="output limit; for Codex, a post-call acceptance check, not a generation cap",
        )
        command.add_argument("--budget-usd", type=float)
        command.add_argument(
            "--allow-external",
            action="store_true",
            help="explicitly permit synthetic-only OpenAI inference; requires OPENAI_API_KEY and budget",
        )
        command.add_argument(
            "--allow-codex",
            action="store_true",
            help="permit synthetic-only Codex CLI calls using an existing ChatGPT login; consumes plan allowance, no API-key fallback",
        )
        if name in {"compare-teachers", "propose-candidates"}:
            command.add_argument(
                "--execute",
                action="store_true",
                help="perform model calls instead of writing a zero-call comparison plan",
            )
            if name == "propose-candidates":
                command.add_argument("--count", type=int, default=5)
        else:
            command.add_argument("--candidates", type=Path, required=True)
            command.add_argument("--calibration", type=Path)
            command.add_argument(
                "--data-dir",
                type=Path,
                help="new isolated directory for live replay; omitted means no export eligibility",
            )


def run_learning(arguments, settings: Settings) -> int:
    command = arguments.learning_command
    try:
        if command == "prepare-real-world":
            report = prepare_realworld(
                arguments.output,
                download=arguments.download,
                source_cache=arguments.source_cache,
            )
            print(
                json.dumps(
                    report
                    if not arguments.download and arguments.source_cache is None
                    else {
                        "path": str(arguments.output),
                        "graphs": len(report["graphs"]),
                        "cases": len(report["cases"]),
                        "training_started": False,
                    }
                )
            )
            return 0
        if command == "verify-real-world":
            report, _ = load_realworld(arguments.corpus)
            print(
                json.dumps(
                    {
                        "verified": True,
                        "graphs": len(report["graphs"]),
                        "cases": len(report["cases"]),
                    }
                )
            )
            return 0
        if command == "propose-real-world":
            report = run_pipeline(
                prepare_questions,
                settings,
                corpus=arguments.corpus,
                destination=arguments.output,
                execute=arguments.execute,
                allow_codex=arguments.allow_codex,
                limit_cases=arguments.limit_cases,
            )
            print(
                json.dumps(
                    {
                        key: report.get(key)
                        for key in (
                            "executed",
                            "maximum_model_calls",
                            "reviewer_qualified",
                            "screened",
                            "quarantined",
                            "budget",
                        )
                    }
                )
            )
            return 0 if not arguments.execute or report.get("reviewer_qualified") else 1
        if command in {"audit-real-world", "evaluate-real-world"}:
            options = (
                {"questions": arguments.questions, "repeats": arguments.repeats}
                if command == "evaluate-real-world"
                else {}
            )
            report = run_pipeline(
                audit_realworld
                if command == "audit-real-world"
                else evaluate_realworld,
                settings,
                corpus=arguments.corpus,
                output=arguments.output,
                data_dir=arguments.data_dir,
                **options,
            )
            print(json.dumps({key: report[key] for key in ("passed", "total")}))
            return 0 if report["passed"] == report["total"] else 1
        if command == "recheck-workflows":
            report = recheck_workflows(
                corpus=arguments.corpus,
                report_path=arguments.report,
                output=arguments.output,
            )
            print(
                json.dumps(
                    {
                        name: report[name]
                        for name in ("passed", "total", "workflows_passed")
                    }
                )
            )
            return 0 if report["passed"] == report["total"] else 1
        if command == "evaluate-workflows":
            report = run_pipeline(
                evaluate_workflows,
                settings,
                corpus=arguments.corpus,
                output=arguments.output,
                data_dir=arguments.data_dir,
                case_ids=set(arguments.case_id) if arguments.case_id else None,
                repeats=arguments.repeats,
            )
            print(
                json.dumps(
                    {
                        name: report[name]
                        for name in ("passed", "total", "workflows_passed")
                    }
                )
            )
            return 0 if report["passed"] == report["total"] else 1
        if command in {"compare-teachers", "review-candidates", "propose-candidates"}:
            if arguments.provider == "codex" and arguments.budget_usd is not None:
                raise ValueError(
                    "Codex consumes ChatGPT plan allowance, not --budget-usd; bound the number of calls"
                )

            def profile(name):
                return ModelProfile(
                    provider=arguments.provider,
                    model=name,
                    base_url=(arguments.base_url or settings.llm_base_url)
                    if arguments.provider == "local"
                    else arguments.base_url,
                    max_output_tokens=arguments.max_output_tokens,
                )

            if command == "propose-candidates":
                report = run_pipeline(
                    propose_candidates,
                    settings,
                    corpus=arguments.corpus,
                    destination=arguments.output,
                    count=arguments.count,
                    profile=profile(
                        arguments.model
                        or (
                            settings.llm_model
                            if arguments.provider == "local"
                            else "gpt-6.1-sol"
                        )
                    ),
                    execute=arguments.execute,
                    allow_external=arguments.allow_external,
                    allow_codex=arguments.allow_codex,
                    budget_usd=arguments.budget_usd,
                )
                print(
                    json.dumps(
                        {
                            "executed": report["executed"],
                            "calls": len(report["calls"]),
                            "quarantined_candidates": len(report["candidates"]),
                            "estimated_reservation_usd": report[
                                "estimated_total_reservation_usd"
                            ],
                            "fits_requested_budget": report["fits_requested_budget"],
                            "path": str(arguments.output),
                        }
                    )
                )
                return (
                    0
                    if all(call["status"] == "proposed" for call in report["calls"])
                    else 1
                )
            if command == "compare-teachers":
                models = arguments.model or (
                    [settings.llm_model]
                    if arguments.provider == "local"
                    else ["gpt-6.1-sol", "gpt-6-astra"]
                )
                report = run_pipeline(
                    compare_teachers,
                    settings,
                    corpus=arguments.corpus,
                    destination=arguments.output,
                    profiles=[profile(name) for name in models],
                    execute=arguments.execute,
                    allow_external=arguments.allow_external,
                    allow_codex=arguments.allow_codex,
                    budget_usd=arguments.budget_usd,
                )
                print(
                    json.dumps(
                        {
                            "executed": report["executed"],
                            "controls": len(report["controls"]),
                            "models": [
                                {
                                    "model": row["profile"]["model"],
                                    "passed": row["passed"],
                                    "total": row["total"],
                                }
                                for row in report["models"]
                            ],
                            "estimated_reservation_usd": report[
                                "estimated_total_reservation_usd"
                            ],
                            "fits_requested_budget": report["fits_requested_budget"],
                            "path": str(arguments.output),
                        }
                    )
                )
                return (
                    0
                    if not report["executed"]
                    or all(row["qualified_for_screening"] for row in report["models"])
                    else 1
                )
            report = run_pipeline(
                review_candidates,
                settings,
                corpus=arguments.corpus,
                candidates=arguments.candidates,
                destination=arguments.output,
                profile=profile(
                    arguments.model
                    or (
                        settings.llm_model
                        if arguments.provider == "local"
                        else "gpt-6-astra"
                    )
                ),
                calibration=arguments.calibration,
                data_dir=arguments.data_dir,
                allow_external=arguments.allow_external,
                allow_codex=arguments.allow_codex,
                budget_usd=arguments.budget_usd,
            )
            print(
                json.dumps(
                    {
                        name: report[name]
                        for name in (
                            "screened",
                            "replayed",
                            "accepted",
                            "distinct_reviewer",
                            "reviewer_calibrated",
                        )
                    }
                )
            )
            return 0
        if command == "generate":
            report = generate_corpus(
                arguments.output,
                seed=arguments.seed,
                graphs_per_family=arguments.graphs_per_family,
            )
            summary = {
                "graphs": len(report["graphs"]),
                "questions": len(report["examples"]),
                "path": str(arguments.output),
            }
        elif command == "verify":
            report, _ = load_corpus(arguments.corpus)
            summary = {
                "verified": True,
                "graphs": len(report["graphs"]),
                "questions": len(report["examples"]),
            }
        elif command in {"audit", "evaluate"}:
            report = run_pipeline(
                audit_native if command == "audit" else evaluate_agent,
                settings,
                corpus=arguments.corpus,
                output=arguments.output,
                data_dir=arguments.data_dir,
                split=arguments.split,
                limit=arguments.limit,
            )
            summary = {
                "passed": report["passed"],
                "total": report["total"],
                "path": str(arguments.output),
            }
            print(json.dumps(summary))
            return 0 if report["passed"] == report["total"] else 1
        elif command == "export":
            report = export_candidates(
                settings,
                corpus=arguments.corpus,
                audit=arguments.audit,
                destination=arguments.output,
            )
            summary = {
                "candidate_rows": len(report["rows"]),
                "quarantined": len(report["quarantine"]),
                "training_started": False,
                "path": str(arguments.output),
            }
        elif command == "export-reviewed":
            report = export_reviewed(
                settings,
                corpus=arguments.corpus,
                candidates=arguments.candidates,
                review=arguments.review,
                calibration=arguments.calibration,
                audit=arguments.audit,
                destination=arguments.output,
            )
            summary = {
                "candidate_rows": len(report["rows"]),
                "quarantined": len(report["quarantine"]),
                "training_started": False,
                "path": str(arguments.output),
            }
        else:
            report = run_pipeline(
                generate_teacher_candidates,
                settings,
                corpus=arguments.corpus,
                destination=arguments.output,
                count=arguments.count,
                model=arguments.model,
                base_url=arguments.base_url,
            )
            summary = {
                "calls": len(report["calls"]),
                "quarantined_candidates": len(report["candidates"]),
                "training_started": False,
                "path": str(arguments.output),
            }
            print(json.dumps(summary))
            return (
                0
                if all(call["status"] == "proposed" for call in report["calls"])
                else 1
            )
    except (ValueError, OSError) as error:
        raise SystemExit(f"Learning workflow: {error}") from error
    print(json.dumps(summary))
    return 0
