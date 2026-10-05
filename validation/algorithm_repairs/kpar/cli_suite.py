#!/usr/bin/env python3
"""Standalone executable checks, including malformed and stale input rejection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np
from validate import corpus, oracle

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--binary',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True); args=ap.parse_args()
    work=args.work.resolve(); data=work/'data with spaces';data.mkdir(parents=True,exist_ok=True)
    binary=args.binary.resolve(); records=[]; positives=0; rejects=0
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','OPENBLAS_NUM_THREADS':'1','ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    def run(options, bad=False):
        nonlocal rejects
        result=subprocess.run([str(binary),*options],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
        records.append(dict(args=options,returncode=result.returncode,output=result.stdout))
        assert (result.returncode!=0)==bad,(options,result.returncode,result.stdout)
        assert 'AddressSanitizer' not in result.stdout and 'runtime error:' not in result.stdout and 'LeakSanitizer' not in result.stdout,result.stdout
        if bad: rejects+=1
        return result
    selected=[g for g in corpus() if g['name'] in ['singleton','singleton_loop','isolates','cycle_16','cycle_64','star_33','chain_7','multigraph']]
    for g in selected:
        folder=data/g['name'];folder.mkdir(exist_ok=True)
        (folder/'attribute.txt').write_text(f"n={g['n']}\nm={len(g['edges'])}\n")
        (folder/'graph.txt').write_text(''.join(f'{a} {b}\n' for a,b in g['edges']))
        (folder/'queries.txt').write_text(''.join(f'{s}\n' for s in g['sources']))
        options=['--prefix',str(data),'--dataset',g['name'],'--epsilon','0.1']
        run(['indexing',*options])
        digest=hashlib.sha256((folder/'kpar_index.txt').read_bytes()).hexdigest()
        run(['indexing',*options])
        assert hashlib.sha256((folder/'kpar_index.txt').read_bytes()).hexdigest()==digest
        for high in [0,10000]:
            for k in [1,4,g['n']+2]:
                run(['query',*options,'--k',str(k),'--highrrw-size',str(high)])
                for source in g['sources']:
                    rows=[line.split() for line in (folder/'result'/f'{source}.txt').read_text().splitlines()]
                    ids=[int(v) for v,s in rows]; scores=np.array([float(s) for v,s in rows])
                    assert len(ids)==len(set(ids))==min(k,g['n'])
                    ref=oracle(g,source)
                    tol=.1*np.maximum(ref[ids],1/g['n'])+1e-10
                    if len({a for a,b in g['edges']})<g['n']:tol=np.full(len(ids),2e-10)
                    assert np.all(np.abs(scores-ref[ids])<=tol),(g['name'],source,rows,ref)
                    assert np.all(scores[:-1]>=scores[1:])
                    positives+=1
    for options in [[],['bogus'],['query','--k'],['query','--unknown','1']]:run(options,True)
    for option,values in {'--epsilon':['0','1','-1','nan','inf','0.5junk'], '--k':['0','-1','x','2147483648'],
                          '--query_size':['0','-1','x'],'--highrrw-size':['-1','x'],'--shard-size':['0','x'],
                          '--gpu_idx':['-1','999999']}.items():
        for value in values:run(['query',option,value],True)
    base=data/'cycle_16'; serial=0
    def reject_mutation(filename,content,action='query',extra=None):
        nonlocal serial
        serial+=1; name='invalid_'+str(serial);folder=data/name;shutil.copytree(base,folder)
        p=folder/filename
        if content is None:p.unlink()
        else:p.write_text(content)
        run([action,'--prefix',str(data),'--dataset',name,'--epsilon','0.1',*(extra or [])],True)
    for text in ['', 'n=0\nm=0\n','n=-1\nm=2\n','n=16\nm=-1\n','n=16\nm=16\nextra']:
        reject_mutation('attribute.txt',text,'indexing')
    reject_mutation('attribute.txt',None,'indexing')
    for text in ['', 'x y\n','0 16\n','-1 2\n', (base/'graph.txt').read_text()+'1 2\n']:
        reject_mutation('graph.txt',text,'indexing')
    reject_mutation('graph.txt',None,'indexing')
    for text in ['', '-1\n','16\n','0\n2147483648','0\nbad']:
        reject_mutation('queries.txt',text)
    reject_mutation('queries.txt',None)
    index=(base/'kpar_index.txt').read_text();lines=index.splitlines()
    for text in ['', '1\n2\n', index[:len(index)//2],index+'extra\n']:
        reject_mutation('kpar_index.txt',text)
    reject_mutation('kpar_index.txt',None)
    for row,value in [(1,'18446744073709551615'),(2,'18446744073709551615'),(3,'-1'),(4,'0'),(5,'-1'),(7,'1'),(8,'1'),(9,'-1'),(10,'16'),(11,'0')]:
        changed=lines.copy();tokens=changed[row].split();tokens[0]=value;changed[row]=' '.join(tokens)
        reject_mutation('kpar_index.txt','\n'.join(changed)+'\n')
    reject_mutation('kpar_index.txt',index,extra=['--epsilon','0.5'])
    edges=(base/'graph.txt').read_text().replace('0 1\n','0 2\n')
    reject_mutation('graph.txt',edges)
    summary=dict(positive_queries=positives,rejections=rejects,processes=len(records),deterministic_index_rebuilds=len(selected))
    (work/'results.json').write_text(json.dumps(records,indent=2)+'\n')
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':main()
