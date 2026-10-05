#!/usr/bin/env python3
"""Replay CDS scratch, capacity, scheduling, sanitizer and rejection checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def rejection_suite(normal, wide, output, gpu):
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / 'inputs'
    inputs.mkdir(exist_ok=True)
    malformed = {
        'missing_header': '', 'negative_size': '-1 0\n',
        'header_junk': '2 1 extra\n0 1\n1 0\n',
        'missing_row': '2 1\n0 1\n', 'unordered_rows': '2 1\n1 0\n0 1\n',
        'duplicate_neighbor': '2 1\n0 1 1\n1 0\n',
        'out_of_range': '2 1\n0 2\n1 0\n',
        'self_loop': '2 1\n0 0\n1 0\n',
        'extra_row': '2 1\n0 1\n1 0\n2\n',
        'bad_token': '2 1\n0 x\n1 0\n',
        'wrong_edge_count': '2 2\n0 1\n1 0\n',
        'asymmetric': '3 2\n0 1 2\n1 2\n2 0\n',
        'unsorted': '3 3\n0 2 1\n1 0 2\n2 0 1\n',
    }
    cases = []
    for name, data in malformed.items():
        path = inputs / f'{name}.adj'
        path.write_text(data)
        cases.append((name, normal, [str(path), '2', '64', '128', '1024', '1024', '-1']))
    fixture = HERE / 'fixtures/original_small.adj'
    for name, index, value in [('k_zero', 1, '0'), ('k_one', 1, '1'),
            ('negative_buffer', 2, '-1'), ('zero_buffer', 3, '0'),
            ('noninteger', 2, 'a'), ('integer_overflow', 2, '4294967296'),
            ('scratch_index_overflow', 2, '2147483647'), ('early_stop', 6, '10')]:
        command = [str(fixture), '3', '64', '128', '1024', '1024', '-1']
        command[index] = value
        cases.append((name, normal, command))
    cases.extend([
        ('candidate_partition_overflow', normal, [str(fixture), '3', '64', '1', '1024', '1024', '-1']),
        ('clique_partition_overflow', normal, [str(fixture), '3', '1', '128', '1024', '1024', '-1']),
        ('peeling_queue_overflow', normal, [str(HERE / 'fixtures/large_disjoint_triangles.adj'), '3', '64', '128', '1', '1024', '-1']),
        ('capacity_overflow', wide, [str(HERE / 'fixtures/large_windmill.adj'), '3', '8192', '4096', '4097', '1024', '-1']),
    ])
    records = []
    for name, binary, arguments in cases:
        command = [str(binary), *arguments]
        try:
            proc = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=120,
                env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(gpu)))
            (output / f'{name}.log').write_text(proc.stdout)
            passed = proc.returncode != 0 and 'CDS_RESULT' not in proc.stdout
            if name == 'capacity_overflow':
                passed = passed and 'exact capacity range exceeded' in proc.stdout
            elif name.endswith('partition_overflow') or name == 'peeling_queue_overflow':
                passed = passed and 'assertion' in proc.stdout.lower()
            else:
                passed = passed and 'CDS error:' in proc.stdout or (
                    passed and 'Require k >=' in proc.stdout)
            records.append(dict(name=name, command=command, returncode=proc.returncode, passed=passed))
        except subprocess.TimeoutExpired:
            records.append(dict(name=name, command=command, passed=False, error='timeout'))
    result = dict(cases=len(records), passed=sum(r['passed'] for r in records), results=records)
    (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"rejections: {result['passed']}/{result['cases']} passed", flush=True)
    if result['passed'] != result['cases']:
        raise RuntimeError('A rejection check failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--normal', type=Path, required=True)
    parser.add_argument('--poison', type=Path, required=True)
    parser.add_argument('--wide', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gpu', type=int, default=1)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--resume', action='store_true',
                        help='Reuse passing suites with matching binary and manifest hashes')
    args = parser.parse_args()
    args.normal, args.poison, args.wide = (p.resolve() for p in [args.normal, args.poison, args.wide])
    args.output = args.output.resolve()
    broad = ['--group', 'named', 'original', 'random', 'higher_k', 'regression']
    repeat = ['--case', '^original_', '^clique4_', '^random_0[0-2][0-9]_',
              '^large_disjoint_triangles_k3$', '^windmill_17_k3$']
    sanitizer = ['--case', '^original_', '^clique4_', '^empty_0_k2$', '^empty_1_k3$',
        '^complete_7_k4$', '^complete_9_k6$', '^path_17_k2$', '^cycle_33_k2$',
        '^star_33_k2$', '^windmill_17_k3$', '^random_00[0-2]_k[234]$',
        '^large_disjoint_triangles_k3$', '^large_sparse_04_k3$']
    suites = [('buffers_double', args.normal, broad + ['--buffer-factor', '2']),
              ('poison', args.poison, broad), ('wide', args.wide, broad)]
    suites += [(f'repeat_{i}', args.normal, repeat) for i in range(1, 4)]
    suites += [(tool, args.normal, sanitizer + ['--sanitizer', tool, '--timeout', '120'])
               for tool in ['memcheck', 'initcheck', 'synccheck', 'racecheck']]
    suite_records = []
    args.output.mkdir(parents=True, exist_ok=True)
    for name, binary, selection in suites:
        if args.only and name not in args.only:
            continue
        command = [sys.executable, str(HERE / 'validate.py'), '--binary', str(binary),
            '--output', str(args.output / name), '--gpu', str(args.gpu), '--stop-on-failure', *selection]
        result_path = args.output / name / 'results.json'
        if args.resume and result_path.exists():
            previous = json.loads(result_path.read_text())
            if (previous['cases'] == previous['passed'] and previous['failed'] == 0
                    and previous['binary_sha256'] == hashlib.sha256(binary.read_bytes()).hexdigest()
                    and previous['manifest_sha256'] == hashlib.sha256((HERE / 'manifest.json').read_bytes()).hexdigest()):
                suite_records.append({k:v for k,v in previous.items() if k != 'results'} | {'suite': name})
                print(f"Reusing {name}: {previous['passed']}/{previous['cases']} passed", flush=True)
                continue
        print(f'Starting {name}', flush=True)
        with (args.output / f'{name}.log').open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        summary = json.loads((args.output / name / 'results.json').read_text())
        suite_records.append({k:v for k,v in summary.items() if k != 'results'} | {'suite': name})
        print(f"{name}: {summary['passed']}/{summary['cases']} passed", flush=True)
    if not args.only or 'rejections' in args.only:
        rejection_suite(args.normal, args.wide, args.output / 'rejections', args.gpu)
    (args.output / ('suite-summary' + ('-' + '-'.join(args.only) if args.only else '') + '.json')).write_text(
        json.dumps(suite_records, indent=2) + '\n')


if __name__ == '__main__':
    main()
