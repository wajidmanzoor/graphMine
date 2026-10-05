#!/usr/bin/env python3
"""Standalone CLI checks, including empty inputs and malformed DIMACS records."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gpu',type=int,default=1)
    args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    binary=args.binary.resolve()
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=str(args.gpu),OMP_NUM_THREADS='1',
             ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:protect_shadow_gap=0',
             UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    records=[]
    cases=json.loads((HERE/'manifest.json').read_text())['cases']
    selected={'audit-9','empty-0','empty-1','empty-65','complete-33','complete-65',
              'cycle-33','bipartite-17','multipartite-4-9','star-129','planted-2049'}
    variants=[[],['--alpha=0'],['--anneal'],['--anneal','--alpha=-0.5'],
              ['--atten=3'],['--atten=3','--alpha=-0.5']]
    for c in cases:
        if c['id'] not in selected:continue
        graph=out/(c['id']+'.col')
        graph.write_text(f"c generated oracle fixture\np edge {c['n']} {len(c['edges'])}\n"+
                         ''.join(f'e {u+1} {v+1}\n' for u,v in c['edges']))
        for v,variant in enumerate(variants):
            cmd=[str(binary),'--gpu','--DIMACSascii',*variant,str(graph)]
            result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=120)
            log=result.stdout+result.stderr
            (out/f"{c['id']}-{v}.log").write_text(log)
            match=re.search(r'clique size: (\d+) nodes:\n([^\n]*)\n',log)
            size=int(match[1]) if match else -1
            witness=list(map(int,match[2].split())) if match else []
            edges=set(map(tuple,c['edges']))
            ok=(result.returncode==0 and size==c['expected'] and len(witness)==size and
                len(set(witness))==size and all(0<=x<c['n'] for x in witness) and
                all((min(u,v),max(u,v)) in edges for u,v in itertools.combinations(witness,2)) and
                'exact maximum (completed GPU search)' in log)
            records.append(dict(id=f"{c['id']}-{v}",kind='numerical',passed=ok,exit_code=result.returncode))
    malformed=['','c no newline','p edge -1 0\n','p edge 2 -1\n','p edge 2 2\n',
               'p edge 3 1\n','p edge 3 1\ne 0 1\n','p edge 3 1\ne 1 4\n',
               'p edge 3 1\ne 1 1\n','p edge 3 1\ne 1\n','p edge 3 1\ne 1 a\n',
               'p edge 3 1\ne 1 2 x\n','p edge 3 2\ne 1 2\ne 2 1\n',
               'e 1 2\np edge 2 1\n','p edge 2 1\np edge 2 1\ne 1 2\n',
               'p edge 2 0\ne 1 2\n','p wrong 2 0\n','p edge 2147483648 0\n',
               'p edge 2 0 trailing\n','p edge 2 0\nx unexpected\n']
    for i,contents in enumerate(malformed):
        f=out/f'invalid-{i}.col';f.write_text(contents)
        result=subprocess.run([str(binary),'--DIMACSascii',str(f)],env=env,capture_output=True,text=True,timeout=5)
        (out/f'invalid-{i}.log').write_text(result.stdout+result.stderr)
        records.append(dict(id=f'invalid-{i}',kind='rejection',passed=result.returncode==10,exit_code=result.returncode))
    for i,option in enumerate(['--max-res=0','--max-res=-1','--atten=0','--max-unsolved=-1',
                                '--max-res=abc','--max-unsolved=2147483648','--alpha=nan',
                                '--zero=inf','--alpha-step=-1','--alpha=oops']):
        result=subprocess.run([str(binary),option,'--DIMACSascii',str(out/'audit-9.col')],
                              env=env,capture_output=True,text=True,timeout=5)
        records.append(dict(id=f'option-{i}',kind='rejection',passed=result.returncode>0,exit_code=result.returncode))
        (out/f'option-{i}.log').write_text(result.stdout+result.stderr)
    summary=dict(numerical=sum(r['kind']=='numerical' for r in records),
                 rejections=sum(r['kind']=='rejection' for r in records),
                 passed=sum(r['passed'] for r in records),failures=[r for r in records if not r['passed']],
                 binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (out/'records.json').write_text(json.dumps(records,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    return not summary['failures']


if __name__=='__main__':raise SystemExit(0 if main() else 1)
