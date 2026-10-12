#!/usr/bin/env python3
"""Combine identical-binary checks, retaining every original attempt.

Only MBE-GPU allocation failures may be replaced, and its entire test set must
be repeated. Typed-ID command correction also requires complete PageRank and
flow reruns with unchanged fixtures. Numerical errors and other failures cannot
be hidden by this step.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def records(folder):
    rows = {}
    for path in sorted(folder.glob('gpu-*/results.jsonl')):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert row['id'] not in rows, f"Duplicate case {row['id']}"
            rows[row['id']] = row
    return rows


def main():
    full_dir = HERE / 'results/final'
    retry_dir = HERE / 'results/mbe-resource-rerun'
    ids_dir = HERE / 'results/vertex-id-rerun'
    full, retry = read(full_dir / 'summary.json'), read(retry_dir / 'summary.json')
    ids = read(ids_dir / 'summary.json')
    hashes = ['binary_sha256', 'generator_sha256', 'instructions_sha256', 'worker_sha256']
    for name in hashes:
        assert full[name] == retry[name], f"{name} differs between runs"
        if name != 'generator_sha256':
            assert full[name] == ids[name], f"{name} differs in typed-ID rerun"
    assert full['generator_sha256'] == hashlib.sha256(
        (HERE / 'evidence/validate-before-vertex-id-fix.py').read_bytes()).hexdigest()
    assert ids['generator_sha256'] == hashlib.sha256((HERE / 'validate.py').read_bytes()).hexdigest()
    original, repeated = records(full_dir), records(retry_dir)
    typed_ids = records(ids_dir)
    assert len(original) == full['cases']
    assert len(repeated) == retry['cases']
    original_cases = {c['id']: c for c in read(full_dir / 'cases.json')}
    assert set(original_cases) == set(original)
    retry_cases = {c['id']: c for c in read(retry_dir / 'cases.json')}
    expected = {key for key, row in original.items() if row['backend'] == 'mbe-gpu'}
    assert expected == set(repeated) == set(retry_cases), 'Incomplete MBE rerun'
    for key in expected:
        assert original_cases[key] == retry_cases[key], f"Fixture changed: {key}"
    id_cases = {c['id']: c for c in read(ids_dir / 'cases.json')}
    id_expected = {key for key, row in original.items() if row['backend'] in {'kpar', 'ecl-maxflow'}}
    assert len(typed_ids) == ids['cases']
    assert id_expected == set(typed_ids) == set(id_cases), 'Incomplete typed-ID rerun'
    for key in id_expected:
        assert original_cases[key] == id_cases[key], f"Typed-ID fixture changed: {key}"
    failures = [row for row in original.values() if not row['passed']]
    assert failures, 'No resource failures to reconcile'
    assert all(row['backend'] == 'mbe-gpu' and 'GPUassert: out of memory' in row.get('error', '')
               for row in failures), 'A non-allocation failure requires investigation'
    combined = []
    for key, row in sorted(original.items()):
        selected = typed_ids[key] if key in id_expected else repeated[key] if key in expected else row
        combined.append({**selected,
                         'evidence_run': ('vertex-id-rerun' if key in id_expected else
                                          'mbe-resource-rerun' if key in expected else 'final'),
                         'original_attempt_passed': row['passed']})
    coverage = {}
    for row in combined:
        key = row['operation'] + '/' + row['backend']
        counts = coverage.setdefault(key, {'passed': 0, 'failed': 0})
        counts['passed' if row['passed'] else 'failed'] += 1
    summary = {
        'mode': 'acceptance_with_resource_rerun',
        **{name: full[name] for name in hashes},
        'generator_sha256_by_run': {'final': full['generator_sha256'],
                                    'mbe-resource-rerun': retry['generator_sha256'],
                                    'vertex-id-rerun': ids['generator_sha256']},
        'gpus': full['gpus'],
        'seconds': full['seconds'] + retry['seconds'] + ids['seconds'],
        'time_scope': 'Sum of run durations; the runs overlapped in wall time.',
        'cases': len(combined),
        'passed': sum(row['passed'] for row in combined),
        'failed': sum(not row['passed'] for row in combined),
        'coverage': coverage,
        'full_run': {'summary': '../final/summary.json', 'failed': full['failed'],
                     'workers_per_gpu': full['workers_per_gpu']},
        'resource_rerun': {'summary': '../mbe-resource-rerun/summary.json',
                           'cases': retry['cases'], 'passed': retry['passed'],
                           'failed': retry['failed'], 'gpus': retry['gpus'],
                           'workers_per_gpu': retry['workers_per_gpu']},
        'vertex_id_rerun': {'summary': '../vertex-id-rerun/summary.json',
                            'cases': ids['cases'], 'passed': ids['passed'], 'failed': ids['failed'],
                            'reason': 'The harness now JSON-encodes vertex-ID arguments, preserving string zero versus integer zero. '
                                      'All PageRank and max-flow cases were repeated with identical fixtures and binaries. '
                                      'Dangling-seed PageRank is also checked exactly.'},
        'limitations': full['limitations'],
        'resource_note': 'MBE-GPU fixed scratch allocations exhausted GPU memory with concurrent instances. '
                         'Every MBE case was repeated at lower concurrency with identical binary, workers, '
                         'generator, instructions and fixtures. All original attempts remain in results/final.',
    }
    output = HERE / 'results/acceptance'
    output.mkdir(exist_ok=True)
    (output / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in combined))
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print({key: summary[key] for key in ['cases', 'passed', 'failed', 'resource_rerun']})


if __name__ == '__main__':
    main()
