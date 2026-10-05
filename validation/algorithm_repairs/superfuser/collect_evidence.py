#!/usr/bin/env python3
"""Archive final evidence and verify source/binary identity across copies."""
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = Path('problems/28_influence_maximization/papers/2021_superfuser/code')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    work, tests, evidence = HERE / '_work', HERE / '_work/final-tests', HERE / 'evidence'
    evidence.mkdir(exist_ok=True)
    suites, manifest = read(tests / 'summary.json'), read(HERE / 'manifest.json')
    assert set(suites) == {'numerical', 'core', 'repeat', 'memcheck', 'initcheck',
                           'racecheck', 'synccheck', 'asan', 'asan-core', 'cli', 'asan-cli'}
    artifacts = {}

    def archive(path, name):
        dest = evidence / (name + '.gz')
        dest.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        artifacts[str(dest.relative_to(HERE))] = dict(raw_sha256=sha(path), gzip_sha256=sha(dest))

    def diagnostics(directory, name):
        bundle = ''.join(f'===== {p.name} =====\n' + p.read_text()
                         for p in sorted(directory.glob('*.log')))
        path = directory / 'diagnostics.txt'
        path.write_text(bundle)
        archive(path, name + '-diagnostics.txt')

    for name, summary in suites.items():
        assert summary['status'] == 'passed' and summary['failures'] == 0, name
        assert summary.get('process_exit', 0) == 0, name
        for file in ['summary.json', 'results.json', 'commands.txt', 'invocation.json', 'run.log']:
            path = tests / name / file
            if path.exists():
                archive(path, name + '-' + file)
        if name in ['cli', 'asan-cli']:
            diagnostics(tests / name, name)
    for name in ['numerical', 'core', 'repeat', 'memcheck']:
        archive(tests / name / 'corpus.json', name + '-corpus.json')
    for tool in ['memcheck', 'initcheck', 'synccheck']:
        assert 'ERROR SUMMARY: 0 errors' in (tests / tool / 'run.log').read_text(), tool
    assert 'LEAK SUMMARY: 0 bytes leaked' in (tests / 'memcheck/run.log').read_text()
    assert '(0 errors, 0 warnings)' in (tests / 'racecheck/run.log').read_text()

    # Verify determinism from the already completed runs, without another GPU run.
    normal = read(tests / 'numerical/results.json')['results']
    assert normal == read(tests / 'asan/results.json')['results']
    assert read(tests / 'core/results.json')['results'] == read(tests / 'asan-core/results.json')['results']
    repeats = read(tests / 'repeat/results.json')['results']
    canonical, repeat_checks = {}, 0
    for name, result in repeats.items():
        base = name.rsplit('-r', 1)[0]
        value = {k: v for k, v in result.items() if k != 'name'}
        if base in canonical:
            assert value == canonical[base], name
            repeat_checks += 1
        else:
            canonical[base] = value
    consistency = dict(normal_asan_cases=len(normal), normal_asan_core_cases=suites['core']['cases'],
                       repeated_stress_cases=len(canonical), repeated_equalities=repeat_checks)

    for variant in ['final-build', 'final-asan-build']:
        build = read(work / variant / 'build.json')
        assert build['manifest'] == manifest
        for name, digest in build['binaries'].items():
            assert sha(work / variant / name) == digest
        for file in ['build.json', 'superfuser-build.log', 'probe-build.log']:
            archive(work / variant / file, variant + '-' + file)
    for file in ['production-build.log', 'baseline-build.log']:
        archive(work / file, file)
    production = read(work / 'production/summary.json')
    assert production['status'] == 'passed' and production['failures'] == 0
    for file in ['summary.json', 'results.json']:
        archive(work / 'production' / file, 'production-' + file)
        archive(work / 'production/cli' / file, 'production-cli-' + file)
    diagnostics(work / 'production', 'production')
    diagnostics(work / 'production/cli', 'production-cli')
    historical = HERE.parents[1] / 'gpu_correctness_expansion/results/superfuser.json'
    archive(historical, 'historical-audit.json')
    for path in sorted(evidence.glob('baseline*')):
        if path.suffix != '.gz':
            artifacts[str(path.relative_to(HERE))] = dict(raw_sha256=sha(path))

    root = HERE.parents[3] / ARTIFACT
    mirror = HERE.parents[2] / ARTIFACT
    locations = dict(root=root, canonical=mirror, normal=work / 'final-build/source',
                     asan=work / 'final-asan-build/source')
    for label, directory in locations.items():
        for name, digest in manifest['source_sha256'].items():
            assert sha(directory / name) == digest, (label, name)
    assert sha(HERE / 'repair.patch') == manifest['patch_sha256']
    for directory in [root, mirror]:
        assert sha(directory / 'bin/superfuser') == production['binary_sha256']
    for name in ['README.md', 'REPAIR.md']:
        assert sha(root / name) == sha(mirror / name)

    totals = dict(
        numerical_checks=sum(suites[n]['checks'] for n in ['numerical', 'core', 'repeat', 'asan', 'asan-core'])
                         + sum(suites[n]['positive_checks'] for n in ['cli', 'asan-cli']) + production['checks'],
        cuda_sanitizer_checks=sum(suites[n]['checks'] for n in ['memcheck', 'initcheck', 'racecheck', 'synccheck']),
        rejection_checks=sum(suites[n]['rejections'] for n in ['cli', 'asan-cli']) + production['rejections'],
        prefix_spread_checks=sum(suites[n]['prefix_checks'] for n in ['numerical', 'repeat', 'asan', 'cli', 'asan-cli'])
                             + production['prefix_checks'],
        core_state_checks=sum(suites[n]['core_state_checks'] for n in ['core', 'asan-core']),
        cuda_sanitizer_state_checks=sum(suites[n]['core_state_checks'] for n in ['memcheck', 'initcheck', 'racecheck', 'synccheck']))
    report = dict(status='passed', totals=totals, suites=suites, production=production,
                  consistency=consistency, gpu='physical GPU 1, NVIDIA RTX 6000 Ada Generation (SM 89)')
    (HERE / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    provenance = dict(manifest=manifest, historical_baseline_sha256=sha(work / 'baseline-historical'),
                      fresh_baseline_sha256=sha(work / 'baseline-fresh'),
                      normal_build=read(work / 'final-build/build.json'),
                      asan_build=read(work / 'final-asan-build/build.json'), production=production,
                      verified_source_locations={k: str(v) for k, v in locations.items()},
                      harness_sha256={p.name: sha(p) for p in sorted(HERE.glob('*.py'))},
                      probe_sha256=sha(HERE / 'probe.cu'), evidence=artifacts)
    (HERE / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps(dict(totals=totals, consistency=consistency)))


if __name__ == '__main__':
    main()
