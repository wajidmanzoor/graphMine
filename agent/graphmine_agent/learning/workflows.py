"""Repeatable multi-turn development probes over verified synthetic graphs.

Cases are derived from source contracts and independent references, never from
model answers. These are developer regressions, not an untouched test set or
training examples.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx

from ..config import Settings
from ..history import HistoryStore
from ..models import utc_now
from ..terminal import ClientError, Terminal, agent_client
from .corpus import digest, load_corpus
from .oracles import expected_answer, key
from .pipeline import check_agent_outcome
from .teacher import local_endpoint

VERSION = "conversation-regressions-v1"


def build_workflows(manifest: dict, graphs: dict) -> list[dict]:
    examples = [row for row in manifest["examples"] if row["split"] != "test"]
    records = {row["id"]: row for row in manifest["graphs"]}
    general = [
        row for row in examples if row["task"]["operation_id"] == "maximum-clique"
    ]
    if not general:
        raise ValueError("Conversation probes require general relationship graphs")

    def pick(domain):
        return next((row for row in general if row["domain"] == domain), general[0])

    def task_for(graph_id, operation, behavior="execute"):
        return next(
            row
            for row in examples
            if row["graph_id"] == graph_id
            and row["task"]["operation_id"] == operation
            and row["task"]["behavior"] == behavior
        )

    def step(example, query=None, *, parameters=None, filters=None, intent=None):
        task = copy.deepcopy(example["task"])
        task["query"] = query or task["query"]
        task["intent"]["objective"] = task["query"]
        if parameters is not None:
            task["parameters"].update(parameters)
        if filters is not None:
            task["filters"] = copy.deepcopy(filters)
            task["intent"]["filters"] = copy.deepcopy(filters)
        if intent:
            task["intent"].update(intent)
        task["oracle"] = expected_answer(graphs[example["graph_id"]], task)
        return {"source_example": example["id"], "query": task["query"], "task": task}

    def year(value):
        return [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": value,
            }
        ]

    def case(identifier, example, steps):
        return {
            "id": identifier,
            "domain": example["domain"],
            "graph_id": example["graph_id"],
            "graph_path": records[example["graph_id"]]["path"],
            "family": example["family"],
            "steps": steps,
        }

    cases = []
    base = pick("social_networks")
    groups = task_for(base["graph_id"], "maximal-cliques")
    weighted = task_for(base["graph_id"], "betweenness-centrality", "unsupported")
    cases.append(
        case(
            "scope-corrections",
            base,
            [
                step(
                    groups,
                    "Using only 2026 relationships, " + groups["task"]["query"],
                    filters=year(2026),
                ),
                step(
                    groups,
                    "Sorry, use 2025 instead. Keep the same group rules.",
                    filters=year(2025),
                ),
                step(
                    groups,
                    "Drop the year restriction and include all years. Keep the same group rules.",
                    filters=[],
                ),
                step(weighted),
                step(
                    groups,
                    "Go back to the unweighted groups from all years. "
                    + groups["task"]["query"],
                ),
            ],
        )
    )
    base = pick("bioinformatics")
    groups = task_for(base["graph_id"], "maximal-cliques")
    cases.append(
        case(
            "group-quantifiers",
            base,
            [
                step(base),
                step(
                    groups,
                    "Now I need every group of at least three, not just one biggest group. "
                    "Every pair must have interacted directly; leave out groups contained in a larger such group.",
                ),
                step(
                    base,
                    "Actually, show just one largest group again. One is enough if several tie.",
                ),
            ],
        )
    )
    base = pick("fraud_detection")
    ambiguous = task_for(base["graph_id"], None, "clarify")
    connectors = task_for(base["graph_id"], "betweenness-centrality")
    weighted = task_for(base["graph_id"], "betweenness-centrality", "unsupported")
    cases.append(
        case(
            "clarification-and-refusal",
            base,
            [
                step(ambiguous),
                step(
                    connectors,
                    "I mean those connecting others along the fewest relationship steps. "
                    "Rank all names by how often they lie on shortest routes between other accounts.",
                ),
                step(weighted),
            ],
        )
    )
    base = next(
        row for row in examples if row["task"]["operation_id"] == "maximal-bicliques"
    )
    cases.append(
        case(
            "customer-bundles",
            base,
            [
                step(base),
                step(
                    base,
                    "Make that at least three customers; leave the product minimum at two. "
                    "Still list every bundle that cannot be enlarged on either side.",
                    parameters={"minimum_left_size": 3, "minimum_right_size": 2},
                ),
                step(
                    base,
                    "Actually, at least two customers and three products. "
                    "Keep every shared bundle that cannot be enlarged on either side; customers may buy other items too.",
                    parameters={"minimum_left_size": 2, "minimum_right_size": 3},
                ),
            ],
        )
    )
    base = next(
        row
        for row in examples
        if row["task"]["operation_id"] == "temporal-motif-mining"
        and row["task"]["behavior"] == "execute"
    )
    unsupported = task_for(base["graph_id"], "temporal-motif-mining", "unsupported")
    unit = graphs[base["graph_id"]]["graph"]["attributes"]["timestamp_unit"]
    scale = 1000 if unit == "milliseconds" else 1
    cases.append(
        case(
            "event-window",
            base,
            [
                step(base),
                step(
                    base,
                    "Use a five-second window instead, with the same sequence and three distinct hosts.",
                    parameters={"max_time_span": 5 * scale},
                    intent={"time_window": 5, "time_unit": "seconds"},
                ),
                step(unsupported),
                step(
                    base,
                    "Return to three different hosts and the earlier A to B, B to C, A to C sequence, "
                    "now within 20000 milliseconds. List the hosts and event IDs in order.",
                    intent={"time_window": 20000, "time_unit": "milliseconds"},
                ),
            ],
        )
    )
    base = pick("communications_infrastructure")
    core = task_for(base["graph_id"], "k-core")
    cases.append(
        case(
            "partner-threshold",
            base,
            [
                step(
                    core,
                    parameters={
                        "requested_k": core["task"]["parameters"]["requested_k"]
                    },
                ),
                step(
                    core,
                    "Use three remaining direct partners instead. "
                    "Keep removing those below that threshold until no more can be removed, and show the survivors.",
                    parameters={"requested_k": 3},
                ),
                step(
                    core,
                    "Only consider connections from 2026 now; keep the same repeated-removal rule and threshold.",
                    parameters={"requested_k": 3},
                    filters=year(2026),
                ),
            ],
        )
    )
    return cases


def check_workflow_step(graph: dict, task: dict, outcome: dict) -> list[str]:
    issues = check_agent_outcome(graph, task, outcome)
    if task["behavior"] != "execute":
        if (outcome.get("response") or {}).get("plan") is not None:
            issues.append("Non-executable response exposed a plan")
        return issues
    plan = (outcome.get("job") or {}).get("plan") or {}
    actual = plan.get("application_intent") or {}
    for field in ("requires_edge_weights", "requires_direction"):
        if actual.get(field, False) != task["intent"].get(field, False):
            issues.append(f"Requested {field} changed")
    if task["operation_id"] == "temporal-motif-mining":
        for field in ("pattern_vertex_count", "pattern_edges"):
            if key(actual.get(field)) != key(task["intent"][field]):
                issues.append(f"Requested event {field} changed")
    return issues


def restore_reused_outcome(
    outcome: dict,
    *,
    history: Path,
    session_id: str,
    source_graph: Path,
) -> dict:
    """Bind an explanation/reuse to saved native evidence, not a model's claim.

    The regular CLI need not fetch a result again when displaying an LLM
    interpretation. The evaluator does: reusing an exactly matching analysis
    is valid, but only after its source, parameters and output are rechecked.
    """
    response = outcome.get("response") or {}
    if (
        response.get("mode") != "analyst"
        or not response.get("result_id")
        or response.get("job_id")
        or response.get("job_ids")
    ):
        return outcome
    root = history / HistoryStore.identifier(session_id)
    evidence = []

    def read(relative):
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Reused evidence escaped its session directory")
        value = json.loads(path.read_text())
        evidence.append({"path": str(path), "sha256": HistoryStore.digest(path)})
        return value

    result_id = HistoryStore.identifier(response["result_id"])
    result = read(f"results/{result_id}/result.json")
    job_id = HistoryStore.identifier(result["job_id"])
    job = read(f"jobs/{job_id}/job.json")
    if (
        result.get("id") != result_id
        or result.get("session_id") != session_id
        or job.get("id") != job_id
        or job.get("session_id") != session_id
        or job.get("result_id") != result_id
        or job.get("status") != "completed"
    ):
        raise ValueError(
            "Reused result is not bound to a completed job in this session"
        )
    graph_id = HistoryStore.identifier(job["plan"]["graph_id"])
    metadata = read(f"files/{graph_id}/metadata.json")
    if (
        metadata["file"]["session_id"] != session_id
        or metadata["file"]["id"] != graph_id
        or metadata["file"]["sha256"] != HistoryStore.digest(source_graph)
    ):
        raise ValueError("Reused result belongs to another source graph")
    original = (root / "files" / graph_id / "original").resolve()
    if not original.is_relative_to(root.resolve()) or HistoryStore.digest(
        original
    ) != HistoryStore.digest(source_graph):
        raise ValueError("Reused source graph bytes changed")
    evidence.append({"path": str(original), "sha256": HistoryStore.digest(original)})
    # Grade the interpretation actually sent on this turn, not a later snapshot.
    result["interpretation"] = response.get("interpretation") or {}
    return {
        **outcome,
        "job": job,
        "result": result,
        "reused_result": True,
        "reuse_evidence": evidence,
    }


def recheck_workflows(*, corpus: Path, report_path: Path, output: Path) -> dict:
    """Read-only regrading; preserve the original run and any earlier feedback."""
    if output.exists():
        raise ValueError("Recheck output exists; preserve previous evidence")
    manifest, graphs = load_corpus(corpus)
    original = json.loads(report_path.read_text())
    if (
        original.get("mode") != VERSION
        or not original.get("finished_at")
        or original.get("corpus_sha256")
        != HistoryStore.digest(corpus / "manifest.json")
    ):
        raise ValueError("A completed workflow run on this exact corpus is required")
    selected = {case["id"] for case in original["cases"]}
    cases = [
        case for case in build_workflows(manifest, graphs) if case["id"] in selected
    ]
    if digest(cases) != original["cases_sha256"] or cases != original["cases"]:
        raise ValueError("Workflow questions or expected contracts changed")
    by_id = {case["id"]: case for case in cases}
    report = copy.deepcopy(original)
    report.update(
        mode=VERSION + "-recheck",
        rechecked_at=utc_now().isoformat(),
        original_report={
            "path": str(report_path.resolve()),
            "sha256": HistoryStore.digest(report_path),
        },
        grading_source_sha256={
            name: HistoryStore.digest(Path(__file__).with_name(name))
            for name in ("workflows.py", "pipeline.py", "oracles.py")
        },
    )
    history = Path(original["data_directory"]) / "history"
    identities = set()
    for trial in report["trials"]:
        case = by_id.get(trial["id"])
        identity = trial["id"], trial["repetition"]
        if (
            not case
            or identity in identities
            or len(trial["steps"]) != len(case["steps"])
            or not 1 <= trial["repetition"] <= original["repeats"]
        ):
            raise ValueError("Incomplete, duplicate or unknown workflow trial")
        identities.add(identity)
        for row, step in zip(trial["steps"], case["steps"], strict=True):
            if row["query"] != step["query"]:
                raise ValueError("Observed question changed")
            observed = row["observed"]
            extra = []
            try:
                observed = restore_reused_outcome(
                    observed,
                    history=history,
                    session_id=trial["session_id"],
                    source_graph=corpus / case["graph_path"],
                )
            except (KeyError, ValueError, OSError, TypeError) as error:
                extra.append(f"Reused-result evidence failed: {error}")
            issues = (
                check_workflow_step(graphs[case["graph_id"]], step["task"], observed)
                + extra
            )
            row.update(
                original_passed=row["passed"],
                original_issues=row["issues"],
                passed=not issues,
                issues=issues,
                observed=observed,
            )
    if len(identities) != len(cases) * original["repeats"]:
        raise ValueError("Missing workflow trials")
    rows = [row for trial in report["trials"] for row in trial["steps"]]
    report.update(
        passed=sum(row["passed"] for row in rows),
        total=len(rows),
        workflows_passed=sum(
            all(row["passed"] for row in trial["steps"]) for trial in report["trials"]
        ),
    )
    HistoryStore.write(output, report)
    return report


async def evaluate_workflows(
    settings: Settings,
    *,
    corpus: Path,
    output: Path,
    data_dir: Path,
    case_ids: set[str] | None = None,
    repeats: int = 1,
) -> dict:
    if not 1 <= repeats <= 3:
        raise ValueError("Choose one to three complete workflow trials")
    if (
        output.exists()
        or data_dir.exists()
        or data_dir.resolve() == settings.data_root.resolve()
    ):
        raise ValueError("Use a new report and isolated runtime directory")
    if not settings.llm_enabled:
        raise ValueError(
            "Conversation evaluation requires the real local language model"
        )
    local_endpoint(settings.llm_base_url)
    manifest, graphs = load_corpus(corpus)
    all_cases = build_workflows(manifest, graphs)
    if case_ids and case_ids - {row["id"] for row in all_cases}:
        raise ValueError("Unknown workflow case IDs")
    cases = [row for row in all_cases if not case_ids or row["id"] in case_ids]
    root = Path(__file__).parent.parent
    report = {
        "schema_version": "1.0.0",
        "mode": VERSION,
        "started_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "cases_sha256": digest(cases),
        "cases": cases,
        "repeats": repeats,
        "trials": [],
        "model": settings.llm_model,
        "data_directory": str(data_dir.resolve()),
        "source_sha256": {
            name: HistoryStore.digest(root / name)
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
            )
        },
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
        "scope": "Automatically derived multi-turn developer regressions, not an untouched evaluation or training corpus. Exact contracts/reference solvers check behavior; no human usability or general accuracy claim.",
        "training_started": False,
        "external_teacher_calls": 0,
    }

    def save(finished=False):
        rows = [step for trial in report["trials"] for step in trial["steps"]]
        report.update(
            passed=sum(row["passed"] for row in rows),
            total=len(rows),
            workflows_passed=sum(
                len(row["steps"]) == row["expected_steps"]
                and all(step["passed"] for step in row["steps"])
                for row in report["trials"]
            ),
        )
        if finished:
            report["finished_at"] = utc_now().isoformat()
        HistoryStore.write(output, report)

    async with agent_client(
        replace(settings, history_directory=None), data_dir=data_dir
    ) as (client, history):
        for repetition in range(1, repeats + 1):
            for case in cases:
                terminal = Terminal(client, history_root=history, output=lambda _: None)
                await terminal.start(
                    domain_id=case["domain"],
                    title=f"Workflow {case['id']} trial {repetition}",
                )
                await terminal.load(corpus / case["graph_path"])
                trial = {
                    "id": case["id"],
                    "repetition": repetition,
                    "session_id": terminal.session_id,
                    "history_path": str(history / terminal.session_id),
                    "expected_steps": len(case["steps"]),
                    "steps": [],
                }
                report["trials"].append(trial)
                for index, step in enumerate(case["steps"], 1):
                    print(
                        f"[{case['id']} trial {repetition}, turn {index}] {step['query']}",
                        flush=True,
                    )
                    started = time.monotonic()
                    try:
                        outcome = await terminal.ask(step["query"])
                    except (ClientError, httpx.HTTPError) as error:
                        outcome = {**terminal.last_outcome, "error": str(error)}
                    reuse_issues = []
                    try:
                        outcome = restore_reused_outcome(
                            outcome,
                            history=history,
                            session_id=terminal.session_id,
                            source_graph=corpus / case["graph_path"],
                        )
                    except (KeyError, ValueError, OSError, TypeError) as error:
                        reuse_issues.append(f"Reused-result evidence failed: {error}")
                    issues = (
                        check_workflow_step(
                            graphs[case["graph_id"]], step["task"], outcome
                        )
                        + reuse_issues
                    )
                    record = {
                        "index": index,
                        "query": step["query"],
                        "turn_id": terminal.turn_id,
                        "passed": not issues,
                        "issues": issues,
                        "observed": outcome,
                        "elapsed_seconds": time.monotonic() - started,
                    }
                    if issues:
                        feedback = await terminal.feedback(
                            "; ".join(issues),
                            "Preserve the current question, corrections and earlier unchanged requirements. "
                            "Use the named original records and exact reference-checked answer; refuse unsupported calculations without starting a job.",
                            source="assistant_evaluation",
                        )
                        record["feedback_id"] = feedback["id"]
                    trial["steps"].append(record)
                    save()
                    print(
                        f"{'PASS' if not issues else 'ISSUE'} ({record['elapsed_seconds']:.1f}s): {issues}",
                        flush=True,
                    )
                HistoryStore.write(
                    history / terminal.session_id / "workflow-evaluation.json", trial
                )
    save(finished=True)
    return report
