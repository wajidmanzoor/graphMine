"""Export and report authoritative backend JSONL rows without loading a model."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .storage import DEFAULT_DATA_DIR, DEFAULT_MODEL_DIR, prepare_directories, read_rows


def add_parser(commands):
    runs = commands.add_parser("backend-runs", help="export or summarize the native run log")
    actions = runs.add_subparsers(dest="backend_runs_command", required=True)
    for name in ("export", "report", "fit-memory"):
        command = actions.add_parser(name)
        command.add_argument("--since", help="ISO 8601 UTC date or timestamp")
        command.add_argument("--operation")
        command.add_argument("--data-dir", type=Path)
    return runs


def percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * quantile
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def report(rows):
    # Corrections are new rows; all originals remain visible in export.
    records = {row["run_id"]: row for row in rows}
    superseded = {row["supersedes"] for row in records.values() if row.get("supersedes")}
    groups = defaultdict(list)
    for run_id, row in records.items():
        if run_id not in superseded:
            groups[row["operation"], row.get("chosen_backend")].append(row)
    summaries = []
    for (operation, backend), group in sorted(groups.items(), key=lambda item: str(item[0])):
        completed = [r for r in group if r["outcome"] == "completed"]
        durations = [r["runtime_seconds"] for r in completed if r.get("runtime_seconds") is not None]
        errors = [r["prediction_error"] for r in completed if r.get("prediction_error") is not None]
        regrets = [r["regret"] for r in completed if r.get("regret") is not None]
        summaries.append(dict(operation=operation, backend=backend, run_count=len(group),
                              completed_count=len(completed),
                              evaluation_count=sum(bool(r.get("is_evaluation")) for r in group),
                              timeout_count=sum(r["outcome"] == "timeout" for r in group),
                              oom_count=sum(r["outcome"] == "oom" for r in group),
                              median_seconds=statistics.median(durations) if durations else None,
                              p90_seconds=percentile(durations, 0.9),
                              failure_rate=1 - len(completed) / len(group),
                              mean_prediction_error=statistics.mean(errors) if errors else None,
                              mean_regret=statistics.mean(regrets) if regrets else None,
                              worst_regret=max(regrets) if regrets else None))
    return dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), groups=summaries)


def run_command(arguments, settings=None):
    data = arguments.data_dir or (settings.backend_data_dir if settings else
                                 Path(os.getenv("GRAPHMINE_BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR))))
    model = settings.backend_model_dir if settings else Path(os.getenv("GRAPHMINE_BACKEND_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
    root = settings.repository_root if settings else Path(__file__).resolve().parents[3]
    prepare_directories(data, model, root)
    rows = read_rows(data, since=arguments.since, operation=arguments.operation)
    if arguments.backend_runs_command == "export":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, allow_nan=False))
        return 0
    if arguments.backend_runs_command == "fit-memory":
        from .memory import rebuild

        # Always rebuild from the complete authoritative history, so a changed
        # implementation or a correction cannot retain a stale active fit.
        if arguments.since or arguments.operation:
            raise ValueError("fit-memory requires the complete run history; omit --since and --operation")
        models, skipped = rebuild(data)
        print(json.dumps(dict(backends=len(models), skipped_rows=skipped,
            validated_profiles=sum(p["validated"] for m in models.values() for p in m["profiles"].values()),
            completed_rows=sum(p["completed_count"] for m in models.values() for p in m["profiles"].values()),
            oom_rows=sum(p["oom_count"] for m in models.values() for p in m["profiles"].values())), indent=2))
        return 0
    summary = report(rows)
    from ..config import Settings
    from .model_cli import comparison_report, native_context
    from .compatibility import benchmark_compatibility
    settings = settings or Settings.from_env(root)
    try:
        cards, implementation, _ = native_context(settings, data)
        summary["backend_selection"] = comparison_report(list(read_rows(data)), cards, model, implementation,
            dict(exploration_budget=settings.backend_exploration_budget,
                 max_explore_ratio=settings.backend_max_explore_ratio,
                 exploration_enabled=settings.backend_exploration_enabled), arguments.operation,
            benchmark_compatibility(settings.native_repository_root / "catalog/native_execution_evidence.json", implementation))
        summary["backend_selection"]["history_scope"] = "Complete authoritative history; --since filters run summaries only"
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        summary["backend_selection"] = dict(live_ready=False, insufficient_evidence=True,
                                            report_error=type(error).__name__)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    destination = Path(data) / "reports" / f"{stamp}-backend-report.json"
    try:
        handle = destination.open("x")
    except FileExistsError:
        destination = destination.with_name(f"{stamp}-{uuid4().hex[:12]}-backend-report.json")
        handle = destination.open("x")
    with handle:
        json.dump(summary, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="graphmine backend-runs")
    actions = parser.add_subparsers(dest="backend_runs_command", required=True)
    for name in ("export", "report", "fit-memory"):
        command = actions.add_parser(name)
        command.add_argument("--since")
        command.add_argument("--operation")
        command.add_argument("--data-dir", type=Path)
    return run_command(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
