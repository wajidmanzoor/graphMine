#!/usr/bin/env python3
"""Check the original standalone coloring modes against the same exact oracles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gpu', type=int, default=1)
    parser.add_argument('--tool', choices=['memcheck', 'racecheck', 'initcheck', 'synccheck'])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads((HERE / 'manifest.json').read_text())['cases']
    selected = [c for c in cases if c['edges'] and
                (c['group'] == 'regression' or c['group'] == 'family' and c['n'] <= 150)]
    selected += [c for c in cases if c['group'] == 'random-small'][:20]
    selected += [c for c in cases if c['group'] == 'random-medium'][:20]
    if args.tool:
        selected = [c for c in cases if c['id'] in
                    {'cycle_chords-01', 'boundary-random-33', 'low-core-optimum-17'}]
    modes = [('psanse', []), ('number', []), ('recolor', []), ('renumber', []),
             ('reduce', []), ('psanse', ['-x']), ('reduce', ['-x'])]
    results = []
    started = time.monotonic()
    for case in selected:
        graph_file = output / (case['id'] + '.bel')
        arcs = sorted(case['edges'] + [[v, u] for u, v in case['edges']])
        graph_file.write_bytes(b''.join(struct.pack('<QQQ', v + 1, u + 1, 1) for u, v in arcs))
        for color, flags in modes:
            name = case['id'] + '-' + color + ('-warp' if flags else '-block')
            command = [str(args.binary.resolve()), '-g', str(graph_file), '-m', 'mcp', '-c', color, '-d', '0', *flags]
            if args.tool:
                prefix = ['compute-sanitizer', '--tool', args.tool, '--error-exitcode', '97']
                if args.tool == 'memcheck':
                    prefix += ['--leak-check', 'full']
                command = prefix + command
            log = output / (name + '.log')
            timeout = False
            with log.open('w') as stream:
                try:
                    run = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), OMP_NUM_THREADS='4'), timeout=60)
                    code = run.returncode
                except subprocess.TimeoutExpired:
                    timeout, code = True, None
            text = log.read_text()
            matches = re.findall(r'(?:Maximum clique found in preprocessing time, size: |Found a maximum clique of size )(\d+)', text)
            observed = int(matches[-1]) if matches else None
            clean = not args.tool or ('RACECHECK SUMMARY: 0 hazards displayed' in text if args.tool == 'racecheck'
                                      else 'ERROR SUMMARY: 0 errors' in text)
            ok = code == 0 and observed == case['expected'] and clean
            results.append(dict(id=name, graph=case['id'], expected=case['expected'], observed=observed,
                                exit=code, timeout=timeout, status='pass' if ok else 'fail', command=command,
                                searched='Launching search kernel' in text,
                                log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
            if not ok:
                print(json.dumps(results[-1]), flush=True)
        print(f'{len(results)} runs; {sum(x["status"] == "fail" for x in results)} failures', flush=True)
    summary = dict(binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                   manifest_sha256=hashlib.sha256((HERE / 'manifest.json').read_bytes()).hexdigest(),
                   gpu=args.gpu, tool=args.tool, graphs=len(selected), cases=len(results),
                   passed=sum(x['status'] == 'pass' for x in results),
                   failed=sum(x['status'] == 'fail' for x in results),
                   elapsed_seconds=time.monotonic() - started, results=results)
    (output / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}), flush=True)
    raise SystemExit(bool(summary['failed']))


if __name__ == '__main__':
    main()
