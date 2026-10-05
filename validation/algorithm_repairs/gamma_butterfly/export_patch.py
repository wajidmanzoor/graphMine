#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'problems/23_butterfly_counting_bipartite/papers/2022_gamma_reuse/code'
COMMIT='3e01be68ededb8dcc4fa44bdb069a945a822232c'
def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    files=sorted(p.name for p in SOURCE.iterdir() if p.suffix in ['.cu','.cuh','.h','.cpp'] or p.name=='Makefile')
    patch=subprocess.check_output(['git','diff','--binary',COMMIT,'--',*files],cwd=SOURCE)
    base={};source={}
    for name in files:
        original=subprocess.run(['git','show',COMMIT+':'+name],cwd=SOURCE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        base[name]=sha(original.stdout) if original.returncode==0 else None
        if original.returncode:
            added=subprocess.run(['git','diff','--no-index','--binary','--','/dev/null',name],cwd=SOURCE,stdout=subprocess.PIPE)
            assert added.returncode==1
            patch+=added.stdout
        source[name]=sha((SOURCE/name).read_bytes())
    (HERE/'repair.patch').write_bytes(patch)
    manifest=dict(commit=COMMIT,remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=SOURCE,text=True).strip(),
                  patch_sha256=sha(patch),base_sha256=base,source_sha256=source)
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Exported',len(files),'source hashes')
if __name__=='__main__':main()
