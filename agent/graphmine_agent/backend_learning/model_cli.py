"""Offline shared policy training, comparison reports and version rollback."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from . import shared, evaluation, models
from .storage import atomic_json, prepare_directories, read_rows, utc_now


def actions(parser):
    commands = parser.add_subparsers(dest="backend_model_command", required=True)
    for name in ("train", "report", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path)
        command.add_argument("--model-dir", type=Path)
        command.add_argument("--seed", type=int, default=1729)
        command.add_argument("--epochs", type=int, default=400)
    return parser


def add_parser(commands):
    return actions(commands.add_parser("backend-model", help="train or inspect the one shared backend policy"))


def comparison_report(rows, cards, model_dir, implementation, options=None):
    accepted, skipped = models.admissible_rows(rows, cards, implementation)
    try:
        model, metadata = models.load(model_dir, implementation)
        cases, excluded = shared.paired_cases(accepted, failure_penalty=model['training']['failure_penalty'])
        held = [c for c in cases if c['context']['graph_features']['snapshot_fingerprint'] in model['held_out_graphs']]
        report = evaluation.compare({'shared_nn': model}, held, options=options)
        report.update(model_version=model['model_version'], shadow=evaluation.shadow_report(accepted, model),
                      skipped_rows=skipped, excluded_comparisons=excluded)
        return report
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(live_ready=False, recommendation='keep_native', model_error=type(error).__name__, skipped_rows=skipped)


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
        return caps["problems"], implementation, admitted
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
    data = arguments.data_dir or settings.backend_data_dir
    model_dir = arguments.model_dir or settings.backend_model_dir
    prepare_directories(data, model_dir, root)
    cards, implementation, admitted = native_context(settings, data)
    options = dict(seed=arguments.seed, epochs=arguments.epochs,
        exploration_budget=settings.backend_exploration_budget,
        temperature=settings.backend_temperature, floor=settings.backend_exploration_floor,
        exploration_enabled=settings.backend_exploration_enabled,
        ipw_clip=settings.backend_ipw_clip, failure_penalty=settings.backend_failure_penalty)
    rows = list(read_rows(data))
    if arguments.backend_model_command == 'rollback':
        report = models.rollback(model_dir)
    elif arguments.backend_model_command == 'train':
        report = models.train(rows, cards, model_dir=model_dir, implementation=implementation,
                              admission_fingerprint=admitted, options=options)
    else:
        report = comparison_report(rows, cards, model_dir, implementation, options)
    name = utc_now()[:10] + '-shared-model-' + arguments.backend_model_command + '-' + uuid4().hex[:12] + '.json'
    atomic_json(Path(data) / 'reports' / name, report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


def main(argv=None):
    return run_command(actions(argparse.ArgumentParser(prog='graphmine backend-model')).parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
