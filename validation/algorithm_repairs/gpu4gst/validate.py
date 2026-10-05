#!/usr/bin/env python3
"""Independent exhaustive vertex-subset/MST oracle and tree-certificate checks."""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import re
import shlex
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent

def spanning_costs(n, edges):
    ordered = sorted(edges, key=lambda e:e[2])
    costs = []
    for mask in range(1, 1 << n):
        parent = list(range(n))
        def root(v):
            while parent[v] != v:
                v = parent[v]
            return v
        count, cost = mask.bit_count(), 0
        for u,v,w in ordered:
            if mask >> u & 1 and mask >> v & 1:
                a,b = root(u),root(v)
                if a != b:
                    parent[a] = b
                    count -= 1
                    cost += w
        if count == 1:
            costs.append((mask,cost))
    return costs

def exact(n, edges, groups, queries):
    costs = spanning_costs(n,edges)
    masks = [sum(1 << v for v in set(g)) for g in groups]
    return [min((cost for vertices,cost in costs if all(vertices & masks[g] for g in q)),default=None) for q in queries]

def case(name,n,edges,groups,queries,expected=None):
    return dict(name=name,n=n,edges=edges,groups=groups,queries=queries,
                expected=exact(n,edges,groups,queries) if expected is None else expected)

def padded(vertices,k):
    return list(vertices)+[vertices[0]]*(k-len(vertices))

def numerical_cases():
    rng = random.Random(20261004)
    pairs = list(itertools.combinations(range(5),2))
    groups = [[v for v in range(5) if mask >> v & 1] for mask in range(1,32)] + [[]]
    queries = [padded([(1<<v)-1 for v in vs],5) for size in range(1,6) for vs in itertools.combinations(range(5),size)]
    queries += [[rng.randrange(31) for _ in range(5)] for _ in range(8)] + [[0,1,3,7,31]]
    cases = [case(f'exhaustive5-{mask:04d}',5,[(u,v,1) for i,(u,v) in enumerate(pairs) if mask>>i&1],groups,queries) for mask in range(1<<len(pairs))]
    for i in range(120):
        n = rng.randrange(2,10)
        scale = [1,1,7,(1<<31)+1,(1<<48)+3][i%5]
        edges = [(u,v,rng.randrange(31)*scale) for u,v in itertools.combinations(range(n),2) if rng.random()<.43]
        groups = [[v for v in range(n) if mask >> v & 1] for mask in range(1,1<<n)] + [[]]
        k = rng.randrange(1,8)
        queries = [[rng.randrange(len(groups)-1) for _ in range(k)] for _ in range(15)]
        queries += [padded([(1<<v)-1 for v in rng.sample(range(n),min(k,n))],k) for _ in range(15)]
        queries += [[len(groups)-1]*k, [0]*k]
        cases.append(case(f'weighted-{i:03d}',n,edges,groups,queries))
        if i%4 == 0:
            permutation = rng.sample(range(n),n)
            cases.append(case(f'relabel-{i:03d}',n,[(permutation[u],permutation[v],w) for u,v,w in edges],
                [[permutation[v] for v in group] for group in groups],queries,cases[-1]['expected']))
    return cases

