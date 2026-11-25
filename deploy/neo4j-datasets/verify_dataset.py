#!/usr/bin/env python3
"""Check graph counts, indexes and representative published read-only queries."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
import subprocess
import time

from neo4j import READ_ACCESS

import common
from cypher import statements
from source_pages import audit


# The user approved representative query checks on 2026-11-15 (local time).
# Preserve published text and record every unexecuted query explicitly.
REPRESENTATIVE = {
    "yelp": ("Q01", "Q02", "Q08", "Q24"),
    "movielens-32m": ("Q01", "Q02", "Q04", "Q08"),
    "movielens-genome": ("Q01", "Q04", "Q07", "Q08"),
    "stackoverflow": ("Q01", "Q04", "Q05", "Q08"),
    "ontime": ("Q01", "Q04", "Q05", "Q08"),
    "ldbc-snb": ("Q01", "Q04", "Q07", "Q08"),
}


def selected_queries(slug, manifest, all_queries=False):
    eligible = {item["id"] for item in manifest["queries"] if item["has_cypher"] and not item["gds"]}
    selected = eligible if all_queries else set(REPRESENTATIVE[slug])
    if not selected or not selected.issubset(eligible):
        raise ValueError("Representative queries must have published non-GDS Cypher")
    return selected


def query_checks_passed(records, selected, *, all_queries=False):
    if any(item["status"] == "failed" for item in records):
        return False
    accepted = {"passed", "skipped_write"} if all_queries else {"passed"}
    return all(any(item["id"] == identifier and item["status"] in accepted for item in records)
               for identifier in selected)


def count_differences(expected, actual, explanations=(), source_text=""):
    differences = []
    for kind in ("nodes", "relationships"):
        for name in sorted(set(expected[kind]) | set(actual[kind])):
            wanted, observed = expected[kind].get(name, 0), actual[kind].get(name, 0)
            if wanted == observed:
                continue
            record = {"kind": kind, "name": name, "expected": wanted, "actual": observed}
            matches = [item for item in explanations if all(item.get(k) == v for k, v in record.items())]
            if len(matches) == 1 and matches[0].get("reason") and matches[0]["reason"] in source_text and matches[0].get("evidence"):
                record.update(explained=True, reason=matches[0]["reason"], evidence=matches[0]["evidence"])
            else:
                record["explained"] = False
            differences.append(record)
    return differences


def typed_parameters(value):
    if isinstance(value, dict):
        if set(value) == {"type", "value"} and value["type"] in {"date", "datetime"}:
            return (date if value["type"] == "date" else datetime).fromisoformat(value["value"])
        return {k: typed_parameters(v) for k, v in value.items()}
    if isinstance(value, list):
        return [typed_parameters(v) for v in value]
    return value


def run_statement(session, statement, parameters, timeout):
    # Never execute a write merely to find out whether it is a write.
    with session.begin_transaction(timeout=timeout) as transaction:
        summary = transaction.run("EXPLAIN " + statement, parameters).consume()
        if summary.query_type != "r":
            transaction.rollback()
            return {"status": "skipped_write", "query_type": summary.query_type}
        transaction.rollback()
    digest = hashlib.sha256()
    rows, sample = 0, []
    with session.begin_transaction(timeout=timeout) as transaction:
        result = transaction.run(statement, parameters)
        for row in result:
            payload = json.dumps(row.data(), sort_keys=True, default=str, ensure_ascii=False)
            digest.update(payload.encode() + b"\n")
            if rows < 2:
                sample.append(payload[:2000])
            rows += 1
        summary = result.consume()
        if summary.query_type != "r" or summary.counters.contains_updates:
            raise ValueError("A verification query attempted to change the graph")
        transaction.rollback()
    return {"status": "passed", "rows": rows, "result_sha256": digest.hexdigest(), "sample": sample}


def resource_usage(slug):
    root = common.INSTANCE_ROOT / slug
    directories = [root / name for name in ("data", "transactions", "logs", "source-cache") if (root / name).exists()]
    disk = {}
    for directory in directories:
        result = subprocess.run(["du", "-s", "-B1", str(directory)], check=True, capture_output=True, text=True)
        disk[directory.name] = int(result.stdout.split()[0])
    result = subprocess.run(["systemctl", "--user", "show", f"graphmine-neo4j-{slug}.service",
                             "-p", "MemoryCurrent", "-p", "MemoryPeak", "-p", "ActiveState", "-p", "MainPID"],
                            check=True, capture_output=True, text=True)
    service = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {"measured_at": common.now(), "disk_bytes": disk, "service": service}


def publish(slug, report, state):
    if not report.get("passed") or state.get("status") != "ready":
        raise ValueError("Only a ready dataset with passed verification may enter the registry")
    path = common.SOURCE_ROOT / "registry.json"
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registry = json.loads(path.read_text())
        entries = {item["id"]: item for item in registry["datasets"]}
        entries[slug] = common.definition(slug)
        registry["datasets"] = [entries[key] for key in common.ORDER if key in entries]
        common.write_json(path, registry)


def verify(slug, *, timeout=300, all_queries=False):
    if not os.environ.get("TMUX"):
        raise ValueError("Run verification inside tmux so long benchmark queries survive disconnection")
    root = common.INSTANCE_ROOT / slug
    source = common.SOURCE_ROOT / slug
    manifest = audit(slug)
    selected = selected_queries(slug, manifest, all_queries)
    with (root / "problem.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads((root / "status.json").read_text())
        if not state.get("load_finished_at") or state.get("phase") not in {"awaiting_verification", "verifying", "verification_failed", "ready"}:
            raise ValueError("Loading and index checks must finish before verification")
        if state["script_hashes"] != common.load_hashes(slug):
            raise ValueError("Load scripts changed after the database was loaded")
        expected = json.loads((source / "expected_counts.json").read_text())
        notes_file = source / "count_explanations.json"
        notes = json.loads(notes_file.read_text()) if notes_file.exists() else []
        params_file = source / "verification-parameters.json"
        params = json.loads(params_file.read_text()) if params_file.exists() else {"default": {}, "queries": {}}
        report = {"id": slug, "started_at": common.now(), "source_page_sha256": manifest["page_sha256"],
                  "script_hashes": state["script_hashes"], "queries": [], "parameters": params, "passed": False,
                  "query_scope": "all_non_gds_reads" if all_queries else "representative",
                  "selected_queries": sorted(selected), "query_timeout_seconds": timeout}
        state.update(status="loading", phase="verifying")
        common.status(slug, state)
        common.write_json(root / "verify_report.json", report)
        try:
            with common.driver(slug) as driver:
                with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as session:
                    if not params_file.exists() and slug in {"ontime", "ldbc-snb"}:
                        from parameter_values import values
                        params = values(slug, session)
                        common.write_json(params_file, params)
                        report["parameters"] = params
                        with (source / "SOURCE.md").open("a") as source_notes:
                            source_notes.write("\n## Verification parameters\n\nThe publisher supplies parameterized queries without concrete values. "
                                        + params["selection"] + " The exact values and selection queries are saved in "
                                        "`verification-parameters.json`; the published Cypher is unchanged.\n")
                    report["counts"] = common.graph_counts(session)
                    report["count_differences"] = count_differences(expected, report["counts"], notes, (source / "SOURCE.md").read_text())
                    report["indexes"] = session.run("SHOW INDEXES YIELD name, state, populationPercent, failureMessage RETURN *").data()
                    common.write_json(root / "verify_report.json", report)
                    for item in manifest["queries"]:
                        if item["gds"] or not item["has_cypher"]:
                            report["queries"].append({"id": item["id"], "status": "skipped_gds" if item["gds"] else "no_published_cypher"})
                            continue
                        if item["id"] not in selected:
                            report["queries"].append({"id": item["id"], "status": "not_run",
                                                      "reason": "Outside the user-approved representative query checks"})
                            continue
                        path = source / item["file"]
                        values = typed_parameters({**params.get("default", {}), **params.get("queries", {}).get(item["id"], {})})
                        for number, statement in enumerate(statements(path.read_text()), 1):
                            record = {"id": item["id"], "statement": number, "file_sha256": common.sha256(path),
                                      "started_at": common.now()}
                            started = time.monotonic()
                            print(f"{common.now()} {slug} {item['id']} statement {number}: starting", flush=True)
                            try:
                                record.update(run_statement(session, statement, values, timeout))
                            except Exception as error:
                                record.update(status="failed", error=str(error).replace(common.password(slug), "<redacted>"))
                            record.update(seconds=round(time.monotonic()-started, 3), finished_at=common.now())
                            report["queries"].append(record)
                            common.write_json(root / "verify_report.json", report)
                            print(f"{common.now()} {slug} {item['id']} statement {number}: {record['status']} ({record['seconds']}s)", flush=True)
                    after = common.graph_counts(session)
                    if after != report["counts"]:
                        raise ValueError("Graph counts changed during read-only verification")
            report["resources"] = resource_usage(slug)
            report["passed"] = (all(item["explained"] for item in report["count_differences"])
                                and all(item["state"] == "ONLINE" for item in report["indexes"])
                                and query_checks_passed(report["queries"], selected, all_queries=all_queries))
            report["finished_at"] = common.now()
            common.write_json(root / "verify_report.json", report)
            state.update(status="ready" if report["passed"] else "failed", phase="ready" if report["passed"] else "verification_failed",
                         verified_at=report["finished_at"], counts=report["counts"], resources=report["resources"],
                         query_scope=report["query_scope"], selected_queries=report["selected_queries"],
                         verify_report_sha256=common.sha256(root / "verify_report.json"))
            common.status(slug, state)
            if report["passed"]:
                publish(slug, report, state)
                print(f"{slug}: counts, indexes and {report['query_scope']} query checks passed; added to the registry", flush=True)
            else:
                raise ValueError("Verification did not pass; inspect verify_report.json before publication")
        except BaseException as error:
            state.update(status="failed", phase="verification_failed", error=str(error).replace(common.password(slug), "<redacted>"))
            common.status(slug, state)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=common.ORDER)
    parser.add_argument("--query-timeout", type=int, default=300, help="Seconds per selected query; any timeout fails verification")
    parser.add_argument("--all-queries", action="store_true", help="Opt in to every published non-GDS read query")
    args = parser.parse_args()
    if args.query_timeout < 1:
        parser.error("--query-timeout must be positive")
    verify(args.dataset, timeout=args.query_timeout, all_queries=args.all_queries)


if __name__ == "__main__":
    main()
