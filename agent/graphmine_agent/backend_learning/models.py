"""Immutable versions of ONE shared policy; no model fitting in requests."""
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

from . import shared, evaluation
from .storage import atomic_json, utc_now

VERSION = re.compile(r'[a-z0-9][a-z0-9._-]{0,127}\Z')
_CACHE = {}


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid4().hex)
    try:
        with temporary.open('x') as handle:
            handle.write(value + '\n')
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
    fd = os.open(path / '.publication.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def pointer(root, name):
    path = root / name
    if path.is_symlink() or path.stat().st_size > 128:
        raise ValueError('Invalid shared model pointer')
    value = path.read_text().strip()
    if not VERSION.fullmatch(value):
        raise ValueError('Invalid shared model version')
    return value


def load(model_dir, implementation=None, *, version=None):
    root = Path(model_dir) / 'shared'
    version = version or pointer(root, 'current')
    if not VERSION.fullmatch(version):
        raise ValueError('Invalid shared model version')
    directory = root / version
    paths = [directory / 'model.json', directory / 'metadata.json']
    if root.is_symlink() or directory.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError('Shared model paths must not be symlinks')
    stamps = []
    for path in paths:
        stat = path.stat()
        if stat.st_size > 32 * 1024 * 1024:
            raise ValueError('Shared model exceeds size limit')
        stamps.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    key = str(directory), tuple(stamps)
    if key not in _CACHE:
        raw = paths[0].read_bytes()
        model, metadata = json.loads(raw), json.loads(paths[1].read_text())
        shared.validate(model)
        if (model['model_version'] != version or metadata['model_version'] != version
                or metadata['model_sha256'] != hashlib.sha256(raw).hexdigest()
                or metadata['implementation_sha256'] != model['implementation_sha256']):
            raise ValueError('Shared model identity or content hash changed')
        if len(_CACHE) >= 8:
            _CACHE.clear()
        _CACHE[key] = model, metadata
    model, metadata = _CACHE[key]
    if implementation is not None and model['implementation_sha256'] != implementation:
        raise ValueError('Shared model belongs to another implementation')
    return model, metadata


def admissible_rows(rows, cards, implementation, compatibility=None):
    # Timing compatibility is deliberately exact: a new implementation needs
    # new paired measurements. Historical logs remain readable for inspection.
    by_id = {c['id']: {b['id'] for b in c['backends'] if b.get('verified')} for c in cards}
    records = {r['run_id']: r for r in rows if r.get('run_id')}
    superseded = {r['supersedes'] for r in records.values() if r.get('supersedes')}
    result, skipped = [], 0
    for key, row in records.items():
        try:
            if key in superseded or row.get('is_evaluation') is not False or row.get('source') not in {'application', 'benchmark'}:
                continue
            if row.get('implementation_sha256') != implementation:
                continue
            chosen = row.get('chosen_backend') or row.get('requested_backend')
            if chosen not in by_id.get(row.get('problem'), set()):
                raise ValueError('Backend lacks current correctness evidence')
            candidate = next(c for c in row['candidates'] if c['id'] == chosen)
            if not candidate.get('compiled') or not candidate.get('admitted'):
                raise ValueError('Unadmitted observation')
            if candidate['device'] == 'gpu' and row['hardware'].get('leased_gpu_index') != 1:
                raise ValueError('Unpermitted GPU')
            shape = row['graph_features']
            if not re.fullmatch(r'[0-9a-f]{64}', shape['snapshot_fingerprint']) or any(type(shape[k]) is not int or shape[k] < 0 for k in ('n', 'm')):
                raise ValueError('Invalid graph provenance')
            if row['outcome'] not in {'completed', 'timeout', 'oom', 'unsupported_input', 'error'}:
                raise ValueError('Missing terminal outcome')
            result.append(row)
        except (KeyError, ValueError, TypeError, StopIteration):
            skipped += 1
    return result, skipped


def live_permitted(model_dir, metadata, implementation, admission_fingerprint, *, configuration=None):
    # Deleting the old selector does not invent evidence for the new model.
    report = metadata.get('comparison', {})
    return (metadata.get('implementation_sha256') == implementation
            and metadata.get('admission_fingerprint') == admission_fingerprint
            and report.get('live_ready') is True
            and report.get('shadow', {}).get('live_ready') is True
            and metadata.get('configuration') == configuration)


def train(rows, cards, *, model_dir, implementation, admission_fingerprint, options=None):
    options = options or {}
    accepted, skipped = admissible_rows(rows, cards, implementation)
    cases, excluded = shared.paired_cases(accepted, failure_penalty=options.get('failure_penalty', 10.))
    training, held = shared.split_graphs(cases, seed=options.get('seed', 1729))
    held_graphs = {c['context']['graph_features']['snapshot_fingerprint'] for c in held}
    feedback = [r for r in accepted if r['graph_features']['snapshot_fingerprint'] not in held_graphs]
    kwargs = {k: v for k, v in options.items() if k in {'seed', 'epochs', 'learning_rate', 'ipw_clip', 'failure_penalty'}}
    model = shared.train(training, cards, implementation, feedback=feedback, **kwargs)
    linear = shared.train(training, cards, implementation, feedback=feedback, architecture='shared_linear', **kwargs)
    comparison = evaluation.compare({'shared_nn': model, 'shared_linear': linear}, held, options=options)
    version = datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%S.%fz-') + model['training']['data_sha256'][:12]
    model['model_version'] = version
    model['held_out_graphs'] = sorted(held_graphs)
    comparison['shadow'] = evaluation.shadow_report(accepted, model)
    with publication_lock(model_dir):
        root = Path(model_dir) / 'shared'
        directory = root / version
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        atomic_json(directory / 'model.json', model)
        metadata = dict(schema_version=1, model_version=version, created_at=utc_now(),
            implementation_sha256=implementation, admission_fingerprint=admission_fingerprint,
            model_sha256=hashlib.sha256((directory / 'model.json').read_bytes()).hexdigest(),
            configuration={k: options.get(k, d) for k, d in {'temperature': 1., 'floor': .02, 'exploration_enabled': True, 'exploration_budget': .1}.items()},
            comparison=comparison, skipped_rows=skipped, excluded_comparisons=excluded,
            dropped_features=model['normalization']['dropped_features'])
        atomic_json(directory / 'metadata.json', metadata)
        # Publication activates a shadow candidate. Live mode still checks the
        # evidence gate (or an explicitly configured development override).
        if (root / 'current').exists():
            atomic_text(root / 'previous', pointer(root, 'current'))
        atomic_text(root / 'current', version)
    return metadata


def rollback(model_dir):
    with publication_lock(model_dir):
        root = Path(model_dir) / 'shared'
        previous = pointer(root, 'previous')
        load(model_dir, version=previous)
        current = pointer(root, 'current')
        atomic_text(root / 'current', previous)
        atomic_text(root / 'previous', current)
    return dict(model_version=previous, rollback_from=current)
