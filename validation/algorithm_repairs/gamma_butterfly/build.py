#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--upstream',type=Path,default=HERE.parents[3]/'problems/23_butterfly_counting_bipartite/papers/2022_gamma_reuse/code')
    ap.add_argument('--arch',default='sm_89');ap.add_argument('--asan',action='store_true');args=ap.parse_args()
    work=args.work.resolve();source=work/'source'
    if work.exists():raise SystemExit('Use a fresh work directory')
    source.mkdir(parents=True)
    manifest=json.loads((HERE/'manifest.json').read_text());assert sha(HERE/'repair.patch')==manifest['patch_sha256']
    for name,digest in manifest['base_sha256'].items():
        if digest is None:continue
        data=subprocess.check_output(['git','show',manifest['commit']+':'+name],cwd=args.upstream)
        (source/name).write_bytes(data);assert sha(source/name)==digest
    # patch uses this working directory even when it is nested in another Git repository.
    subprocess.run(['patch','--binary','-p1','--batch','-i',str(HERE/'repair.patch')],cwd=source,check=True,stdout=subprocess.DEVNULL)
    for name,digest in manifest['source_sha256'].items():assert sha(source/name)==digest,name
    flags=['-I'+str(source),'-std=c++17','-arch='+args.arch,'-O2','-lineinfo']
    if args.asan:flags+=['-Xcompiler=-fsanitize=address','-Xcompiler=-fsanitize=undefined','-Xcompiler=-fno-omit-frame-pointer']
    commands=[];binaries={}
    for name,input_path in [('sm',source/'sm.cu'),('probe',HERE/'probe.cu')]:
        cmd=['nvcc',str(input_path),str(source/'log.cpp'),*flags,'-o',str(work/name)]
        with (work/(name+'-build.log')).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        commands.append(cmd);binaries[name]=sha(work/name)
    report=dict(manifest=manifest,commands=commands,binaries=binaries,asan=args.asan,nvcc=subprocess.check_output(['nvcc','--version'],text=True))
    (work/'build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(binaries))
if __name__=='__main__':main()