def stress_cases():
    cases = [case('empty',0,[],[[]],[[0]]),case('single-isolated',1,[],[[0],[]],[[0],[1],[0]]),
        case('overlapping-isolated',5,[],[[0,2],[0,3],[0,4],[]],[[0,1,2],[0,1,3],[0,0,0]]),
        case('groups16',1,[],[[0]],[[0]*16])]
    for n,scale in [(8,1),(64,1),(513,0),(2049,1),(9,(1<<52)+1)]:
        edges = [(v,v+1,scale) for v in range(n-1)]
        groups = [[v] for v in [0,n-1,n//2,1]]
        queries = [[0,1,2,3],[0,0,0,0],[1,2,2,2],[3,2,1,0]]
        expected = [(max(groups[g][0] for g in q)-min(groups[g][0] for g in q))*scale for q in queries]
        cases.append(case(f'path-{n}-{scale}',n,edges,groups,queries,expected))
    for degree in [31,32,511,512,1024,1025,2049]:
        n = degree+1
        edges = [(0,v,1+v%13) for v in range(1,n)]
        groups = [[v] for v in [0,1,n//2,n-1]]
        queries = [[1,2,3,1],[0,1,2,3],[3,3,3,3],[1,0,0,0]]
        expected=[]
        for q in queries:
            terminals=set(groups[g][0] for g in q)
            expected.append(sum(1+v%13 for v in terminals if v) if len(terminals)>1 else 0)
        cases.append(case(f'star-degree-{degree}',n,edges,groups,queries,expected))
        permutation=list(reversed(range(n)))
        cases.append(case(f'star-last-hub-{degree}',n,[(permutation[u],permutation[v],w) for u,v,w in edges],
            [[permutation[v] for v in group] for group in groups],queries,expected))
    # Two split hubs plus a nonterminal last row; dangling leaves cannot improve
    # any tree connecting terminals in the independently enumerated small core.
    core=[(0,1,9),(1,2,2),(2,3,8),(3,4,3),(0,4,20),(0,2,5),(1,4,4)]
    edges=core+[(0,v,7) for v in range(5,1105)]+[(4,v,11) for v in range(1105,2205)]
    groups=[[v] for v in range(5)]; queries=[padded(list(vs),5) for size in range(1,6) for vs in itertools.combinations(range(5),size)]
    cases.append(case('two-split-hubs',2205,edges,groups,queries,exact(5,core,groups,queries)))
    rng=random.Random(4662)
    for n in [33,65,129,513]:
        groups=[[v] for v in [0,1,n//2,n-2,n-1]]
        queries=[[0,1,2,3,4],[1,2,3,4,4],[1,1,1,1,1]]
        for weighted in [False,True]:
            edges=[(u,v,(1+v%7 if u==0 else 1000+rng.randrange(10000)) if weighted else 1)
                   for u,v in itertools.combinations(range(n),2)]
            expected=[]
            for q in queries:
                terminals=set(groups[g][0] for g in q)
                expected.append((sum(1+v%7 for v in terminals if v) if weighted else len(terminals)-1) if len(terminals)>1 else 0)
            cases.append(case(f'dense-{n}-{int(weighted)}',n,edges,groups,queries,expected))
    # Parallel weighted edges, loops, unsorted rows, and zero-cost cycles.
    cases.append(case('parallel-loops',5,[(0,1,8),(0,1,0),(0,1,0),(1,2,0),(2,0,0),(2,3,7),(3,4,0),(4,4,9)],
                      [[0],[1],[2],[3],[4]],[[0,1,2,3,4],[4,4,4,4,4]]))
    return cases

def write_case(folder,c):
    folder.mkdir(parents=True,exist_ok=True)
    adjacency=[[] for _ in range(c['n'])]
    for u,v,w in c['edges']:
        adjacency[u].append((v,w))
        if u!=v: adjacency[v].append((u,w))
    offsets=[0];dest=[];weights=[]
    for row in adjacency:
        # Deliberately reverse input order; the production loader normalizes it.
        row.reverse(); offsets.append(offsets[-1]+len(row))
        dest.extend(v for v,w in row); weights.extend(w for v,w in row)
    for suffix,values in [('beg_pos',offsets),('csr',dest),('weight',weights)]:
        (folder/f'graph_{suffix}.bin').write_bytes(struct.pack('<'+'q'*len(values),*values))
    (folder/'graph.g').write_text(''.join(f'g{i+1}: '+ ' '.join(map(str,g))+'\n' for i,g in enumerate(c['groups'])))
    k=len(c['queries'][0])
    (folder/f'graph{k}.csv').write_text(''.join(' '.join(map(str,q))+'\n' for q in c['queries']))

def check_witness(c,q,expected,witness):
    assert witness['query']==q and witness['cost']==expected
    vertices=witness['vertices']; edges=witness['edges']
    assert vertices and len(set(vertices))==len(vertices)
    assert all(0<=v<c['n'] for v in vertices)
    present=set(vertices);original={(min(u,v),max(u,v),w) for u,v,w in c['edges']}
    parent={v:v for v in vertices}
    def root(v):
        while parent[v]!=v: v=parent[v]
        return v
    assert len(edges)==len(vertices)-1
    for u,v,w in edges:
        assert u in present and v in present and (min(u,v),max(u,v),w) in original
        a,b=root(u),root(v); assert a!=b; parent[a]=b
    assert len({root(v) for v in vertices})==1
    assert sum(w for u,v,w in edges)==expected
    assert all(present.intersection(c['groups'][g]) for g in c['queries'][q])

def select_cases(suite):
    if suite=='numerical':return numerical_cases()+stress_cases()
    if suite=='stress':return stress_cases()
    if suite=='sanitizer':
        allcases=numerical_cases();stress=stress_cases()
        selected=[allcases[i] for i in [0,1,31,341,683,1023,1025,1031,1041]]
        selected += [c for c in stress if c['name'] in ['single-isolated','overlapping-isolated','path-64-1','star-degree-32','star-degree-1025','star-last-hub-1025','two-split-hubs','dense-65-1','parallel-loops']]
        # Repeated queries in one allocation verify state is reset after infeasibility.
        return [{**c,'queries':c['queries'][:4]*2,'expected':c['expected'][:4]*2} for c in selected]
    raise ValueError(suite)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--suite',choices=['numerical','stress','sanitizer'],default='numerical');ap.add_argument('--tool',choices=['memcheck','initcheck','racecheck','synccheck']);ap.add_argument('--corpus',type=Path);ap.add_argument('--gpu',default='1');ap.add_argument('--repeat',type=int,default=1)
    args=ap.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    cases=json.loads(args.corpus.read_text()) if args.corpus else select_cases(args.suite)
    cases=[{**c,'name':c['name']+f'-repeat-{r}'} for r in range(args.repeat) for c in cases]
    (work/'corpus.json').write_text(json.dumps(cases))
    lines=[]
    for c in cases:
        folder=work/'inputs'/c['name'];write_case(folder,c)
        lines.append(c['name']+' '+json.dumps(str(folder))+' '+str(len(c['queries'][0]))+' '+str(len(c['queries'])))
    commands='\n'.join(lines)+'\n';(work/'commands.txt').write_text(commands)
    cmd=[str(args.binary.resolve())]
    if args.tool:
        cmd=['compute-sanitizer','--tool',args.tool,'--error-exitcode','97',*(['--leak-check','full'] if args.tool=='memcheck' else []),*cmd]
    (work/'invocation.json').write_text(json.dumps(cmd))
    env={**os.environ,'CUDA_VISIBLE_DEVICES':args.gpu,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    start=time.monotonic()
    with (work/'run.log').open('w') as log:
        proc=subprocess.run(cmd,input=commands,text=True,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=2400)
    text=(work/'run.log').read_text();chunks={}
    for match in re.finditer(r'^BEGIN ([^\n]+)\n(.*?)^END \1 (\d+)\n',text,re.M|re.S):chunks[match[1]]=(match[2],int(match[3]))
    results=[];failures=[];witnesses=0;checks=0
    for c in cases:
        try:
            body,code=chunks[c['name']];assert code==0
            answers=[None if s=='infeasible' else int(s) for s in re.findall(r'^min cost (\S+)$',body,re.M)]
            assert answers==c['expected'],(answers,c['expected'])
            trees={w['query']:w for w in [json.loads(line[8:]) for line in body.splitlines() if line.startswith('witness ')]}
            for q,expected in enumerate(c['expected']):
                if expected is not None:check_witness(c,q,expected,trees[q]);witnesses+=1
            checks+=len(answers)
            results.append(dict(name=c['name'],answers=answers,witnesses=len(trees)))
        except (AssertionError,KeyError,ValueError) as e:failures.append(dict(name=c['name'],error=str(e)))
    if proc.returncode:failures.append(dict(process_exit=proc.returncode))
    if args.tool and args.tool!='racecheck' and 'ERROR SUMMARY: 0 errors' not in text:failures.append(dict(sanitizer='missing clean summary'))
    if args.tool=='racecheck' and '(0 errors, 0 warnings)' not in text:failures.append(dict(sanitizer='racecheck not clean'))
    if args.tool=='memcheck' and 'LEAK SUMMARY: 0 bytes leaked' not in text:failures.append(dict(sanitizer='leak summary not clean'))
    summary=dict(status='passed' if not failures else 'failed',cases=len(cases),checks=checks,witnesses=witnesses,failures=len(failures),seconds=round(time.monotonic()-start,3),process_exit=proc.returncode)
    (work/'results.json').write_text(json.dumps(dict(results=results,failures=failures),indent=2));(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary));print(json.dumps(failures[:3]))
    raise SystemExit(bool(failures))
if __name__=='__main__':main()
