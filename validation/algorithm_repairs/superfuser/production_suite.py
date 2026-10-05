#!/usr/bin/env python3
"""Check the native executable, including all 18 historical fixtures."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from validate import closure, config, prefix_spread, write_graph

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    binary, work = args.binary.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(HERE / 'cli_suite.py'), '--binary', str(binary),
                    '--work', str(work / 'cli')], check=True)
    cli = json.loads((work / 'cli/summary.json').read_text())
    results = []
    prefixes = 0
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '1'}
    for n in [8, 64]:
        for kind in ['star', 'chain', 'two_stars']:
            if kind == 'star':
                edges = [(0, v, 1) for v in range(1, n)]
            elif kind == 'chain':
                edges = [(v, v + 1, 1) for v in range(n - 1)]
            else:
                edges = [(u, v, 1) for u in [0, n // 2]
                         for v in range(u + 1, u + n // 2)]
            k = 2 if kind == 'two_stars' else 1
            path = work / f'{kind}-{n}.txt'
            write_graph(path, config(path.stem, n, edges, k))
            expected = closure(n, [(u, v) for u, v, _ in edges])
            repeated = []
            for repeat in range(3):
                name = f'{kind}_{n}_{repeat}'
                command = [str(binary), '-g', '1', '-K', str(k), '-R', '256', str(path)]
                run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=40)
                (work / (name + '.log')).write_text(run.stdout + run.stderr)
                assert run.returncode == 0, (name, run.returncode, run.stderr)
                rows = [line.split() for line in run.stdout.splitlines()]
                assert len(rows) == k and all(len(row) == 3 for row in rows), (name, rows)
                seeds = [int(row[0]) for row in rows]
                spread = [float(row[1]) for row in rows]
                assert len(set(seeds)) == k and all(0 <= v < n for v in seeds)
                assert spread == prefix_spread([expected], seeds) and spread[-1] == n
                assert all(float(row[2]) >= 0 for row in rows)
                repeated.append((seeds, spread))
                results.append(dict(name=name, arguments=command, exit=run.returncode,
                                    seeds=seeds, spread=spread, optimum=n, passed=True))
                prefixes += k
            assert all(result == repeated[0] for result in repeated)
    summary = dict(status='passed', checks=cli['positive_checks'] + len(results),
                   prefix_checks=cli['prefix_checks'] + prefixes,
                   rejections=cli['rejections'], failures=0, original_fixture_checks=len(results),
                   binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), cli=cli)
    (work / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    (work / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
