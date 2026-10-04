"""Run reference checks, measure the live agent, and export gated SFT candidates."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path

from ..api import build_runtime
from ..catalog import Catalog
from ..config import Settings
from ..execution import ExecutionError
from ..graph_context import semantic_context
from ..graph_store import GraphStore
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import ExecutionPlan, FeedbackCreate, FileRole, SessionRecord, utc_now
from ..planning import PlanValidationError, route_request_payload
from ..terminal import ClientError, Terminal, agent_client
from .corpus import digest, load_corpus
from .oracles import key, selected_graph, verify_output


def choose_examples(manifest: dict, split: str, limit: int | None = None) -> list[dict]:
    if split not in {"all", "train", "validation", "test"}:
        raise ValueError("Unknown dataset split")
    if limit is not None and limit < 1:
        raise ValueError("Example limit must be positive")
    groups = defaultdict(deque)
    for example in manifest["examples"]:
        if split == "all" or example["split"] == split:
            groups[example["family"]].append(example)
    selected = []
    while groups and (limit is None or len(selected) < limit):
        for family in list(groups):
            selected.append(groups[family].popleft())
            if not groups[family]:
                del groups[family]
            if limit is not None and len(selected) == limit:
                break
    return selected


def _new_report(corpus: Path, output: Path, mode: str, split: str) -> dict:
    if output.exists():
        raise ValueError("Output report exists; choose a new path to preserve evidence")
    return {
        "schema_version": "1.0.0",
        "mode": mode,
        "started_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "split": split,
        "checker_sha256": HistoryStore.digest(Path(__file__).with_name("oracles.py")),
        "source_sha256": HistoryStore.digest(Path(__file__)),
        "examples": [],
    }


def _save(report: dict, output: Path, *, finished: bool = False) -> dict:
    report["passed"] = sum(row["passed"] for row in report["examples"])
    report["total"] = len(report["examples"])
    if finished:
        report["finished_at"] = utc_now().isoformat()
    HistoryStore.write(output, report)
    return report


async def audit_native(
    settings: Settings,
    *,
    corpus: Path,
    output: Path,
    data_dir: Path,
    split: str = "all",
    limit: int | None = None,
) -> dict:
    manifest, graphs = load_corpus(corpus)
    report = _new_report(corpus, output, "native_oracle", split)
    if data_dir.exists() or data_dir.resolve() == settings.data_root:
        raise ValueError(
            "Use a new isolated audit directory, never the running API store"
        )
    runtime = build_runtime(
        replace(
            settings,
            data_root=data_dir.resolve(),
            history_directory=None,
            llm_enabled=False,
        )
    )
    report["data_directory"] = str(data_dir.resolve())
    try:
        runtime.runner.require_ready()
        report["capabilities"] = runtime.runner.capabilities.model_dump(mode="json")
        report["binary_sha256"] = HistoryStore.digest(settings.graphmine_binary)
        report["adapter_source_sha256"] = {
            name: HistoryStore.digest(Path(__file__).parent.parent / name)
            for name in (
                "execution.py",
                "selector.py",
                "planning.py",
                "graph_context.py",
            )
        }
        for example in choose_examples(manifest, split, limit):
            graph, task = graphs[example["graph_id"]], example["task"]
            started = time.monotonic()
            record = {
                "id": example["id"],
                "split": example["split"],
                "example_sha256": digest(example),
                "operation_id": task["operation_id"],
                "behavior": task["behavior"],
                "issues": [],
            }
            if task["behavior"] != "execute":
                # This is a deterministic contract check, not a claim that an
                # LLM will understand the wording. Live evaluation tests that.
                if task["behavior"] == "unsupported":
                    probe = ExecutionPlan(
                        session_id="synthetic",
                        graph_id="synthetic",
                        problem_id=task["problem_id"],
                        operation_id=task["operation_id"],
                        parameters=task["parameters"],
                        application_intent=task["intent"],
                    )
                    try:
                        runtime.validator.validate(probe, for_execution=True)
                    except PlanValidationError:
                        record["contract_refusal"] = True
                    else:
                        record["issues"].append(
                            "Unsupported semantic requirements were accepted"
                        )
                record["verification"] = "template_and_semantic_contract_only"
            else:
                session = runtime.database.create_session(
                    SessionRecord(
                        domain_id=example["domain"],
                        title=f"Synthetic oracle: {example['id']}",
                    )
                )
                with runtime.database.history.scope(
                    session.id,
                    "synthetic_reference",
                    {"example": example["id"], "task": task},
                ) as turn_id:
                    uploaded = runtime.graph_store.ingest(
                        session_id=session.id,
                        role=FileRole.graph,
                        filename="synthetic.json",
                        content=json.dumps(graph).encode(),
                        media_type="application/json",
                    )
                    auxiliary = {}
                    if task["operation_id"] == "maximal-bicliques":
                        partition = [
                            row["id"]
                            for row in graph["vertices"]
                            if row["type"] == "customer"
                        ]
                        file = runtime.graph_store.ingest(
                            session_id=session.id,
                            role=FileRole.left_partition,
                            filename="customers.json",
                            content=json.dumps({"left_partition": partition}).encode(),
                            media_type="application/json",
                        )
                        auxiliary["left_partition"] = [file.id]
                    plan = ExecutionPlan(
                        session_id=session.id,
                        graph_id=uploaded.id,
                        problem_id=task["problem_id"],
                        operation_id=task["operation_id"],
                        parameters=task["parameters"],
                        optional_outputs=task["optional_outputs"],
                        auxiliary_inputs=auxiliary,
                        application_intent=task["intent"],
                    )
                    workspace = runtime.settings.workspaces_root / example["id"]
                    record.update(
                        {
                            "session_id": session.id,
                            "turn_id": turn_id,
                            "plan": plan.model_dump(mode="json"),
                            "workspace": str(workspace),
                            "verification": "independent_native_result_check",
                        }
                    )
                    try:
                        payload, command = await runtime.runner.execute(plan, workspace)
                        record.update(
                            {
                                "payload": payload,
                                "command": command,
                            }
                        )
                        record["issues"] = verify_output(graph, task, payload["output"])
                    except (ExecutionError, ValueError, OSError, KeyError) as error:
                        record["issues"] = [f"{type(error).__name__}: {error}"]
                        for artifact in ("process", "command"):
                            path = workspace / f"{artifact}.json"
                            if path.is_file():
                                record[artifact] = json.loads(path.read_text())
                    if record["issues"]:
                        feedback = runtime.database.add_feedback(
                            session.id,
                            FeedbackCreate(
                                source="assistant_evaluation",
                                turn_id=turn_id,
                                what_went_wrong="; ".join(record["issues"]),
                                expected_behavior="The native computation must complete and match the independently checked answer for this application request: "
                                + task["query"]
                                + ". Reference: "
                                + json.dumps(task["oracle"]),
                            ),
                        )
                        record["feedback_id"] = feedback.id
                    runtime.database.history.current("synthetic.checked", record)
            record.update(
                {
                    "passed": not record["issues"],
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            report["examples"].append(record)
            _save(report, output)
            print(
                f"{'PASS' if record['passed'] else 'ISSUE'} {example['id']}: {record['verification'] if 'verification' in record else record['issues']}",
                flush=True,
            )
    finally:
        await runtime.agent.close()
    return _save(report, output, finished=True)


def check_agent_outcome(graph: dict, task: dict, outcome: dict) -> list[str]:
    issues = [outcome["error"]] if outcome.get("error") else []
    response, job, result = (
        outcome.get(field) or {} for field in ("response", "job", "result")
    )
    if task["behavior"] != "execute":
        if job or response.get("job_id") or response.get("job_ids"):
            issues.append("A non-executable question started a computation")
        expected = (
            "unsupported" if task["behavior"] == "unsupported" else "needs_information"
        )
        if response.get("planning_status") != expected:
            issues.append(
                f"Expected {expected}, received {response.get('planning_status')}"
            )
        return issues
    if (
        job.get("status") != "completed"
        or result.get("operation_id") != task["operation_id"]
    ):
        issues.append(f"No completed {task['operation_id']} result")
        return issues
    plan = job["plan"]
    for name, value in task["parameters"].items():
        if plan["parameters"].get(name) != value:
            issues.append(f"Semantic parameter {name} changed")
    actual_filters = (plan.get("application_intent") or {}).get("filters", [])
    if sorted(map(key, actual_filters)) != sorted(map(key, task.get("filters", []))):
        issues.append("Requested attribute scope changed")
    issues.extend(verify_output(graph, task, result["payload"]["output"]))
    source_ids = {key(row["id"]): row for row in graph["vertices"]}
    answer = result.get("answer", {})
    for row in answer.get("rows", []):
        source = source_ids.get(key(row["id"]))
        if (
            source is None
            or row.get("label") != source.get("label")
            or row.get("attributes", {}) != source.get("attributes", {})
        ):
            issues.append("Original names or attributes were lost in answer rows")
            break
    projection = selected_graph(graph, task.get("filters", []))
    if answer.get("provenance", {}).get("input_edges") != len(projection["edges"]):
        issues.append("Answer provenance does not match the selected input")
    if not result.get("interpretation", {}).get("visualizations"):
        issues.append("No answer visualization was offered")
    if not answer.get("facts"):
        issues.append("No computed answer facts")
    return issues


async def evaluate_agent(
    settings: Settings,
    *,
    corpus: Path,
    output: Path,
    data_dir: Path,
    split: str = "test",
    limit: int | None = None,
) -> dict:
    manifest, graphs = load_corpus(corpus)
    report = _new_report(corpus, output, "live_agent", split)
    if data_dir.exists() or data_dir.resolve() == settings.data_root:
        raise ValueError("Use a new isolated evaluation directory")
    if not settings.llm_enabled:
        raise ValueError("Live corpus evaluation requires a configured language model")
    report.update(
        {
            "model": settings.llm_model,
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
            "agent_source_sha256": {
                name: HistoryStore.digest(Path(__file__).parent.parent / name)
                for name in (
                    "agent_service.py",
                    "llm.py",
                    "planning.py",
                    "answers.py",
                    "visualization.py",
                    "selector.py",
                )
            },
            "data_directory": str(data_dir.resolve()),
            "scope": "Oracle and semantic-contract checks on unseen generator families; not a human usability score or training approval.",
        }
    )
    async with agent_client(
        replace(settings, history_directory=None), data_dir=data_dir
    ) as (client, history):
        for example in choose_examples(manifest, split, limit):
            task = example["task"]
            terminal = Terminal(client, history_root=history, output=lambda _: None)
            await terminal.start(
                domain_id=example["domain"],
                title=f"Synthetic evaluation: {example['id']}",
            )
            file = next(
                item for item in manifest["graphs"] if item["id"] == example["graph_id"]
            )
            await terminal.load(corpus / file["path"])
            started = time.monotonic()
            print(f"Evaluating {example['id']}: {task['query']}", flush=True)
            try:
                outcome = await terminal.ask(task["query"])
            except ClientError as error:
                outcome = {**terminal.last_outcome, "error": str(error)}
            issues = check_agent_outcome(graphs[example["graph_id"]], task, outcome)
            record = {
                "id": example["id"],
                "split": example["split"],
                "example_sha256": digest(example),
                "query": task["query"],
                "session_id": terminal.session_id,
                "turn_id": terminal.turn_id,
                "job_id": terminal.job_id,
                "result_id": terminal.result_id,
                "history_path": str(history / terminal.session_id),
                "elapsed_seconds": time.monotonic() - started,
                "passed": not issues,
                "issues": issues,
                "observed": outcome,
            }
            if issues:
                feedback = await terminal.feedback(
                    "; ".join(issues),
                    "Answer the exact application question, preserving its scope, names, attributes and oracle-checked results; refuse unsupported semantics before execution.",
                    source="assistant_evaluation",
                )
                record["feedback_id"] = feedback["id"]
            report["examples"].append(record)
            _save(report, output)
            print(
                f"{'PASS' if not issues else 'ISSUE'} {example['id']} ({record['elapsed_seconds']:.1f}s): {issues}",
                flush=True,
            )
    return _save(report, output, finished=True)


def export_candidates(
    settings: Settings, *, corpus: Path, audit: Path, destination: Path
) -> dict:
    """Export training/validation messages only; test labels never enter SFT files."""
    manifest, graphs = load_corpus(corpus)
    report = json.loads(audit.read_text())
    if (
        report.get("mode") != "native_oracle"
        or not report.get("finished_at")
        or report["corpus_sha256"] != HistoryStore.digest(corpus / "manifest.json")
    ):
        raise ValueError(
            "A completed native-oracle audit of this exact corpus is required"
        )
    if report.get("checker_sha256") != HistoryStore.digest(
        Path(__file__).with_name("oracles.py")
    ):
        raise ValueError("Oracle checker changed; rerun the audit before exporting")
    if destination.exists():
        raise ValueError("Export destination already exists")
    destination.mkdir(parents=True, mode=0o700)
    catalog = Catalog(settings)
    checks = {row["id"]: row for row in report["examples"]}
    if len(checks) != len(report["examples"]):
        raise ValueError("Duplicate example IDs in the audit")
    provenance, quarantine = [], []
    files = {
        split: (destination / f"{split}.jsonl").open("x", encoding="utf-8")
        for split in ("train", "validation")
    }
    for split in files:
        os.chmod(destination / f"{split}.jsonl", 0o600)
    try:
        for example in manifest["examples"]:
            if example["split"] == "test":
                continue
            check = checks.get(example["id"])
            if (
                not check
                or not check["passed"]
                or check["example_sha256"] != digest(example)
            ):
                quarantine.append(
                    {
                        "id": example["id"],
                        "reason": "missing, failed, or stale independent audit",
                    }
                )
                continue
            graph = graphs[example["graph_id"]]
            if example["task"]["behavior"] == "execute":
                payload = check.get("payload", {})
                issues = verify_output(
                    graph, example["task"], payload.get("output", {})
                )
                if payload.get("ok") is not True or issues:
                    quarantine.append(
                        {
                            "id": example["id"],
                            "reason": "Saved output failed independent revalidation",
                            "issues": issues,
                        }
                    )
                    continue
            payload = training_route_payload(catalog, example, graph)
            messages = [
                {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {
                    "role": "assistant",
                    "content": json.dumps(example["gold_route"], ensure_ascii=False),
                },
            ]
            line = {"messages": messages}
            files[example["split"]].write(json.dumps(line, ensure_ascii=False) + "\n")
            provenance.append(
                {
                    "id": example["id"],
                    "split": example["split"],
                    "family": example["family"],
                    "row_sha256": digest(line),
                    "label_source": "seeded_semantic_template_plus_independent_oracle",
                    "verification": check["verification"],
                    "review_state": "automatic_candidate_not_human_reviewed",
                    "stage": "RouteDecision",
                }
            )
    finally:
        for stream in files.values():
            stream.close()
    metadata = {
        "schema_version": "1.0.0",
        "corpus_sha256": report["corpus_sha256"],
        "audit_sha256": HistoryStore.digest(audit),
        "created_at": utc_now().isoformat(),
        "training_started": False,
        "teacher_model": None,
        "scope": "Intent-routing SFT candidates from semantic templates, not teacher distillation. Test families excluded. No provider upload or weight update.",
        "rows": provenance,
        "quarantine": quarantine,
        "files": {
            split: HistoryStore.digest(destination / f"{split}.jsonl")
            for split in files
        },
    }
    HistoryStore.write(destination / "provenance.json", metadata)
    return metadata


def run_pipeline(function, settings: Settings, **kwargs):
    return asyncio.run(function(settings, **kwargs))


def training_route_payload(catalog, example, graph, *, query=None):
    return route_request_payload(
        message=query or example["task"]["query"],
        graph_context=semantic_context(graph),
        graph_metadata=GraphStore._metadata(example["graph_id"], graph).model_dump(
            mode="json", exclude={"semantic_context"}
        ),
        routing_context=catalog.routing_context(example["domain"]),
    )
