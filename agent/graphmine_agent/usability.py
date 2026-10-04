"""Replay domain-language workflows through the conversational CLI client.

Contract checks are deliberately narrower than a human usability assessment.
Raw turns and reviewer feedback remain linked to the actual session history.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .database import Database
from .history import HistoryStore
from .models import FeedbackCreate, utc_now
from .terminal import ClientError, Terminal, agent_client


def lookup(value: Any, path: str) -> Any:
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def assess(expected: dict, outcome: dict) -> list[str]:
    issues = []
    if outcome.get("error"):
        issues.append("The request failed: " + outcome["error"])
    response = outcome.get("response") or {}
    job = outcome.get("job") or {}
    result = outcome.get("result") or {}
    behavior = expected["behavior"]
    if behavior == "execute":
        if job.get("status") != "completed":
            issues.append("No new completed computation answered this request.")
        if result.get("operation_id") not in expected.get("operations", []):
            issues.append(
                f"Expected one of {expected.get('operations', [])}; got {result.get('operation_id') or response.get('mode', 'no operation')}."
            )
        payload = result.get("payload", {})
        if expected.get("analysis_operations"):
            actual_operations = {
                step["operation_id"]
                for step in result.get("answer", {}).get("steps", {}).values()
            }
            if actual_operations != set(expected["analysis_operations"]):
                issues.append(
                    f"Expected the complete analysis workflow {expected['analysis_operations']}; got {sorted(actual_operations)}."
                )
        for check in expected.get("checks", []):
            paths = check.get("paths", [check.get("path")])
            observed = None
            found = False
            for path in paths:
                try:
                    observed = lookup(
                        result.get("answer", {})
                        if check.get("scope") == "answer"
                        else payload,
                        path,
                    )
                    found = True
                    break
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
            target = check["value"]
            try:
                if check["kind"] == "groups":
                    matched = {frozenset(group) for group in observed} == {
                        frozenset(group) for group in target
                    }
                elif check["kind"] == "set":
                    matched = set(observed) == set(target)
                elif check["kind"] == "length":
                    matched = len(observed) == target
                else:
                    matched = observed == target
            except (TypeError, ValueError):
                matched = False
            if not found or not matched:
                issues.append(
                    f"Expected {paths} {check['kind']} {target!r}; observed {observed!r}."
                )
        if result and not (result.get("interpretation") or {}).get("visualizations"):
            issues.append("No visualization choice was provided.")
    elif response.get("job_id") or job:
        issues.append(
            f"Expected a {behavior} response before running; the system started a computation."
        )
    elif not response.get("message"):
        issues.append(f"No {behavior} explanation was returned.")
    elif response.get("planning_status") != {
        "clarify": "needs_information",
        "unsupported": "unsupported",
    }.get(behavior):
        issues.append(
            f"Expected {behavior}; received planning status {response.get('planning_status')!r}."
        )
    return issues


async def evaluate_applications(
    settings: Settings,
    *,
    cases_path: Path,
    output: Path,
    data_dir: Path,
    case_ids: set[str] | None = None,
    timeout_seconds: float = 600,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError(
            f"Evaluation output already exists: {output}. Choose a new output path to preserve evidence."
        )
    corpus = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [
        case for case in corpus["cases"] if case_ids is None or case["id"] in case_ids
    ]
    if not cases:
        raise ValueError("No matching application cases")
    if case_ids and case_ids - {case["id"] for case in cases}:
        raise ValueError(
            "Unknown case IDs: "
            + ", ".join(sorted(case_ids - {case["id"] for case in cases}))
        )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "started_at": utc_now().isoformat(),
        "cases_sha256": HistoryStore.digest(cases_path),
        "agent_source_sha256": {
            str(path.relative_to(settings.repository_root)): HistoryStore.digest(path)
            for path in sorted(
                (settings.repository_root / "agent/graphmine_agent").rglob("*")
            )
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
        },
        "model": settings.llm_model,
        "real_llm": settings.llm_enabled,
        "inference_settings": {
            "route_reasoning": settings.llm_route_reasoning_effort,
            "plan_reasoning": settings.llm_plan_reasoning_effort,
            "analyst_reasoning": "none (verified-fact selection)",
            "plan_max_tokens": settings.llm_plan_max_tokens,
        },
        "contract_sha256": {
            str(path.relative_to(settings.repository_root)): HistoryStore.digest(path)
            for path in (
                settings.catalog_path,
                settings.manifest_path,
                settings.program_instructions_path,
                settings.backend_policy_path,
            )
        },
        "data_directory": str(data_dir.resolve()),
        "scope": "Small synthetic end-to-end application probes; contract checks are not a general usability or model-accuracy score. Human review is required for wording, grounding and visualization usefulness.",
        "cases": [],
    }
    async with agent_client(settings, data_dir=data_dir) as (client, history_root):
        probe = Terminal(client, output=lambda _: None)
        health = await probe.request("GET", "/api/health")
        if not health["llm"]["enabled"] or not health["llm"]["available"]:
            raise ClientError(
                "Application evaluation requires the live language model; offline keyword matching cannot measure this workflow."
            )
        if health["status"] != "ready":
            raise ClientError(
                "The GraphMine runtime is not ready for end-to-end evaluation."
            )
        report["runtime"] = health
        for case in cases:
            transcript: list[str] = []
            terminal = Terminal(
                client,
                history_root=history_root,
                timeout_seconds=timeout_seconds,
                output=transcript.append,
            )
            await terminal.start(
                domain_id=case["domain"], title=f"Application evaluation: {case['id']}"
            )
            graph_path = cases_path.parent / "graphs" / case["graph"]
            await terminal.load(graph_path)
            case_report = {
                "id": case["id"],
                "domain": case["domain"],
                "graph": case["graph"],
                "graph_sha256": HistoryStore.digest(graph_path),
                "session_id": terminal.session_id,
                "history_path": str(history_root / terminal.session_id),
                "steps": [],
            }
            report["cases"].append(case_report)
            for index, step in enumerate(case["steps"], 1):
                print(
                    f"[{case['id']} {index}/{len(case['steps'])}] {step['query']}",
                    flush=True,
                )
                for upload in step.get("uploads_before", []):
                    await terminal.load(
                        cases_path.parent / "graphs" / upload["path"],
                        role=upload["role"],
                    )
                started = time.monotonic()
                try:
                    outcome = await terminal.ask(step["query"])
                except (ClientError, httpx.HTTPError) as error:
                    outcome = terminal.last_outcome
                    outcome["error"] = str(error)
                issues = assess(step["expected"], outcome)
                record = {
                    "query": step["query"],
                    "expected": step["expected"],
                    "turn_id": terminal.turn_id,
                    "job_id": terminal.job_id,
                    "result_id": terminal.result_id,
                    "elapsed_seconds": time.monotonic() - started,
                    "contract_passed": not issues,
                    "issues": issues,
                    "observed": outcome,
                }
                if issues:
                    feedback = await terminal.feedback(
                        " ".join(issues),
                        step["expected"]["user_expectation"],
                        source="assistant_evaluation",
                    )
                    record["feedback_id"] = feedback["id"]
                case_report["steps"].append(record)
                HistoryStore.write(output, report)
                print(
                    f"  {'PASS' if not issues else 'ISSUE'}: {outcome.get('job', {}).get('status', 'no job')} / {outcome.get('result', {}).get('operation_id', 'no new result')}; {record['elapsed_seconds']:.1f}s",
                    flush=True,
                )
            HistoryStore.write(
                history_root / terminal.session_id / "evaluation.json", case_report
            )
            HistoryStore.write(
                history_root / terminal.session_id / "terminal-transcript.json",
                transcript,
            )
    steps = [step for case in report["cases"] for step in case["steps"]]
    report.update(
        {
            "finished_at": utc_now().isoformat(),
            "case_count": len(report["cases"]),
            "query_count": len(steps),
            "contract_passed": sum(step["contract_passed"] for step in steps),
            "contract_failed": sum(not step["contract_passed"] for step in steps),
        }
    )
    HistoryStore.write(output, report)
    return report


def run_application_evaluation(settings: Settings, **kwargs) -> dict[str, Any]:
    return asyncio.run(evaluate_applications(settings, **kwargs))


async def evaluate_followup(
    settings: Settings, report_path: Path, probe_path: Path, output: Path
) -> dict:
    """A focused probe can resume an actual prior run without replaying it."""
    if output.exists():
        raise ValueError(f"Evaluation output already exists: {output}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    case = next(item for item in report["cases"] if item["id"] == probe["resume_case"])
    async with agent_client(settings, data_dir=Path(report["data_directory"])) as (
        client,
        history_root,
    ):
        terminal = Terminal(client, history_root=history_root)
        await terminal.start(session_id=case["session_id"])
        started = time.monotonic()
        try:
            outcome = await terminal.ask(probe["query"])
        except ClientError as error:
            outcome = terminal.last_outcome
            outcome["error"] = str(error)
        issues = assess(probe["expected"], outcome)
        result = {
            **probe,
            "probe_sha256": HistoryStore.digest(probe_path),
            "session_id": terminal.session_id,
            "turn_id": terminal.turn_id,
            "job_id": terminal.job_id,
            "result_id": terminal.result_id,
            "elapsed_seconds": time.monotonic() - started,
            "observed": outcome,
            "issues": issues,
            "contract_passed": not issues,
        }
        if issues:
            result["feedback_id"] = (
                await terminal.feedback(
                    " ".join(issues),
                    probe["expected"]["user_expectation"],
                    source="assistant_evaluation",
                )
            )["id"]
        HistoryStore.write(output, result)
        HistoryStore.write(
            history_root / terminal.session_id / "followup-evaluation.json", result
        )
        return result


def save_review(report_path: Path, reviews_path: Path, output: Path) -> dict:
    """Persist explicitly authored reviewer observations as labeled feedback.

    This does not call an LLM, infer a pass from successful execution, or use review
    feedback as model conversation. A new report preserves the original observations.
    """
    if output.exists():
        raise ValueError(f"Reviewed report already exists: {output}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in report["cases"]}
    database = Database(Path(report["data_directory"]) / "agent.sqlite3")
    saved = []
    for review in reviews["reviews"]:
        case = cases[review["case_id"]]
        step = case["steps"][review["step"] - 1]
        # Use the recorded directory even if the evaluation used an override.
        database.history = HistoryStore(Path(case["history_path"]).parent)
        feedback = database.add_feedback(
            case["session_id"],
            FeedbackCreate(
                what_went_wrong=review["finding"],
                expected_behavior=review["expected_behavior"],
                turn_id=step["turn_id"],
                job_id=step.get("job_id"),
                result_id=step.get("result_id"),
                source="assistant_evaluation",
            ),
        )
        item = {**review, "feedback_id": feedback.id}
        saved.append(item)
        database.history.snapshot(
            case["session_id"], f"reviews/{feedback.id}.json", item
        )
    report["manual_review"] = {
        "source": "assistant_evaluation",
        "reviewed_at": utc_now().isoformat(),
        "reviews_sha256": HistoryStore.digest(reviews_path),
        "reviews": saved,
    }
    HistoryStore.write(output, report)
    return report
