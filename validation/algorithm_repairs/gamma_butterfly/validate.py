#!/usr/bin/env python3
"""Exact independent butterfly and injective-matching oracles for GAMMA."""
import argparse
import itertools
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess

SQUARE=[(0,1),(1,2),(2,3),(0,3)]

def cycles(n,edges):
    adj=[set() for _ in range(n)]
    for a,b in edges: adj[a].add(b); adj[b].add(a)
    value=sum(math.comb(len(adj[a]&adj[b]),2) for a,b in itertools.combinations(range(n),2))//2
    if n<=10:
        # Enumerate the three distinct cycles on each four-vertex set.
        brute=0
        for a,b,c,d in itertools.combinations(range(n),4):
            for order in [(a,b,c,d),(a,b,d,c),(a,c,b,d)]:
                brute+=all(order[(i+1)%4] in adj[order[i]] for i in range(4))
        assert value==brute
    return value

def embeddings(g):
    n=g['n'];q=g.get('query_n',4); pattern=g.get('query_edges',SQUARE)
    labels=g.get('labels',[0]*n);qlabels=g.get('query_labels',[0]*q)
    order=g.get('ordering',[])
    if q==4 and sorted(map(sorted,pattern))==sorted(map(sorted,SQUARE)) and not any(labels) and not any(qlabels) and not order:
        return 8*cycles(n,g['edges'])
    adj=[set() for _ in range(n)]
    for a,b in g['edges']:adj[a].add(b);adj[b].add(a)
    total=0
    for vertices in itertools.permutations(range(n),q):
        if any(l!=255 and labels[v]!=l for v,l in zip(vertices,qlabels)):continue
        if any(vertices[b] not in adj[vertices[a]] for a,b in pattern):continue
        if any((len(adj[vertices[a]]),vertices[a]) >= (len(adj[vertices[b]]),vertices[b]) for a,b in order):continue
        total+=1
    return total

def corpus(full=False):
    result=[]
    def add(name,n,edges,**kwargs):
        result.append(dict(name=name,n=n,edges=sorted(set(tuple(sorted(e)) for e in edges)),**kwargs))
    for n in [0,1,2,4,7,31,32,33]:add(f'empty_{n}',n,[])
    for a,b in [(2,2),(2,31),(2,32),(2,33),(3,65),(8,9),(33,33),(2,1001)]:
        add(f'complete_{a}_{b}',a+b,[(u,a+v) for u in range(a) for v in range(b)])
    for n in [4,5,6,7,31,32,33,63,64,65,129]:
        add(f'cycle_{n}',n,[(v,(v+1)%n) for v in range(n)])
        add(f'path_{n}',n,[(v,v+1) for v in range(n-1)])
    add('two_squares',10,SQUARE+[(a+5,b+5) for a,b in SQUARE])
    rng=random.Random(20261004)
    for i in range(60 if full else 12):
        a=rng.randrange(1,13);b=rng.randrange(1,13);p=rng.choice([.05,.2,.5,.85])
        edges=[(u,a+v) for u in range(a) for v in range(b) if rng.random()<p]
        add(f'random_{i}',a+b,edges)
        perm=list(range(a+b));rng.shuffle(perm)
        add(f'permuted_{i}',a+b,[(perm[u],perm[v]) for u,v in edges])
    if full:
        for a,b in [(2,3),(2,4),(3,3)]:
            pairs=[(u,a+v) for u in range(a) for v in range(b)]
            for mask in range(1<<len(pairs)):
                add(f'bip_{a}_{b}_{mask}',a+b,[e for i,e in enumerate(pairs) if mask>>i&1])
        pairs=list(itertools.combinations(range(5),2))
        for mask in range(1<<len(pairs)):
            add(f'graph5_{mask}',5,[e for i,e in enumerate(pairs) if mask>>i&1])
    # Query reordering, labels, wildcard labels, ordering, leaves and disconnected patterns.
    for i,perm in enumerate(itertools.permutations(range(4))):
        add(f'query_permutation_{i}',6,[(a,b+3) for a in range(3) for b in range(3)],
            query_edges=[(perm[a],perm[b]) for a,b in SQUARE])
    for mask in range(16):
        add(f'labels_{mask}',6,[(a,b+3) for a in range(3) for b in range(3)],
            labels=[0,1,0,1,0,1],query_labels=[mask>>i&1 for i in range(4)])
    add('wildcard',6,[(a,b+3) for a in range(3) for b in range(3)],labels=[0,1,2,3,4,5],query_labels=[255]*4)
    add('ordering',6,[(a,b+3) for a in range(3) for b in range(3)],ordering=[(0,1),(0,2),(0,3),(1,3)])
    for q in [1,2,3,4,5,6,7]:
        add(f'query_path_{q}',8,[(v,v+1) for v in range(7)],query_n=q,query_edges=[(v,v+1) for v in range(q-1)])
    add('disconnected_query',6,[(a,b+3) for a in range(3) for b in range(3)],query_n=3,query_edges=[(0,2)])
    return result

