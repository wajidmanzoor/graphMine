#!/usr/bin/env python3
"""Differential tests of exact size, original vertex witnesses, and completion."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import time
import networkx as nx

HERE = Path(__file__).resolve().parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def generate():
    # Reuse the fully enumerated graph atlas and independent family oracles.
    source = HERE.parent / 'maximum_clique_on_gpu/manifest.json'
    cases = json.loads(source.read_text())['cases']
    audit = dict(id='audit-9', n=9, edges=[[0,1],[0,2],[0,3],[0,8],[1,2],[1,4],
        [1,8],[2,4],[2,6],[2,7],[3,5],[4,6],[4,7],[5,7],[5,8],[6,7]],
        expected=4, oracle='exhaustive subsets and Bron-Kerbosch', group='regression')
    cases.insert(0, audit)
    for n in [1023, 1024, 1025, 2049]:
        for family, g, answer in [('cycle', nx.cycle_graph(n), 2),
                                  ('star', nx.star_graph(n-1), 2),
                                  ('planted', nx.empty_graph(n), 7)]:
            if family == 'planted': g.add_edges_from(itertools.combinations(range(n-7,n),2))
            cases.append(dict(id=f'{family}-{n}', n=n, edges=sorted(map(sorted,g.edges())),
                              expected=answer, oracle='analytic graph family', group='large'))
    rng = random.Random(20191004)
    for i, base in enumerate(rng.sample([c for c in cases if 2 <= c['n'] <= 12], 180)):
        for suffix, allowed in [('empty', []), ('all', list(range(base['n']))),
                                ('subset', rng.sample(range(base['n']), rng.randrange(base['n']+1)))]:
            g = nx.Graph(); g.add_nodes_from(allowed)
            g.add_edges_from((u,v) for u,v in base['edges'] if u in allowed and v in allowed)
            answer = max(map(len,nx.find_cliques(g)),default=0)
            # Second oracle enumerates all subsets of the allowed vertices.
            brute = max((len(s) for k in range(len(allowed)+1) for s in itertools.combinations(allowed,k)
                         if all(g.has_edge(u,v) for u,v in itertools.combinations(s,2))), default=0)
            assert answer == brute
            cases.append(dict(base, id=f'allowed-{i:03d}-{suffix}', allowed=allowed,
                              expected=answer, group='allowed', oracle='exhaustive subsets and Bron-Kerbosch'))
    (HERE/'manifest.json').write_text(json.dumps(dict(seed=20191004, source_sha256=sha(source),cases=cases),separators=(',',':'))+'\n')
    print(json.dumps(dict(cases=len(cases), max_n=max(c['n'] for c in cases))))


def run(args):
    cases = json.loads((HERE/'manifest.json').read_text())['cases']
    if args.group: cases = [c for c in cases if c['group'] in args.group]
    if args.ids: cases = [c for c in cases if c['id'] in args.ids]
    if args.native: cases = [c for c in cases if 'allowed' not in c]
    if args.limit: cases = cases[:args.limit]
    runs = [dict(c, mode=mode, run_id=f"{c['id']}-m{mode}-r{r}")
            for r in range(args.repeat) for c in cases for mode in args.modes]
    assert runs, 'no matching cases'
    out = args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    inp, observed = out/'input.txt', out/'observed.txt'
    with inp.open('w') as f:
        for c in runs:
            extra = '-1' if args.native else f"{c['mode']} {len(c['allowed']) if 'allowed' in c else -1}"
            f.write(f"{c['run_id']} {c['n']} {len(c['edges'])} {extra}\n")
            for u,v in c['edges']: f.write(f'{u} {v}\n')
            if not args.native and 'allowed' in c: f.write(' '.join(map(str,c['allowed']))+'\n')
    cmd = [str(args.binary.resolve()),str(inp),str(observed)]
    if args.sanitizer:
        cmd = ['compute-sanitizer','--tool',args.sanitizer,'--error-exitcode','86',
               '--log-file',str(out/'sanitizer.log'),*cmd]
        if args.sanitizer == 'memcheck': cmd[1:1] = ['--leak-check','full']
    env = dict(os.environ,CUDA_VISIBLE_DEVICES=str(args.gpu),OMP_NUM_THREADS='1',
               MALLOC_PERTURB_='165',ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:protect_shadow_gap=0',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    start=time.monotonic()
    with (out/'run.log').open('w') as log:
        try:
            result=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout)
            code=result.returncode
        except subprocess.TimeoutExpired: code='timeout'
    lines=observed.read_text().splitlines() if observed.exists() else []
    records=[]
    for i,c in enumerate(runs):
        f=lines[i].split() if i<len(lines) else []
        error=None; witness=[]
        if len(f)<5 or f[:2]!=[c['run_id'],'OK']: error='missing/failed result: '+' '.join(f)
        else:
            size=int(f[2]); witness=[int(v.removeprefix('vertex:')) for v in f[5:]]
            edges=set(map(tuple,c['edges']))
            if size!=c['expected']: error=f"size {size} != {c['expected']}"
            elif args.native and (int(f[3])!=1 or int(f[4])<size): error='not certified'
            elif not args.native and (float(f[3])!=size or int(f[4])!=size): error='completion size mismatch'
            elif len(witness)!=size or len(set(witness))!=size: error='witness cardinality'
            elif any(v<0 or v>=c['n'] or ('allowed' in c and v not in c['allowed']) for v in witness): error='disallowed vertex'
            elif args.native and any(not v.startswith('vertex:') for v in f[5:]): error='original string IDs were lost'
            elif any((min(u,v),max(u,v)) not in edges for u,v in itertools.combinations(witness,2)): error='not a clique'
        records.append(dict(id=c['run_id'], expected=c['expected'], error=error,witness=witness))
    errors=[r for r in records if r['error']]
    sanitizer_ok=True
    if args.sanitizer:
        log=(out/'sanitizer.log').read_text()
        sanitizer_ok=('ERROR SUMMARY: 0 errors' in log if args.sanitizer!='racecheck'
                      else 'RACECHECK SUMMARY: 0 hazards' in log)
    summary=dict(runs=len(runs),passed=len(runs)-len(errors),failures=len(errors),exit_code=code,
                 sanitizer=args.sanitizer,sanitizer_clean=sanitizer_ok,output_lines=len(lines),
                 binary_sha256=sha(args.binary),input_sha256=sha(inp),command=cmd,gpu=args.gpu,
                 elapsed_s=time.monotonic()-start)
    (out/'records.json').write_text(json.dumps(records,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    for error in errors[:10]: print(json.dumps(error),flush=True)
    return not errors and code==0 and len(lines)==len(runs) and sanitizer_ok


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--generate',action='store_true')
    p.add_argument('--binary',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--native',action='store_true')
    p.add_argument('--modes',nargs='+',type=int,default=[2])
    p.add_argument('--group',nargs='+')
    p.add_argument('--ids',nargs='+')
    p.add_argument('--limit',type=int)
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--sanitizer',choices=['memcheck','initcheck','racecheck','synccheck'])
    p.add_argument('--gpu',type=int,default=1)
    p.add_argument('--timeout',type=int,default=1800)
    args=p.parse_args()
    if args.generate: generate()
    else: raise SystemExit(0 if run(args) else 1)
