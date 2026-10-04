"""Frozen practical conversations with native, presentation and scope checks.

Development-only validation graphs; no oracle feedback is sent to the model.
Original grader findings are retained alongside numeric-semantic filter checks.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx

from ..history import HistoryStore
from ..models import utc_now
from ..terminal import ClientError, Terminal
from . import adapter_workflows, workflows
from .adapter_eval import ARMS, read_suite
from .business_curriculum import load
from .business_questions import wording_issues
from .corpus import digest, load_corpus
from .oracles import expected_answer
from .presentation_checks import check_presentation
from .realworld_eval import _fresh_runtime

VERSION = "practical-business-conversations-v1"


def build_cases(curriculum: Path):
    manifest, graphs = load(curriculum)
    source, _ = load_corpus(Path(manifest["source_corpus"]))
    records = {row["id"]: row for row in source["graphs"]}
    examples = [row for row in manifest["examples"] if row["split"] == "validation"]

    def pick(domain, operation, behavior="execute"):
        return next(
            row
            for row in examples
            if row["domain"] == domain
            and row["task"]["operation_id"] == operation
            and row["task"]["behavior"] == behavior
            and not row["task"]["filters"]
        )

    def step(example, query=None, *, parameters=None, filters=None, intent=None):
        task = copy.deepcopy(example["task"])
        task["query"] = query or task["query"]
        task["intent"]["objective"] = task["query"]
        if parameters:
            task["parameters"].update(parameters)
        if filters is not None:
            task["filters"] = copy.deepcopy(filters)
            task["intent"]["filters"] = copy.deepcopy(filters)
        if intent:
            task["intent"].update(intent)
        issues = wording_issues(task["query"])
        if issues:
            raise ValueError(
                f"Business conversation exposes implementation language: {issues}"
            )
        task["oracle"] = expected_answer(graphs[example["graph_id"]], task)
        return {"source_example": example["id"], "query": task["query"], "task": task}

    def case(identifier, example, steps):
        return {
            "id": identifier,
            "domain": example["domain"],
            "graph_id": example["graph_id"],
            "graph_path": records[example["graph_id"]]["path"],
            "family": example["family"],
            "steps": steps,
        }

    def selected(field, value, operator="eq"):
        return [
            {
                "target": "edges",
                "field": f"attributes.{field}",
                "operator": operator,
                "value": value,
            }
        ]

    team = pick("social_networks", "maximum-clique")
    teams = pick("social_networks", "maximal-cliques")
    fraud = pick("fraud_detection", "maximal-cliques")
    vague_fraud = pick("fraud_detection", None, "clarify")
    weighted = pick("fraud_detection", "betweenness-centrality", "unsupported")
    intermediaries = pick("fraud_detection", "betweenness-centrality")
    service = pick("communications_infrastructure", "k-core")
    threshold = service["task"]["parameters"]["requested_k"]
    retail = pick("recommendation_ecommerce", "maximal-bicliques")
    incident = pick("cybersecurity", "temporal-motif-mining")
    relay = pick("cybersecurity", "temporal-motif-mining", "unsupported")
    scale = (
        1000
        if graphs[incident["graph_id"]]["graph"]["attributes"]["timestamp_unit"]
        == "milliseconds"
        else 1
    )
    protein = pick("bioinformatics", "k-cliques")
    vague_protein = pick("bioinformatics", None, "clarify")
    outreach = pick("social_networks", "community-detection")
    return [
        case(
            "business-project-staffing",
            team,
            [
                step(team),
                step(
                    teams,
                    "Actually, we are staffing several projects. Give me every ready-made team of at least three colleagues who have all worked with one another. Keep full teams and leave out smaller teams entirely inside another option.",
                ),
                step(
                    team,
                    "We are back to one project. Just give me one biggest ready-made team whose members have all worked together; one option is enough if teams tie.",
                ),
            ],
        ),
        case(
            "business-team-year-corrections",
            teams,
            [
                step(
                    teams,
                    "Use only 2026 collaborations for this workshop plan. "
                    + teams["task"]["query"],
                    filters=selected("year", 2026),
                ),
                step(
                    teams,
                    "Sorry, use 2025 collaborations instead. Keep the same workshop-team requirements.",
                    filters=selected("year", 2025),
                ),
                step(
                    teams,
                    "Open the workshop plan to collaborations from all years. Keep the same team requirements.",
                    filters=[],
                ),
            ],
        ),
        case(
            "business-investigation-clarification",
            fraud,
            [
                step(vague_fraud),
                step(
                    fraud,
                    "I mean complete payment circles as leads for manual review. "
                    + fraud["task"]["query"],
                ),
            ],
        ),
        case(
            "business-payment-cost-selection",
            weighted,
            [
                step(weighted),
                step(
                    intermediaries,
                    "Then just use payment relationships with recorded cost exactly 5 for this cost-tier review. Rank every account by how often the fewest-transfer chains between other accounts pass through it. Cost is only the selection criterion; treat all remaining payment links equally and don't claim this traces actual funds.",
                    filters=selected("cost", 5),
                    intent={
                        "requires_edge_weights": False,
                        "weight_attribute": None,
                        "weight_usage": None,
                    },
                ),
            ],
        ),
        case(
            "business-service-pool",
            service,
            [
                step(service),
                step(
                    service,
                    f"Raise the requirement to {threshold + 1} direct neighbors inside the service pool for every included device. Give me the full pool meeting that rule together, with no outside connections counted.",
                    parameters={"requested_k": threshold + 1},
                ),
            ],
        ),
        case(
            "business-bundle-audience",
            retail,
            [
                step(retail),
                step(
                    retail,
                    "For this promotion, require at least three customers in each audience, still sharing at least two products bought by everyone in that audience. Keep every full audience with its full shared purchase set and list customers separately from products.",
                    parameters={"minimum_left_size": 3},
                ),
            ],
        ),
        case(
            "business-incident-window",
            incident,
            [
                step(incident),
                step(
                    incident,
                    "Tighten the review to sequences that finish within five seconds of starting. Keep the same order of contacts, three different machines, and event details.",
                    parameters={"max_time_span": 5 * scale},
                    intent={"time_window": 5, "time_unit": "seconds"},
                ),
                step(
                    relay,
                    "For a different incident lead, count and list relays from a first machine to a second, then to a third, then to a fourth, all distinct and in that order. Allow 20 seconds overall and show the machines and event records.",
                ),
            ],
        ),
        case(
            "business-assay-clarification-empty-selection",
            protein,
            [
                step(vague_protein),
                step(
                    protein,
                    "I mean candidates for three-protein assay batches. "
                    + protein["task"]["query"],
                ),
                step(
                    protein,
                    "For this check, keep the same three-protein batch request but use only assay relationships whose score is exactly zero. Use the score column, not ascore, and tell me if no batches qualify.",
                    filters=selected("score", 0),
                ),
            ],
        ),
        case("business-outreach-groups", outreach, [step(outreach)]),
    ]


def normalized_filters(filters):
    def scalar(value):
        if type(value) in (int, float):
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError("Non-finite filter value")
            text = format(number, "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return ["number", "0" if not number else text]
        if isinstance(value, list):
            return ["list", [scalar(item) for item in value]]
        return [type(value).__name__, value]

    return sorted(
        json.dumps({**row, "value": scalar(row["value"])}, sort_keys=True)
        for row in filters
    )


def grade_step(graph, task, outcome):
    original = workflows.check_workflow_step(graph, task, outcome)
    issues = list(original)
    actual = ((outcome.get("job") or {}).get("plan") or {}).get(
        "application_intent"
    ) or {}
    numeric_equivalence = False
    if "Requested attribute scope changed" in issues and normalized_filters(
        actual.get("filters", [])
    ) == normalized_filters(task.get("filters", [])):
        issues.remove("Requested attribute scope changed")
        numeric_equivalence = True
    issues.extend(check_presentation(graph, task, outcome))
    return issues, original, numeric_equivalence


def code_hashes():
    root = Path(__file__).parent.parent
    paths = [
        root / name
        for name in (
            "agent_service.py",
            "planning.py",
            "llm.py",
            "models.py",
            "graph_context.py",
            "answers.py",
            "visualization.py",
            "terminal.py",
            "learning/workflows.py",
            "learning/pipeline.py",
            "learning/oracles.py",
            "learning/presentation_checks.py",
            "learning/adapter_workflows.py",
            "learning/business_workflows.py",
        )
    ]
    return {str(path.resolve()): HistoryStore.digest(path) for path in paths}


def prepare(curriculum: Path, output: Path):
    if output.exists():
        raise ValueError("Preserve prior business conversation suites")
    manifest, _ = load(curriculum)
    cases = build_cases(curriculum)
    output.mkdir(parents=True, mode=0o700)
    result = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "curriculum": str(curriculum.resolve()),
        "curriculum_sha256": HistoryStore.digest(curriculum / "manifest.json"),
        "source_corpus": manifest["source_corpus"],
        "source_corpus_sha256": manifest["source_corpus_sha256"],
        "source_sha256": code_hashes(),
        "cases": cases,
        "cases_sha256": digest(cases),
        "case_count": len(cases),
        "turn_count": sum(len(case["steps"]) for case in cases),
        "oracle_feedback_sent": False,
        "scope": "Authored practical development conversations on validation graphs. Some initial wording was used for validation token loss. Not independent customer evaluation or the reserved-source test.",
        "grading_policy": "Original native and requirement checks plus presentation checks. Numeric filter equality accepts integer/float representations of the same number, keeping field, operator, string and boolean distinctions. Original grader issues remain recorded.",
    }
    HistoryStore.write(output / "suite.json", result)
    (output / "builder.py").write_bytes(Path(__file__).read_bytes())
    return result


def read(conversations: Path):
    result = json.loads((conversations / "suite.json").read_text())
    if result["version"] != VERSION or result["source_sha256"] != code_hashes():
        raise ValueError("Business conversation implementation changed")
    curriculum = Path(result["curriculum"])
    if HistoryStore.digest(curriculum / "manifest.json") != result["curriculum_sha256"]:
        raise ValueError("Business conversation curriculum changed")
    if (
        result["cases"] != build_cases(curriculum)
        or result["cases_sha256"] != digest(result["cases"])
        or result["case_count"] != len(result["cases"])
        or result["turn_count"] != sum(len(case["steps"]) for case in result["cases"])
    ):
        raise ValueError(
            "Business conversation questions, coverage or contracts changed"
        )
    return result


async def evaluate_cases(
    settings, *, case_suite, corpus, output, data_dir, repeats=1, case_ids=None
):
    if case_ids or not 1 <= repeats <= 3:
        raise ValueError("Evaluate one to three complete practical conversation trials")
    if str(corpus.resolve()) != case_suite["source_corpus"]:
        raise ValueError("Conversation graph source differs from its frozen suite")
    _fresh_runtime(settings, output, data_dir)
    _, graphs = load_corpus(corpus)
    cases = case_suite["cases"]
    report = {
        "schema_version": "1.0.0",
        "mode": VERSION,
        "started_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "business_curriculum_sha256": case_suite["curriculum_sha256"],
        "source_sha256": case_suite["source_sha256"],
        "cases_sha256": digest(cases),
        "cases": cases,
        "repeats": repeats,
        "trials": [],
        "model": settings.llm_model,
        "data_directory": str(data_dir.resolve()),
        "oracle_feedback_sent": False,
        "holdout_model_calls": 0,
        "training_export_allowed": False,
        "scope": case_suite["scope"],
        "grading_policy": case_suite["grading_policy"],
        "inference_profile": {
            name: getattr(settings, name)
            for name in (
                "llm_route_reasoning_effort",
                "llm_plan_reasoning_effort",
                "llm_analyst_reasoning_effort",
                "llm_route_max_tokens",
                "llm_plan_max_tokens",
                "llm_analyst_max_tokens",
            )
        },
    }

    def save(finished=False):
        steps = [step for trial in report["trials"] for step in trial["steps"]]
        report.update(
            passed=sum(step["passed"] for step in steps),
            total=len(steps),
            expected_total=sum(len(case["steps"]) for case in cases) * repeats,
            workflows_passed=sum(
                len(trial["steps"]) == trial["expected_steps"]
                and all(step["passed"] for step in trial["steps"])
                for trial in report["trials"]
            ),
        )
        if finished:
            report["finished_at"] = utc_now().isoformat()
        HistoryStore.write(output, report)

    save()
    async with workflows.agent_client(settings, data_dir=data_dir) as (client, history):
        for repetition in range(1, repeats + 1):
            for case in cases:
                terminal = Terminal(
                    client,
                    history_root=history,
                    output=lambda _: None,
                    timeout_seconds=180,
                )
                await terminal.start(
                    domain_id=case["domain"],
                    title=f"Business: {case['id']} / {repetition}",
                )
                source_graph = corpus / case["graph_path"]
                await terminal.load(source_graph)
                trial = {
                    "case_id": case["id"],
                    "repetition": repetition,
                    "session_id": terminal.session_id,
                    "history_path": str(history / terminal.session_id),
                    "expected_steps": len(case["steps"]),
                    "steps": [],
                }
                report["trials"].append(trial)
                for index, step in enumerate(case["steps"], 1):
                    started = time.monotonic()
                    original, numeric_equivalence, outcome = [], False, {}
                    try:
                        async with asyncio.timeout(180):
                            outcome = await terminal.ask(step["query"])
                        outcome = workflows.restore_reused_outcome(
                            outcome,
                            history=history,
                            session_id=terminal.session_id,
                            source_graph=source_graph,
                        )
                        issues, original, numeric_equivalence = grade_step(
                            graphs[case["graph_id"]], step["task"], outcome
                        )
                    except (
                        ClientError,
                        httpx.HTTPError,
                        ValueError,
                        KeyError,
                        OSError,
                        TimeoutError,
                    ) as error:
                        outcome = {
                            **terminal.last_outcome,
                            "error": f"{type(error).__name__}: {error}",
                        }
                        issues = [outcome["error"]]
                    trial["steps"].append(
                        {
                            "index": index,
                            "query": step["query"],
                            "turn_id": terminal.turn_id,
                            "passed": not issues,
                            "issues": issues,
                            "original_grader_issues": original,
                            "numeric_filter_equivalence_applied": numeric_equivalence,
                            "elapsed_seconds": time.monotonic() - started,
                            "observed": outcome,
                        }
                    )
                    save()
                    print(
                        json.dumps(
                            {"case": case["id"], "turn": index, "issues": issues}
                        ),
                        flush=True,
                    )
    save(finished=True)
    return report


async def evaluate(
    routing_suite,
    conversations,
    output,
    *,
    arms=ARMS,
    repeats=1,
    reference_native_gpu=None,
):
    cases = read(conversations)
    plan, _, _ = read_suite(routing_suite)
    if plan.get("business_curriculum_sha256") != cases["curriculum_sha256"]:
        raise ValueError(
            "Routing and conversation suites use different business curricula"
        )

    async def evaluator(*args, **kwargs):
        return await evaluate_cases(*args, case_suite=cases, **kwargs)

    with patch.object(workflows, "evaluate_workflows", evaluator):
        return await adapter_workflows.evaluate(
            routing_suite,
            output,
            arms=arms,
            repeats=repeats,
            reference_native_gpu=reference_native_gpu,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("curriculum", type=Path)
    create.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("evaluate")
    run.add_argument("routing_suite", type=Path)
    run.add_argument("conversations", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--reference-native-gpu")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.curriculum, args.output)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("case_count", "turn_count", "cases_sha256")
                }
            )
        )
    else:
        result = asyncio.run(
            evaluate(
                args.routing_suite,
                args.conversations,
                args.output,
                arms=args.arms,
                repeats=args.repeats,
                reference_native_gpu=args.reference_native_gpu,
            )
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
