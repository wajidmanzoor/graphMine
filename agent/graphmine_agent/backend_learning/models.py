"""Immutable model versions, verified text pointers, nonregression and rollback."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import evaluation, linear
from .memory import effective_rows
from .policy import NAME
from .storage import atomic_json, utc_now

VERSION = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_CACHE = {}
POLICY_SETTINGS = dict(exploration_budget=0.10, max_explore_ratio=1.5, exploration_enabled=True)


def policy_settings(configuration):
    return {key: configuration[key] for key in POLICY_SETTINGS}


def covered_settings(requested, approved):
    return (requested["exploration_budget"] <= approved["exploration_budget"]
            and requested["max_explore_ratio"] <= approved["max_explore_ratio"]
            and (not requested["exploration_enabled"] or approved["exploration_enabled"]))


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex)
    try:
        with temporary.open("x") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def publication_lock(model_dir):
    path = Path(model_dir)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path / ".publication.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def pointer(root, name):
    path = root / name
    if path.is_symlink() or path.stat().st_size > 128:
        raise ValueError("Invalid runtime model pointer")
    value = path.read_text().strip()
    if not VERSION.fullmatch(value):
        raise ValueError("Invalid runtime model version")
    return value


def load(model_dir, operation, implementation=None, *, version=None):
    if not NAME.fullmatch(operation):
        raise ValueError("Invalid operation model name")
    root = Path(model_dir) / operation
    version = version or pointer(root, "current")
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid runtime model version")
    directory = root / version
    paths = [directory / "model.json", directory / "metadata.json"]
    if root.is_symlink() or directory.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError("Runtime model paths must not be symlinks")
    stamps = []
    for path in paths:
        stat = path.stat()
        if stat.st_size > 16 * 1024 * 1024:
            raise ValueError("Runtime model exceeds the size limit")
        stamps.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    key = (str(directory), tuple(stamps))
    if key in _CACHE:
        model, metadata = _CACHE[key]
    else:
        raw = paths[0].read_bytes()
        model, metadata = json.loads(raw), json.loads(paths[1].read_text())
        if (model["schema_version"] != linear.MODEL_SCHEMA or model["operation"] != operation
                or metadata["operation"] != operation or model["model_version"] != version
                or metadata["model_version"] != version
                or metadata["model_sha256"] != hashlib.sha256(raw).hexdigest()
                or model["implementation_sha256"] != metadata["implementation_sha256"]):
            raise ValueError("Runtime model identity or content hash changed")
        if not linear.finite(model["noise_variance"]) or model["noise_variance"] <= 0:
            raise ValueError("Invalid runtime observation variance")
        if len(_CACHE) >= 128:
            _CACHE.clear()
        _CACHE[key] = model, metadata
    if implementation is not None and model["implementation_sha256"] != implementation:
        raise ValueError("Runtime model belongs to another native implementation")
    return model, metadata


def admissible_rows(rows, cards, implementation, compatibility=None):
    by_id = {c["id"]: {b["id"] for b in c["backends"] if b.get("verified")} for c in cards}
    result, skipped = [], 0
    for row in effective_rows(rows):
        if row.get("is_evaluation") is not False or row.get("source") not in {"application", "benchmark"}:
            continue
        original = row.get("implementation_sha256")
        if original != implementation:
            if row.get("source") != "benchmark" or original not in (compatibility or {}):
                continue
            # Derived fit context only. Immutable JSONL and its actual observed
            # implementation remain untouched; model metadata retains the proof.
            row = dict(row, implementation_sha256=implementation, observed_implementation_sha256=original)
        if row.get("operation") not in by_id:
            continue
        try:
            backend = row.get("chosen_backend") or row.get("requested_backend")
            if backend not in by_id[row["operation"]]:
                raise ValueError("Unadmitted observation")
            candidate = next(c for c in row["candidates"] if c["id"] == backend)
            if not candidate.get("compiled") or not candidate.get("admitted"):
                raise ValueError("Unadmitted observation")
            if candidate["device"] == "gpu" and row["hardware"].get("leased_gpu_index") != 1:
                raise ValueError("Unpermitted device")
            shape = row["graph_features"]
            if not re.fullmatch(r"[0-9a-f]{64}", shape["snapshot_fingerprint"]):
                raise ValueError("Missing graph provenance")
            if any(type(shape[k]) is not int or shape[k] < 0 for k in ("n", "m")):
                raise ValueError("Invalid graph size")
            if row["outcome"] not in {"completed", "timeout", "oom", "unsupported_input", "error"}:
                raise ValueError("Missing terminal outcome")
            result.append(row)
        except (ValueError, KeyError, TypeError, StopIteration):
            skipped += 1
    return sorted(result, key=lambda r: r["run_id"]), skipped


def nonregression(new, previous):
    if new["metrics"] is None or previous["metrics"] is None:
        return False
    if {s["comparison_id"] for s in new["selections"]} != {s["comparison_id"] for s in previous["selections"]}:
        return False
    return all(new["metrics"][key] <= previous["metrics"][key] + 1e-12
               for key in ("mean_regret", "worst_regret", "exploration_worst_regret"))


def refresh_release(model_dir, operations, implementation, admission_fingerprint):
    versions, ready, reasons = {}, True, {}
    configuration = None
    for operation in operations:
        try:
            model, metadata = load(model_dir, operation, implementation)
            versions[operation] = model["model_version"]
            valid = (metadata["admission_fingerprint"] == admission_fingerprint
                     and metadata["comparison"]["live_ready"] is True)
            checked_settings = policy_settings(metadata["comparison"]["configuration"])
            if configuration is None:
                configuration = checked_settings
            valid &= configuration == checked_settings
            if not valid:
                reasons[operation] = "shadow_or_held_out_gate_not_met"
            ready &= valid
        except (OSError, ValueError, KeyError, TypeError):
            ready = False
            reasons[operation] = "model_unavailable"
    release = dict(schema_version=1, created_at=utc_now(), implementation_sha256=implementation,
                   admission_fingerprint=admission_fingerprint, operations=sorted(operations),
                   versions=versions, configuration=configuration,
                   ready=bool(operations) and ready, reasons=reasons)
    atomic_json(Path(model_dir) / "release.json", release)
    return release


def live_permitted(model_dir, operation, metadata, implementation, admission_fingerprint, *, configuration=None):
    path = Path(model_dir) / "release.json"
    if path.is_symlink() or path.stat().st_size > 256 * 1024:
        return False
    release = json.loads(path.read_text())
    configuration = policy_settings(configuration if configuration is not None else POLICY_SETTINGS)
    if (not release.get("configuration")
            or not covered_settings(configuration, release["configuration"])
            or not covered_settings(configuration, policy_settings(metadata["comparison"]["configuration"]))):
        return False
    operations, versions = release.get("operations", []), release.get("versions", {})
    if (not operations or operation not in operations or set(operations) != set(versions)
            or any(not NAME.fullmatch(name) or pointer(Path(model_dir) / name, "current") != versions[name]
                   for name in operations)):
        return False
    return (release.get("schema_version") == 1 and release.get("ready") is True
            and release.get("implementation_sha256") == implementation
            and release.get("admission_fingerprint") == admission_fingerprint
            and release.get("versions", {}).get(operation) == metadata["model_version"]
            and metadata["comparison"]["live_ready"] is True)


def train(rows, cards, *, model_dir, implementation, admission_fingerprint, options=None, operation=None, compatibility=None):
    cards = [c for c in cards if sum(b.get("verified", False) for b in c["backends"]) > 1]
    if not cards:
        raise ValueError("No multi-backend operations have current correctness evidence")
    accepted, skipped = admissible_rows(rows, cards, implementation, compatibility)
    summaries = []
    options = options or {}
    with publication_lock(model_dir):
        for card in sorted(cards, key=lambda c: c["id"]):
            if operation is not None and card["id"] != operation:
                continue
            name = card["id"]
            model = linear.fit(name, accepted, [b["id"] for b in card["backends"] if b.get("verified")],
                               card["parameters"], implementation)
            comparison = evaluation.compare(model, accepted, card, **options)
            version = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S.%fz-") + model["training_data_sha256"][:12]
            model["model_version"] = version
            root = Path(model_dir) / name
            directory = root / version
            directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            atomic_json(directory / "model.json", model)
            previous, previous_comparison = None, None
            publish, reason = not (root / "current").exists(), "initial_shadow_model"
            if not publish:
                try:
                    prior, previous_metadata = load(model_dir, name)
                    previous = prior["model_version"]
                    # Compare unchanged previous weights on the same current
                    # implementation's held-out measurements. This also permits
                    # a verified runtime upgrade without accepting stale timings
                    # as observations or discarding the nonregression gate.
                    baseline = dict(prior, implementation_sha256=implementation)
                    previous_comparison = evaluation.compare(baseline, accepted, card, **options)
                    publish = nonregression(comparison, previous_comparison)
                    reason = "held_out_nonregression" if publish else "held_out_nonregression_unproven"
                except (OSError, ValueError, KeyError, TypeError):
                    reason = "previous_model_invalid"
            # The first current model is for shadow use only until every rollout
            # gate passes. Later candidates never replace it without a measured
            # held-out comparison against that exact previous version.
            selected_rows = [r for r in accepted if r["operation"] == name]
            metadata = dict(schema_version=1, operation=name, model_version=version, created_at=utc_now(),
                implementation_sha256=implementation, admission_fingerprint=admission_fingerprint,
                model_sha256=hashlib.sha256((directory / "model.json").read_bytes()).hexdigest(),
                training_data_sha256=model["training_data_sha256"], training_rows=model["training_rows"],
                benchmark_implementation_compatibility=compatibility or {},
                observed_implementations=model["observed_implementations"],
                training_data_start=min((r["created_at"] for r in selected_rows), default=None),
                training_data_end=max((r["created_at"] for r in selected_rows), default=None),
                prior=dict(intercept_variance=25, slope_variance=4, observation_variance=1),
                timeout_penalty=linear.TIMEOUT_PENALTY, evaluation_rows_used=0,
                feature_names=model["encoder"]["feature_names"], comparison=comparison,
                previous_version=previous, previous_comparison=previous_comparison,
                published=publish, publication_reason=reason)
            atomic_json(directory / "metadata.json", metadata)
            if publish:
                if previous:
                    atomic_text(root / "previous", previous)
                atomic_text(root / "current", version)
            summaries.append(dict(operation=name, model_version=version, training_rows=model["training_rows"],
                                  published=publish, publication_reason=reason, live_ready=comparison["live_ready"]))
        release = refresh_release(model_dir, [c["id"] for c in cards], implementation, admission_fingerprint)
    return dict(schema_version=1, created_at=utc_now(), models=summaries, skipped_rows=skipped, release=release)


def rollback(model_dir, operation):
    if not NAME.fullmatch(operation):
        raise ValueError("Invalid operation model name")
    with publication_lock(model_dir):
        root = Path(model_dir) / operation
        current, previous = pointer(root, "current"), pointer(root, "previous")
        model, metadata = load(model_dir, operation, version=previous)
        atomic_text(root / "previous", current)
        atomic_text(root / "current", previous)
        release_path = Path(model_dir) / "release.json"
        ready = False
        if release_path.exists():
            release = json.loads(release_path.read_text())
            ready = refresh_release(model_dir, release["operations"], release["implementation_sha256"],
                                    release["admission_fingerprint"])["ready"]
    return dict(operation=operation, current=model["model_version"], previous=current,
                operation_gate_passed=metadata["comparison"]["live_ready"], live_ready=ready)
