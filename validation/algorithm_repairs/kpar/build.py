#!/usr/bin/env python3
"""Rebuild kPAR and its CLI test driver from the hashed release plus repair.patch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--archive',type=Path,default=HERE.parents[3]/'validation/gpu_correctness_expansion/vendor/kpar/kPAR.zip')
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--arch',default='sm_89')
    ap.add_argument('--asan',action='store_true')
    args=ap.parse_args(); work=args.work.resolve()
    if work.exists(): raise SystemExit('Use a fresh build directory')
    work.mkdir(parents=True); source=work/'src'; source.mkdir()
    manifest=json.loads((HERE/'manifest.json').read_text())
    assert sha(args.archive)==manifest['archive_sha256']
    assert sha(HERE/'repair.patch')==manifest['patch_sha256']
    with zipfile.ZipFile(args.archive) as z:
        for name in manifest['source_sha256']:
            p=source/name; p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(z.read('kPAR/src/'+name).decode().replace('\r\n','\n'))
    subprocess.run(['patch','-p1','--batch','-i',str(HERE/'repair.patch')],cwd=work,check=True,stdout=subprocess.DEVNULL)
    for name,digest in manifest['source_sha256'].items(): assert sha(source/name)==digest,name
    flags=['-std=c++17','-arch='+args.arch,'-O2','-lineinfo','--expt-relaxed-constexpr','--default-stream','per-thread']
    flags += ['-I'+str(source/p) for p in ('','algo','model','util')]
    if args.asan:
        flags+=['-Xcompiler=-fsanitize=address','-Xcompiler=-fsanitize=undefined',
                '-Xcompiler=-fno-omit-frame-pointer','-Xcompiler=-fno-pie','-Xlinker=-no-pie']
    commands=[]; binaries={}
    for name,input_path in [('kpar',source/'main.cu'),('probe',HERE/'probe.cu')]:
        cmd=['nvcc',str(input_path),*flags,'-o',str(work/name)]
        with (work/(name+'-build.log')).open('w') as log:
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        commands.append(cmd); binaries[name]=sha(work/name)
    report=dict(archive_sha256=manifest['archive_sha256'],patch_sha256=manifest['patch_sha256'],
                source_sha256=manifest['source_sha256'],commands=commands,binaries=binaries,
                nvcc=subprocess.check_output(['nvcc','--version'],text=True),asan=args.asan)
    (work/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(binaries))

if __name__=='__main__': main()
