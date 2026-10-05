#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from validate import write_case,embeddings,SQUARE

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True);binary=args.binary.resolve()
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    records=[];positive=0;negative=0
    def run(options,bad=False,expected=None):
        nonlocal positive,negative
        result=subprocess.run([str(binary),*map(str,options)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
        records.append(dict(args=list(map(str,options)),returncode=result.returncode,output=result.stdout))
        assert (result.returncode!=0)==bad,(options,result.stdout)
        assert not any(s in result.stdout for s in ['AddressSanitizer','LeakSanitizer','runtime error:']),result.stdout
        if bad:negative+=1
        elif expected is not None:
            match=re.search(r'matching_embeddings: (\d+)',result.stdout);assert match and int(match[1])==expected,result.stdout
            if options[-1]=='debug':
                old=re.findall(r'valid emb number is (\d+)',result.stdout);assert old and int(old[-1])==expected
            positive+=1
    graphs=[dict(name='square',n=4,edges=SQUARE),dict(name='isolates',n=8,edges=[]),dict(name='empty',n=0,edges=[]),
            dict(name='complete',n=12,edges=[(a,b+5) for a in range(5) for b in range(7)]),
            dict(name='singleton_query',n=5,edges=[],query_n=1,query_edges=[]),
            dict(name='colored',n=4,edges=SQUARE,labels=[0,1,0,1],query_labels=[0,1,0,1])]
    for g in graphs:
        prefix,query=write_case(work/'data with spaces',g)
        for mode in range(4):
            for debug in [[],['debug']]:run([prefix,query,mode,*debug],expected=embeddings(g))
    base=work/'data with spaces/square';query=base.with_suffix('.query')
    for args_bad in [[],[base],[base,query],[base,query,'x'],[base,query,'-1'],[base,query,'4'],[base,query,'0','extra'],[base,query,'0','debug','extra']]:run(args_bad,True)
    serial=0
    def reject(suffix,content):
        nonlocal serial
        serial+=1;prefix=work/('bad_'+str(serial))
        for ext in ['.col','.dst','.vlabel','.query']:shutil.copy2(base.with_suffix(ext),prefix.with_suffix(ext))
        target=prefix.with_suffix(suffix)
        if content is None:target.unlink()
        else:target.write_bytes(bytes(content) if isinstance(content,(bytes,bytearray)) else content.encode())
        run([prefix,prefix.with_suffix('.query'),'0'],True)
    for suffix in ['.col','.dst','.vlabel','.query']:
        reject(suffix,None);reject(suffix,b'');reject(suffix,base.with_suffix(suffix).read_bytes()+b'x')
    col=bytearray(base.with_suffix('.col').read_bytes());dst=bytearray(base.with_suffix('.dst').read_bytes());labels=bytearray(base.with_suffix('.vlabel').read_bytes())
    for offset,value in [(0,0xffffffff),(4,1),(12,9),(20,1),(36,7)]:
        changed=col.copy();struct.pack_into('<I' if offset==0 else '<Q',changed,offset,value);reject('.col',changed)
    for offset,value in [(0,9999),(8,4),(8,0),(12,1),(20,3)]:
        changed=dst.copy();struct.pack_into('<Q' if offset==0 else '<I',changed,offset,value);reject('.dst',changed)
    changed=labels.copy();struct.pack_into('<I',changed,0,3);reject('.vlabel',changed)
    query_text=query.read_text()
    for text in ['0\n','8\n',query_text.replace('0 0 0 0','256 0 0 0'),query_text.replace('2 1 3','2 1 1',1),
                 query_text.replace('2 1 3','2 1 4',1),query_text.replace('2 1 3','2 1 0',1),query_text.replace('2 1 3','1 1',1),
                 query_text[:-4],query_text.replace('2 1 3','-1',1)]:reject('.query',text)
    summary=dict(positive_checks=positive,rejections=negative,processes=len(records))
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(work/'results.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(summary))
if __name__=='__main__':main()
