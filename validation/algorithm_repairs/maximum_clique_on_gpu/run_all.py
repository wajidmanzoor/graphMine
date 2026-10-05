#!/usr/bin/env python3
"""Replay the native, poisoned-memory, sanitizer, and standalone campaigns."""
import argparse
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--poison-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-cli', type=Path)
    parser.add_argument('--native-test', type=Path)
    parser.add_argument('--native-probe', type=Path)
    parser.add_argument('--asan-build', type=Path)
    parser.add_argument('--gpu', type=int, default=1)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), OMP_NUM_THREADS='4')
    records = []

    def run(name, command, extra_env=None, timeout=1200):
        with (output / (name + '.log')).open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    env=env | (extra_env or {}), timeout=timeout)
        records.append(dict(name=name, command=command, exit=result.returncode))
        (output / 'campaign.json').write_text(json.dumps(records, indent=2) + '\n')
        print(name, 'exit', result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {output / (name + ".log")}')

    if args.native_cli:
        run('native-regression', [str(args.native_cli.resolve()), 'run', 'maximum-clique',
            '--graph', str(HERE / 'fixtures/cycle_chords-01.json'), '--backend', 'maximum-clique-on-gpu'])
        result = json.loads((output / 'native-regression.log').read_text())
        value = result['output']
        assert result['ok'] and value['maximum_size'] == 3 and value['optimal']
        assert len(value['cliques']) == 1 and set(value['cliques'][0]) == {
            'device-447-0', 'device-656-1', 'device-875-2'}
        (output / 'native-regression.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.native_test:
        run('native-api-test', [str(args.native_test.resolve())])
    for suite, binary in [('full', 'probe'), ('core', 'core_probe'), ('bounds', 'probe'), ('stress', 'probe')]:
        run(suite, ['python', str(HERE / 'validate.py'), '--suite', suite, '--binary', str(args.build.resolve() / binary),
            '--output', str(output / suite), '--gpu', str(args.gpu)])
    if args.native_probe:
        run('linked-full', ['python', str(HERE / 'validate.py'), '--suite', 'full',
            '--binary', str(args.native_probe.resolve()), '--output', str(output / 'linked-full'), '--gpu', str(args.gpu)])
    for tool in ['memcheck', 'racecheck', 'initcheck', 'synccheck']:
        run(tool, ['python', str(HERE / 'validate.py'), '--suite', 'sanitizer', '--tool', tool,
            '--binary', str(args.build.resolve() / 'probe'), '--output', str(output / tool), '--gpu', str(args.gpu)])
    for suite, binary in [('full', 'probe'), ('core', 'core_probe')]:
        run('poison-' + suite, ['python', str(HERE / 'validate.py'), '--suite', suite,
            '--binary', str(args.poison_build.resolve() / binary), '--output', str(output / ('poison-' + suite)),
            '--gpu', str(args.gpu)], {'MALLOC_PERTURB_': '165'})
    if args.asan_build:
        run('asan-full', ['python', str(HERE / 'validate.py'), '--suite', 'full',
            '--binary', str(args.asan_build.resolve() / 'probe'), '--output', str(output / 'asan-full'), '--gpu', str(args.gpu)],
            {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0'})
    run('standalone', ['python', str(HERE / 'standalone_suite.py'), '--binary', str(args.build.resolve() / 'parallel_mcp_on_gpus'),
        '--output', str(output / 'standalone'), '--gpu', str(args.gpu)])
    for tool in ['memcheck', 'racecheck', 'initcheck', 'synccheck']:
        run('modes-' + tool, ['python', str(HERE / 'standalone_suite.py'), '--tool', tool,
            '--binary', str(args.build.resolve() / 'parallel_mcp_on_gpus'),
            '--output', str(output / ('modes-' + tool)), '--gpu', str(args.gpu)])


if __name__ == '__main__':
    main()
