"""Nightly linear fitting, measured rollout reports, and one-command rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from . import evaluation, memory, models
from .storage import atomic_json, prepare_directories, read_rows, utc_now


def actions(parser):
    commands = parser.add_subparsers(dest="backend_model_command", required=True)
    for name in ("train", "report", "rollback"):
        command = commands.add_parser(name)
        if name == "rollback":
            command.add_argument("operation")
        else:
            command.add_argument("--operation")
        command.add_argument("--data-dir", type=Path)
        command.add_argument("--model-dir", type=Path)
        command.add_argument("--seed", type=int, default=1729)
    return parser


def add_parser(commands):
    return actions(commands.add_parser("backend-model", help="fit, inspect or roll back backend runtime models"))


def comparison_report(rows, cards, model_dir, implementation, options=None, operation=None, compatibility=None):
    reports = []
    accepted, skipped = models.admissible_rows(rows, cards, implementation, compatibility)
    for card in sorted(cards, key=lambda c: c["id"]):
        if sum(b.get("verified", False) for b in card["backends"]) <= 1 or operation and card["id"] != operation:
            continue
        try:
            model, metadata = models.load(model_dir, card["id"], implementation)
            report = evaluation.compare(model, accepted, card, **(options or {}))
            report["model_version"] = metadata["model_version"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            report = dict(operation=card["id"], model_version=None, live_ready=False,
                          insufficient_evidence=True, model_error=type(error).__name__)
        reports.append(report)
    return dict(schema_version=1, created_at=utc_now(), operations=reports, skipped_rows=skipped,
                live_ready=bool(reports) and all(r["live_ready"] for r in reports))


def native_context(settings, data):
    import sys
    before = {key: os.environ.get(key) for key in ("CUDA_VISIBLE_DEVICES", "GRAPHMINE_NATIVE_LIBRARY")}
    paths = list(sys.path)
    try:
        sys.path.insert(0, str(settings.native_repository_root / "python/graphmine"))
        from ..evidence_cache import install
        from graphmine import evidence
        from graphmine.dispatch import implementation_hash

        native_root = settings.native_repository_root
        if settings.native_runtime_library:
            os.environ["GRAPHMINE_NATIVE_LIBRARY"] = str(settings.native_runtime_library)
        elif not os.environ.get("GRAPHMINE_NATIVE_LIBRARY"):
            os.environ["GRAPHMINE_NATIVE_LIBRARY"] = str(native_root / "library/build/runtime/libgraphmine_runtime.so")
        # Fitting and reporting need only CPU catalog metadata, never CUDA execution.
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        install(evidence, Path(data) / "reports/model-evidence-hashes.json")
        caps = evidence.capabilities(native_root)
        implementation = implementation_hash()
        admitted = hashlib.sha256((native_root / "catalog/native_execution_evidence.json").read_bytes()).hexdigest()
        return caps["operations"], implementation, admitted
    finally:
        sys.path[:] = paths
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_command(arguments, settings=None):
    from ..config import Settings
    root = settings.repository_root if settings else Path(__file__).resolve().parents[3]
    settings = settings or Settings.from_env(root)
    data, model = arguments.data_dir or settings.backend_data_dir, arguments.model_dir or settings.backend_model_dir
    prepare_directories(data, model, root)
    cards, implementation, admitted = native_context(settings, data)
    from .compatibility import benchmark_compatibility
    compatibility = benchmark_compatibility(settings.native_repository_root / "catalog/native_execution_evidence.json", implementation)
    if arguments.operation and arguments.operation not in {c["id"] for c in cards if sum(b.get("verified", False) for b in c["backends"]) > 1}:
        raise ValueError("The operation has no admitted backend comparison")
    options = dict(seed=arguments.seed, exploration_budget=settings.backend_exploration_budget,
                   max_explore_ratio=settings.backend_max_explore_ratio,
                   exploration_enabled=settings.backend_exploration_enabled)
    rows = list(read_rows(data))
    if arguments.backend_model_command == "rollback":
        report = models.rollback(model, arguments.operation)
    elif arguments.backend_model_command == "train":
        report = models.train(rows, cards, model_dir=model, implementation=implementation,
                              admission_fingerprint=admitted, options=options, operation=arguments.operation,
                              compatibility=compatibility)
        # OOM rows affect only memory; this rebuild uses the same authoritative
        # history and never manufactures samples to reach a fitting threshold.
        fitted, skipped = memory.rebuild(data)
        report["memory"] = dict(backends=len(fitted), skipped_rows=skipped,
            validated_profiles=sum(p["validated"] for m in fitted.values() for p in m["profiles"].values()))
    else:
        report = comparison_report(rows, cards, model, implementation, options, arguments.operation, compatibility)
    name = utc_now()[:10] + "-backend-model-" + arguments.backend_model_command + "-" + uuid4().hex[:12] + ".json"
    atomic_json(Path(data) / "reports" / name, report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


def main(argv=None):
    return run_command(actions(argparse.ArgumentParser(prog="graphmine backend-model")).parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
