#!/usr/bin/env python3
"""Independent Markov-chain oracle against the actual kPAR CLI, batched by probe.cu."""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import numpy as np


def corpus(full=False):
    graphs = []
    def add(name, n, edges, sources=None):
        graphs.append(dict(name=name, n=n, edges=list(edges), sources=sources or list(range(min(n, 5)))))
    add('singleton', 1, [])
    add('singleton_loop', 1, [(0, 0)])
    add('isolates', 8, [])
    for n in [2, 3, 7, 16, 31, 32, 33, 64, 129, 511, 512, 513]:
        add(f'cycle_{n}', n, [(v, (v + 1) % n) for v in range(n)], [0, n // 2, n - 1])
        add(f'chain_{n}', n, [(v, v + 1) for v in range(n-1)], [0, n // 2, n - 1])
        add(f'star_{n}', n, [(0, v) for v in range(1, n)] + [(v, 0) for v in range(1, n)], [0, n-1])
    add('disconnected', 10, [(v, (v+1) % 4) for v in range(4)] + [(4, 5), (5, 6), (6, 4)])
    add('multigraph', 5, [(0, 0), (0, 1), (0, 1), (1, 2), (2, 0), (2, 3), (3, 3)])
    if full:
        pairs = [(a, b) for a in range(3) for b in range(3) if a != b]
        for mask in range(64):
            add(f'digraph3_{mask}', 3, [p for i,p in enumerate(pairs) if mask >> i & 1])
        rng = random.Random(20261004)
        for i in range(60):
            n = rng.choice([4, 5, 8, 12, 23, 40, 63, 65])
            p = rng.choice([.04, .15, .35, .7])
            edges = [(a, b) for a in range(n) for b in range(n) if rng.random() < p]
            add(f'random_{i}', n, edges)
        # Multiple high-degree frontiers exercise both the block and warp paths.
        n = 1100
        add('biclique_550', n, [(a,b) for a in range(550) for b in range(550,n)] +
            [(a,b) for a in range(550,n) for b in range(550)], [0,549,550,1099])
    return graphs


def oracle(g, source):
    n = g['n']
    src = np.array([a for a,b in g['edges']], dtype=np.int64)
    dst = np.array([b for a,b in g['edges']], dtype=np.int64)
    degree = np.bincount(src, minlength=n)
    p = np.zeros(n); p[source] = 1
    for _ in range(300):
        next_p = np.bincount(dst, weights=.8 * p[src] / degree[src], minlength=n)
        next_p[source] += .2 + .8 * p[degree == 0].sum()
        if np.abs(next_p - p).sum() < 2e-14:
            p = next_p
            break
        p = next_p
    assert abs(p.sum() - 1) < 1e-11
    # Independently solve the linear system on small cases.
    if n <= 65:
        transition = np.zeros((n,n))
        for a,b in g['edges']: transition[b,a] += 1 / degree[a]
        transition[source,degree == 0] = 1
        rhs = np.zeros(n); rhs[source] = .2
        exact = np.linalg.solve(np.eye(n) - .8 * transition, rhs)
        assert np.max(np.abs(exact - p)) < 1e-12
    return p


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--tool', choices=['memcheck','initcheck','racecheck','synccheck'])
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--epsilons', default='0.5,0.1')
    parser.add_argument('--case-filter', default='')
    parser.add_argument('--max-sources', type=int, default=100)
    parser.add_argument('--seeds', default='20261004')
    parser.add_argument('--high-values', default='0,1,10000')
    parser.add_argument('--k-values', default='1,4,all')
    args=parser.parse_args()
    work=args.work.resolve(); work.mkdir(parents=True,exist_ok=True)
    graphs=corpus(args.full)
    if args.case_filter:
        wanted=set(args.case_filter.split(','))
        graphs=[g for g in graphs if g['name'] in wanted]
        assert {g['name'] for g in graphs}==wanted
    for g in graphs: g['sources']=g['sources'][:args.max_sources]
    (work/'graphs.json').write_text(json.dumps(graphs))
    commands=[]
    for g in graphs:
        folder=work/'data'/g['name']; folder.mkdir(parents=True,exist_ok=True)
        (folder/'attribute.txt').write_text(f"n={g['n']}\nm={len(g['edges'])}\n")
        (folder/'graph.txt').write_text(''.join(f'{a} {b}\n' for a,b in g['edges']))
        (folder/'queries.txt').write_text(''.join(f'{s}\n' for s in g['sources']))
        for eps,seed in itertools.product(args.epsilons.split(','),args.seeds.split(',')):
            common=f"--prefix {work/'data'} --dataset {g['name']} --epsilon {eps} --seed {seed}"
            commands.append(f'indexing {common}')
            for high in args.high_values.split(','):
                for k in sorted(set(g['n']+2 if k=='all' else min(int(k),g['n']) for k in args.k_values.split(','))):
                    commands.append(f'query {common} --k {k} --highrrw-size {high} --shard-size 2')
    (work/'commands.txt').write_text('\n'.join(commands)+'\n')
    if args.prepare_only: return
    cmd=[str(args.probe.resolve()),str(work/'commands.txt'),str(work/'results.txt')]
    if args.tool:
        flags=['--leak-check','full'] if args.tool=='memcheck' else []
        cmd=['compute-sanitizer','--tool',args.tool,'--error-exitcode','91',*flags]+cmd
    env={**os.environ, 'CUDA_VISIBLE_DEVICES':'1', 'OPENBLAS_NUM_THREADS':'1'}
    with (work/'run.log').open('w') as log:
        p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=7200)
    if p.returncode: raise RuntimeError(f'probe returned {p.returncode}; see {work}/run.log')
    byname={g['name']:g for g in graphs}; refs={}; failures=[]; max_error=0; count=0
    for line in (work/'results.txt').read_text().splitlines():
        case,name,source,eps,k,high,*items=line.split()
        source=int(source); eps=float(eps); k=int(k)
        pairs=[(int(s.split(':')[0]),float(s.split(':')[1])) for s in items]
        ids=[v for v,s in pairs]; values=np.array([s for v,s in pairs])
        g=byname[name]; key=(name,source)
        if key not in refs: refs[key]=oracle(g,source)
        ref=refs[key]; error=[]
        if len(ids)!=k or len(set(ids))!=k or any(v<0 or v>=g['n'] for v in ids): error.append('cardinality/ids')
        elif not np.all(np.isfinite(values)) or np.any(values < -1e-12): error.append('finite/nonnegative')
        else:
            err=float(np.max(np.abs(values-ref[ids]))); max_error=max(max_error,err)
            # Published approximate-score scale; also check probability mass for full output.
            tol=eps*np.maximum(ref[ids],1/g['n'])+1e-10
            if len({a for a,b in g['edges']}) < g['n']:
                tol=np.full(len(ids), 2e-10)  # GPU residual completion, no biased local restart.
            if np.any(np.abs(values-ref[ids])>tol): error.append('score')
            if np.any(values[:-1]<values[1:]-1e-12): error.append('order')
            missing=list(set(range(g['n']))-set(ids))
            if missing and min(ref[ids]) < (1-eps)*max(ref[missing])-1e-10: error.append('topk')
            if k==g['n'] and abs(values.sum()-1)>1e-8: error.append('mass')
        if error: failures.append(dict(case=case,name=name,source=source,epsilon=eps,k=k,high=high,errors=error,pairs=pairs[:10],reference=ref.tolist()[:10]))
        count+=1
    expected=sum(len(g['sources'])*len(args.epsilons.split(','))*len(args.seeds.split(','))*len(args.high_values.split(','))*len(set(g['n']+2 if k=='all' else min(int(k),g['n']) for k in args.k_values.split(','))) for g in graphs)
    assert count==expected,(count,expected)
    summary=dict(graphs=len(graphs),queries=count,failures=len(failures),max_abs_error=max_error,tool=args.tool)
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (work/'failures.json').write_text(json.dumps(failures,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if failures: raise SystemExit(1)

if __name__=='__main__': main()
