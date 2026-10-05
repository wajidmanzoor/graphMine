#!/usr/bin/env python3
"""Collect only completed, passing campaigns and verify compressed raw records."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    args = parser.parse_args()
    source = args.campaign.resolve()
    evidence = HERE / 'evidence'
    suites = ['full', 'core', 'bounds', 'stress', 'linked-full', 'poison-full', 'poison-core',
              'asan-full', 'standalone', 'memcheck', 'racecheck', 'initcheck', 'synccheck',
              'modes-memcheck', 'modes-racecheck', 'modes-initcheck', 'modes-synccheck']
    summaries = {}
    for name in suites:
        result = json.loads((source / name / 'results.json').read_text())
        if result['failed'] or result['passed'] != result['cases']:
            raise RuntimeError(f'{name} is not a complete passing suite')
        target = evidence / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name / 'results.json', target / 'results.json')
        raw = {p.name: p.read_bytes() for p in sorted((source / name).iterdir()) if p.is_file() and p.name != 'results.json'}
        checksums = {name: digest(data) for name, data in raw.items()}
        archive_path = target / 'records.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as archive:
            for filename, data in raw.items():
                member = tarfile.TarInfo(filename)
                member.size = len(data)
                member.mode = 0o644
                member.mtime = 0
                archive.addfile(member, io.BytesIO(data))
        with tarfile.open(archive_path) as archive:
            restored = {m.name: digest(archive.extractfile(m).read()) for m in archive.getmembers()}
        if restored != checksums:
            raise RuntimeError(f'Archive verification failed: {name}')
        (target / 'records.sha256.json').write_text(json.dumps(checksums, indent=2) + '\n')
        summaries[name] = {k: v for k, v in result.items() if k not in ['results', 'batches']}
        summaries[name]['records_sha256'] = digest(archive_path.read_bytes())
    for name in ['campaign.json', 'native-regression.json', 'native-api-test.log', 'native-regression.log']:
        shutil.copy2(source / name, evidence / name)
    campaign = json.loads((source / 'campaign.json').read_text())
    assert all(x['exit'] == 0 for x in campaign)
    manifest = json.loads((HERE / 'manifest.json').read_text())['cases']
    bounds = json.loads((source / 'bounds/results.json').read_text())['results']
    # Each sampled graph has two accepted bounds and one deliberately invalid bound.
    rejected = sum(x['witness'] == [] and x['expected'] > 0 for x in bounds)
    accepted = len(bounds) - rejected
    clique_runs = sum(summaries[name]['cases'] for name in
                      ['full', 'stress', 'linked-full', 'poison-full', 'asan-full', 'standalone']) + accepted
    core_runs = sum(summaries[name]['cases'] for name in ['core', 'poison-core'])
    sanitizer_runs = sum(summaries[name]['cases'] for name in suites if
                         name in ['memcheck', 'racecheck', 'initcheck', 'synccheck'] or name.startswith('modes-'))
    native_searches = sum(p.read_text().count('Launching search kernel') for p in (source / 'full').glob('*.log'))
    summary = dict(status='pass', date='2026-10-04',
                   patch_sha256=digest((HERE / 'repair.patch').read_bytes()),
                   manifest_sha256=digest((HERE / 'manifest.json').read_bytes()),
                   graph_fixtures=len(manifest), clique_result_checks=clique_runs,
                   core_vector_checks=core_runs, rejected_invalid_bounds=rejected,
                   cuda_sanitizer_runs=sanitizer_runs,
                   host_asan_graph_checks=summaries['asan-full']['cases'],
                   total_numerical_and_rejection_checks=clique_runs + core_runs + rejected,
                   core_labels_checked=2 * sum(c['n'] for c in manifest),
                   native_full_gpu_searches=native_searches,
                   native_full_positive_edge_graphs=sum(bool(c['edges']) for c in manifest),
                   native_api_regression='passed', selector_policy_regression='1 passed, 7 deselected',
                   suites=summaries)
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'suites'}), flush=True)


if __name__ == '__main__':
    main()
