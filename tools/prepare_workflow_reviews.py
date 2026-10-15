#!/usr/bin/env python3
"""Prepare a private HTML/JSON review packet without approving or training on runs.

Both SQLite stores are opened read-only and backed up to in-memory snapshots.
Evaluation runs, incomplete results and runs without an original question are
listed separately. The existing authenticated review form remains authoritative.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def snapshot(path):
    target = sqlite3.connect(":memory:")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        source.backup(target)
    return target


def prepare(data_root, output, base_url=""):
    data_root, output = data_root.resolve(), output.resolve()
    if output.is_relative_to(data_root):
        raise ValueError("Keep review packets outside the production store")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    output.chmod(0o700)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "Pending review candidates from saved runs; not approved examples or a training dataset.",
        "training_started": False,
        "production_modified": False,
        "approved_examples": 0,
        "candidates": [],
        "excluded": [],
    }
    with (
        closing(snapshot(data_root / "agent.sqlite3")) as main,
        closing(snapshot(data_root / "analytics/workflows.sqlite3")) as workflows,
    ):
        rows = [
            json.loads(row[0])
            for row in workflows.execute(
                "SELECT document FROM workflows ORDER BY rowid"
            )
        ]
        reviewed = [
            json.loads(row[0])
            for row in workflows.execute("SELECT document FROM reviewed_examples")
        ]
        report["approved_examples"] = sum(
            row.get("status") == "approved" for row in reviewed
        )
        for record in rows:
            identifier, session = record["id"], record["session_id"]
            excluded = {"workflow_id": identifier, "reason": None}
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier) or not re.fullmatch(
                r"[a-zA-Z0-9_-]+", session
            ):
                excluded["reason"] = "invalid_saved_identifier"
            elif record.get("evaluation_id"):
                excluded["reason"] = "evaluation_case"
            elif (
                record.get("status") != "completed"
                or record.get("complete") is not True
            ):
                excluded["reason"] = "incomplete_workflow"
            events = [
                json.loads(row[0])
                for row in main.execute(
                    "SELECT payload FROM events WHERE session_id=? AND type='workflow.chat' ORDER BY sequence",
                    (session,),
                )
            ]
            question = next(
                (
                    event
                    for event in events
                    if record.get("planning_turn_id")
                    and event.get("turn_id") == record["planning_turn_id"]
                    and event.get("role") == "user"
                ),
                None,
            )
            if question and question.get("evaluation_id"):
                excluded["reason"] = "evaluation_question"
            if not excluded["reason"] and (
                not question or not question.get("message", "").strip()
            ):
                excluded["reason"] = "missing_original_question"
            if excluded["reason"]:
                report["excluded"].append(excluded)
                continue
            directory = (
                data_root
                / "analytics"
                / identifier
                / f"revision-{int(record['revision'])}"
            )
            try:
                result = json.loads((directory / "result.json").read_text())
                inputs = json.loads((directory / "inputs.json").read_text())
            except (OSError, ValueError):
                report["excluded"].append(
                    {**excluded, "reason": "missing_result_or_inputs"}
                )
                continue
            if result.get("complete") is not True:
                report["excluded"].append({**excluded, "reason": "incomplete_result"})
                continue
            validation = record["validation"]
            earlier = []
            for event in events:
                if event is question:
                    break
                if event.get("role") == "user":
                    earlier.append(event.get("message", ""))
            candidate = {
                "workflow_id": identifier,
                "session_id": session,
                "review_status": "pending",
                "training_eligible": False,
                "question": question["message"],
                "earlier_questions": earlier[-8:],
                "previous_workflow_id": question.get("previous_workflow_id"),
                "selection": question.get("selection"),
                "expected_revision": record["revision"],
                "workflow_hash": validation["workflow_hash"],
                "result_sha256": digest(result),
                "inputs_sha256": digest(inputs),
                "implementation_sha256": validation["implementation_sha256"],
                "plan": validation["plan"],
                "review_url": base_url.rstrip("/")
                + f"/#workspace/{session}/results/{identifier}",
                "checks_to_review": [
                    "The saved question and earlier context match the intended task.",
                    "The plan uses the right inputs, operations, parameters and quality.",
                    "The computed result is appropriate for the question.",
                    "This is a real example, not a development or evaluation probe.",
                ],
                "result_file": f"{identifier}.result.json",
                "inputs_file": f"{identifier}.inputs.json",
            }
            report["candidates"].append(candidate)
            for name, value in [
                (candidate["result_file"], result),
                (candidate["inputs_file"], inputs),
            ]:
                (output / name).write_text(
                    json.dumps(value, ensure_ascii=False, indent=2) + "\n"
                )
    report["completed_workflows_scanned"] = len(rows)
    report["candidate_count"] = len(report["candidates"])
    (output / "review-packet.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    cards = []
    for candidate in report["candidates"]:
        esc = html.escape
        cards.append(
            f"<article><h2>{esc(candidate['question'])}</h2><p>Pending review · Revision {candidate['expected_revision']}</p>"
            + (
                "<details><summary>Earlier questions</summary><pre>"
                + esc(
                    json.dumps(
                        candidate["earlier_questions"], ensure_ascii=False, indent=2
                    )
                )
                + "</pre></details>"
                if candidate["earlier_questions"]
                else ""
            )
            + "<h3>Plan</h3><pre>"
            + esc(json.dumps(candidate["plan"], ensure_ascii=False, indent=2))
            + "</pre>"
            + "<ul>"
            + "".join(
                "<li>" + esc(item) + "</li>" for item in candidate["checks_to_review"]
            )
            + "</ul>"
            + f'<p><a href="{esc(candidate["review_url"], quote=True)}">Open saved result in GraphMine</a> · <a href="{candidate["result_file"]}">Exact result</a> · <a href="{candidate["inputs_file"]}">Exact inputs</a></p>'
            + "<p>In GraphMine, select <strong>Review as a reusable example</strong> only after checking the question, inputs, plan and result. Sign in as the conversation owner. Approvals verify the current revision and hashes.</p></article>"
        )
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GraphMine workflow reviews</title><style>body{max-width:1000px;margin:2rem auto;padding:0 1rem;font:16px/1.6 system-ui;color:#183142;background:#f5f8fa}article{background:white;padding:1.5rem;margin:1.5rem 0;border:1px solid #cbd8e1;border-radius:10px}pre{overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}a{color:#075c96}</style><h1>Saved workflows for review</h1>'
    page += f"<p>{report['candidate_count']} pending candidates; {len(report['excluded'])} runs excluded. No approvals or training were performed.</p><p>This packet contains private source data. It is stored locally and is not part of the Git repository.</p>"
    page += (
        "".join(cards)
        + "<details><summary>Excluded runs</summary><pre>"
        + html.escape(json.dumps(report["excluded"], indent=2))
        + "</pre></details></html>"
    )
    (output / "index.html").write_text(page)
    for path in output.iterdir():
        path.chmod(0o600)
    return {
        key: report[key]
        for key in (
            "candidate_count",
            "completed_workflows_scanned",
            "approved_examples",
            "training_started",
            "production_modified",
        )
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url", default="", help="Your GraphMine HTTPS address for review links"
    )
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(prepare(args.data_root, args.output, args.base_url), indent=2))
