#!/usr/bin/env python3
"""Record the full source patch without resetting either upstream worktree."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
COMMIT='a0b6b00a1f67b6fe65380b2efcb242cf40889d83'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    args=p.parse_args()
    files=sorted(f for f in args.source.iterdir() if f.suffix in {'.c','.h','.cu','.cuh'} or f.name=='Makefile')
    parts=[]
    for f in files:
        old=subprocess.run(['git','-C',str(args.source),'show',COMMIT+':'+f.name],capture_output=True)
        before=old.stdout.decode() if old.returncode==0 else ''
        parts.extend(difflib.unified_diff(before.splitlines(True),f.read_text().splitlines(True),
                      fromfile='a/'+f.name if old.returncode==0 else '/dev/null',tofile='b/'+f.name))
    (HERE/'repair.patch').write_text(''.join(parts))
    library=HERE.parents[2]/'library'
    sources=['src/backends/cuda_ms.cpp','src/backends/gpu_maximum_clique_stub.cpp',
             'src/backends/maximum_clique_on_gpu_stub.cpp','src/core/graph.cpp',
             'src/problems/maximum_clique.cpp','src/backends/maximum_clique_backend.hpp',
             'CMakeLists.txt','tests/maximum_clique_test.cpp']
    provenance=dict(commit=COMMIT,patch_sha256=sha(HERE/'repair.patch'),
                    source_sha256={f.name:sha(f) for f in files},
                    library_source_sha256={name:sha(library/name) for name in sources})
    (HERE/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')


if __name__=='__main__':main()