def write_case(folder,g):
    folder.mkdir(parents=True,exist_ok=True);prefix=folder/g['name']
    n=g['n'];adj=[[] for _ in range(n)]
    for a,b in g['edges']:adj[a].append(b);adj[b].append(a)
    offsets=[0];edges=[]
    for row in adj: edges.extend(sorted(row));offsets.append(len(edges))
    prefix.with_suffix('.col').write_bytes(struct.pack('<I',n)+struct.pack('<'+'Q'*len(offsets),*offsets))
    prefix.with_suffix('.dst').write_bytes(struct.pack('<Q',len(edges))+struct.pack('<'+'I'*len(edges),*edges))
    prefix.with_suffix('.vlabel').write_bytes(struct.pack('<I',n)+bytes(g.get('labels',[0]*n)))
    q=g.get('query_n',4);padj=[[] for _ in range(q)];ordering=[[] for _ in range(q)]
    for a,b in g.get('query_edges',SQUARE):padj[a].append(b);padj[b].append(a)
    for a,b in g.get('ordering',[]):ordering[b].append(a)
    text=f'{q}\n'+' '.join(map(str,g.get('query_labels',[0]*q)))+'\n'
    text+=''.join(str(len(row))+' '+ ' '.join(map(str,row))+'\n' for row in padj+ordering)
    query=prefix.with_suffix('.query');query.write_text(text)
    return prefix,query

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--probe',type=Path,required=True);ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--full',action='store_true');ap.add_argument('--modes',default='0,1,2,3')
    ap.add_argument('--cases',default='');ap.add_argument('--poison',action='store_true')
    ap.add_argument('--tool',choices=['memcheck','initcheck','synccheck','racecheck'])
    ap.add_argument('--overflow',action='store_true');args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    graphs=corpus(args.full)
    if args.cases:
        wanted=set(args.cases.split(','));graphs=[g for g in graphs if g['name'] in wanted]
        assert {g['name'] for g in graphs}==wanted
    if args.overflow:
        graphs=[dict(name=f'overflow_K{n}_{n}',n=2*n,edges=[(a,n+b) for a in range(n) for b in range(n)],expected=8*math.comb(n,2)**2) for n in [257,364]]
    commands=[];expected=[]
    for g in graphs:
        g['expected']=g.get('expected',None) if 'expected' in g else embeddings(g)
        graph,query=write_case(work/'data',g)
        for mode in args.modes.split(','):
            idx=len(expected);commands.append(f'{idx} {graph} {query} {mode}');expected.append(dict(id=idx,name=g['name'],mode=int(mode),expected=g['expected']))
    (work/'graphs.json').write_text(json.dumps(graphs));(work/'expected.json').write_text(json.dumps(expected))
    (work/'commands.txt').write_text('\n'.join(commands)+'\n')
    cmd=[str(args.probe.resolve()),str(work/'commands.txt'),str(work/'results.txt')]
    if args.poison:cmd.append('poison')
    if args.tool:
        extra=['--leak-check','full'] if args.tool=='memcheck' else []
        cmd=['compute-sanitizer','--tool',args.tool,'--error-exitcode','91',*extra]+cmd
    with (work/'run.log').open('w') as log:
        result=subprocess.run(cmd,env={**os.environ,'CUDA_VISIBLE_DEVICES':'1'},stdout=log,stderr=subprocess.STDOUT,timeout=7200)
    if result.returncode:raise RuntimeError(f'probe exit {result.returncode}; see {work}/run.log')
    rows=[tuple(map(int,line.split())) for line in (work/'results.txt').read_text().splitlines()]
    assert len(rows)==len(expected),(len(rows),len(expected))
    failures=[]
    for row,ref in zip(rows,expected):
        if row!=(ref['id'],ref['expected']):failures.append(dict(**ref,observed=row))
    summary=dict(graphs=len(graphs),checks=len(expected),failures=len(failures),tool=args.tool,poison=args.poison,max_count=max(g['expected'] for g in graphs))
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(work/'failures.json').write_text(json.dumps(failures,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
