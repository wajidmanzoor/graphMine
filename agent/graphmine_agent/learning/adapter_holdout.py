"""Explicit final evaluation of reserved real-data sources.

This path consumes the source holdout. Development evaluators retain their
original selection and cannot reach it. Failed answers are recorded without
feeding oracle corrections into subsequent model turns.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx

from ..history import HistoryStore
from ..models import utc_now
from ..terminal import ClientError, Terminal, agent_client
from .corpus import digest
from .presentation_checks import check_presentation
from .realworld import load_realworld
from .realworld_eval import _fresh_runtime, protocol_sha256
from .teacher import local_endpoint
from .workflows import check_workflow_step, restore_reused_outcome


def final_cases(manifest):
    """Keep every reserved case, and reject inconsistent source boundaries."""
    cases = [case for case in manifest["cases"] if case["split"] == "holdout"]
    if not cases:
        raise ValueError("No reserved holdout cases")
    records = {record["id"]: record for record in manifest["graphs"]}
    for case in cases:
        record = records[case["graph_id"]]
        if (
            manifest["sources"][case["source_id"]]["split"] != "holdout"
            or record["source_id"] != case["source_id"]
            or record["split"] != "holdout"
        ):
            raise ValueError("Holdout case crosses a source boundary")
    return cases


async def evaluate_holdout(
    settings, *, corpus: Path, output: Path, data_dir: Path, repeats=1
):
    if not 1 <= repeats <= 3:
        raise ValueError("Choose one to three complete final trials")
    _fresh_runtime(settings, output, data_dir)
    local_endpoint(settings.llm_base_url)
    if not settings.llm_enabled:
        raise ValueError("Final evaluation requires the local model")
    manifest, graphs = load_realworld(corpus)
    cases = final_cases(manifest)
    records = {record["id"]: record for record in manifest["graphs"]}
    report = {
        "schema_version": "1.0.0",
        "mode": "routing-adapter-final-source-holdout-v1",
        "started_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "source_sha256": HistoryStore.digest(Path(__file__)),
        "result_protocol_sha256": protocol_sha256(),
        "cases_sha256": digest(cases),
        "cases": cases,
        "repeats": repeats,
        "trials": [],
        "holdout_question_turns_attempted": 0,
        "holdout_consumed_at": None,
        "oracle_feedback_sent": False,
        "training_export_allowed": False,
        "scope": "Final evaluation on all reserved source cases using original contract questions. Source separation, not unseen task types or independently authored language. Read the enclosing adapter protocol for routing and other-stage models. This source cannot remain an untouched benchmark for any later candidate tuned using these results.",
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
    async with agent_client(
        replace(settings, history_directory=None), data_dir=data_dir
    ) as (client, history):
        for repetition in range(1, repeats + 1):
            for case in cases:
                terminal = Terminal(
                    client,
                    history_root=history,
                    output=lambda _: None,
                    timeout_seconds=120,
                )
                await terminal.start(
                    domain_id=case["domain"],
                    title=f"Final holdout: {case['id']} / trial {repetition}",
                )
                source = corpus / records[case["graph_id"]]["path"]
                await terminal.load(source)
                trial = {
                    "case_id": case["id"],
                    "source_id": case["source_id"],
                    "repetition": repetition,
                    "session_id": terminal.session_id,
                    "history_path": str(history / terminal.session_id),
                    "expected_steps": len(case["steps"]),
                    "steps": [],
                }
                report["trials"].append(trial)
                for index, task in enumerate(case["steps"], 1):
                    report["holdout_consumed_at"] = (
                        report["holdout_consumed_at"] or utc_now().isoformat()
                    )
                    report["holdout_question_turns_attempted"] += 1
                    save()
                    started = time.monotonic()
                    outcome = {}
                    try:
                        async with asyncio.timeout(180):
                            outcome = await terminal.ask(task["query"])
                        outcome = restore_reused_outcome(
                            outcome,
                            history=history,
                            session_id=terminal.session_id,
                            source_graph=source,
                        )
                        issues = check_workflow_step(
                            graphs[case["graph_id"]], task, outcome
                        ) + check_presentation(graphs[case["graph_id"]], task, outcome)
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
                            "query": task["query"],
                            "turn_id": terminal.turn_id,
                            "passed": not issues,
                            "issues": issues,
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
