#!/usr/bin/env python3
import hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'problems/28_influence_maximization/papers/2021_superfuser/code'
COMMIT='1506d275671a456e41bbc7bcb294876615353b2d'
PREFIX=Path('.')
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    files=['Makefile']+sorted(str(f.relative_to(SOURCE)) for f in (SOURCE/'src').iterdir() if f.is_file())
    patch=subprocess.check_output(['git','diff','--binary',COMMIT,'--',*files],cwd=SOURCE)
    base={};source={}
    for name in files:
        original=subprocess.run(['git','show',COMMIT+':'+name],cwd=SOURCE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        base[name]=sha(original.stdout) if original.returncode==0 else None
        if original.returncode:
            addition=subprocess.run(['git','diff','--no-index','--binary','--','/dev/null',name],cwd=SOURCE,stdout=subprocess.PIPE)
            assert addition.returncode==1
            patch+=addition.stdout
        source[name]=sha((SOURCE/name).read_bytes())
    (HERE/'repair.patch').write_bytes(patch)
    manifest=dict(commit=COMMIT,remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=SOURCE,text=True).strip(),prefix=str(PREFIX),patch_sha256=sha(patch),base_sha256=base,source_sha256=source)
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Exported',len(files),'source hashes')
if __name__=='__main__':main()
