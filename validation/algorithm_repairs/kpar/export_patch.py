#!/usr/bin/env python3
"""Export the reviewed source as a patch against the pinned release archive."""
import difflib
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parents[3]
ARCHIVE=WORKSPACE/'validation/gpu_correctness_expansion/vendor/kpar/kPAR.zip'
SOURCE=WORKSPACE/'problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src'

def main():
    patch=[]; hashes={}
    with zipfile.ZipFile(ARCHIVE) as z:
        for path in sorted(SOURCE.rglob('*')):
            if path.is_file() and (path.suffix in ('.h','.cuh','.cu') or path.name=='Makefile'):
                name=str(path.relative_to(SOURCE))
                original=z.read('kPAR/src/'+name).decode().replace('\r\n','\n')
                updated=path.read_text()
                patch.extend(difflib.unified_diff(original.splitlines(True),updated.splitlines(True),
                    fromfile='a/src/'+name,tofile='b/src/'+name))
                hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (HERE/'repair.patch').write_text(''.join(patch))
    manifest=dict(archive_url='https://github.com/jmshi123/kPAR/releases/download/v1.0/kPAR.zip',
        archive_sha256=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
        patch_sha256=hashlib.sha256((HERE/'repair.patch').read_bytes()).hexdigest(),source_sha256=hashes)
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Exported',len(hashes),'source files')

if __name__=='__main__': main()
