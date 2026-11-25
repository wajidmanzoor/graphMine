#!/usr/bin/env python3
"""Load one empty isolated database with its unchanged publisher statements."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time

import common
from cypher import check_batches, statements
from source_pages import audit


def wait_indexes(session, seconds=3600):
    deadline = time.monotonic() + seconds
    while True:
        indexes = session.run("SHOW INDEXES YIELD name, state, populationPercent, failureMessage RETURN *").data()
        if any(row["state"] == "FAILED" for row in indexes):
            raise ValueError("An index failed: " + json.dumps(indexes))
        if all(row["state"] == "ONLINE" for row in indexes):
            return indexes
        if time.monotonic() >= deadline:
            raise ValueError("Indexes did not become ONLINE within the waiting period")
        time.sleep(2)


def execute_scripts(slug, session, record):
    manifest = audit(slug)
    root = common.INSTANCE_ROOT / slug
    with (root / "load-statements.jsonl").open("a") as log:
        for item in manifest["load_order"]:
            path = common.SOURCE_ROOT / slug / item["file"]
            for number, statement in enumerate(statements(path.read_text()), 1):
                current = {"file": item["file"], "statement": number, "started_at": common.now()}
                record.update(phase="loading", current=current)
                common.status(slug, record)
                print(f"{common.now()} {slug} {item['file']} statement {number}: starting", flush=True)
                started = time.monotonic()
                rows, row_count = [], 0
                # Auto-commit is needed by CALL ... IN TRANSACTIONS in published loaders.
                result = session.run(statement)
                for row in result:
                    value = row.data()
                    check_batches(value)
                    row_count += 1
                    if len(rows) < 20:
                        rows.append(value)
                summary = result.consume()
                current.update(finished_at=common.now(), seconds=round(time.monotonic()-started, 3),
                               rows=row_count, result=rows, counters=dict(summary.counters.__dict__))
                log.write(json.dumps(current, default=str) + "\n")
                log.flush()
                os.fsync(log.fileno())
                record.setdefault("completed_statements", []).append(current)
                common.status(slug, record)
                print(f"{common.now()} {slug} {item['file']} statement {number}: completed in {current['seconds']}s", flush=True)


def load(slug):
    if not os.environ.get("TMUX"):
        raise ValueError("Run the loader inside tmux so it survives client disconnection")
    root = common.INSTANCE_ROOT / slug
    manifest = audit(slug)
    proof = common.verify_inputs(slug)
    checked = json.loads((root / "instance-check.json").read_text())
    if checked.get("nodes") != 0 or checked.get("relationships") != 0:
        raise ValueError("The empty-instance startup gate has not passed")
    with (root / "problem.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with common.driver(slug) as driver, driver.session(database="neo4j") as session:
            common.require_empty(session)
        record = {"status": "loading", "phase": "loading", "load_started_at": common.now(),
                  "script_hashes": common.load_hashes(slug), "source_page_sha256": manifest["page_sha256"],
                  "counts": {"nodes": {}, "relationships": {}, "total_nodes": 0, "total_relationships": 0}}
        started = time.monotonic()
        common.status(slug, record)
        try:
            if manifest["import_mode"] == "published_bulk":
                from ldbc_bulk import import_snapshot
                if slug != "ldbc-snb":
                    raise ValueError("The bulk adaptation applies only to LDBC")
                import_snapshot(proof, record)
            with common.driver(slug) as driver, driver.session(database="neo4j") as session:
                execute_scripts(slug, session, record)
                record["indexes"] = wait_indexes(session)
                record.update(phase="awaiting_verification", load_finished_at=common.now(),
                              load_seconds=round(time.monotonic()-started, 3), counts=common.graph_counts(session))
                common.status(slug, record)
                print(f"{slug}: load complete; verification required before publication", flush=True)
        except BaseException as error:
            record.update(status="failed", phase="load_failed", error=str(error).replace(common.password(slug), "<redacted>"))
            # APOC may leave queued worker batches alive after an outer failure.
            # Stop only this dedicated instance before recording the final state.
            try:
                stopped = subprocess.run(["systemctl", "--user", "stop", f"graphmine-neo4j-{slug}.service"],
                                         capture_output=True, text=True, timeout=330)
                record["service_stopped_after_failure"] = stopped.returncode == 0
                if stopped.returncode:
                    record["service_stop_error"] = stopped.stderr[-2000:]
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                record["service_stopped_after_failure"] = False
                record["service_stop_error"] = str(stop_error)
            common.status(slug, record)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=common.ORDER)
    args = parser.parse_args()
    load(args.dataset)


if __name__ == "__main__":
    main()
