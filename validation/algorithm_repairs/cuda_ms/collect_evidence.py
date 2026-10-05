#!/usr/bin/env python3
"""Package passing final replay evidence; development runs never enter totals."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--production-native',type=Path,required=True)
    args=p.parse_args()
    out=HERE/'evidence';out.mkdir(exist_ok=True)
    cases=json.loads((HERE/'manifest.json').read_text())['cases']
    total=dict(numerical=0,cuda_sanitizer=0,rejections=0)
    suites={}
    inputs=list(args.replay.glob('*/summary.json'))+[args.production_native/'summary.json']
    for file in sorted(inputs):
        source=file.parent
        name='production-native' if source==args.production_native else source.name
        data=json.loads(file.read_text())
        assert not data.get('failures'),(name,data)
        assert data.get('exit_code',0)==0,(name,data)
        assert data.get('sanitizer_clean',True),(name,data)
        if data.get('sanitizer'):total['cuda_sanitizer']+=data['runs']
        elif 'runs' in data:total['numerical']+=data['runs']
        else:
            total['numerical']+=data['numerical']
            total['rejections']+=data['rejections']
        dest=out/name;dest.mkdir(exist_ok=True)
        hashes={}
        for src in sorted(source.iterdir()):
            if not src.is_file():continue
            hashes[src.name]=sha(src)
            if src.name=='summary.json':shutil.copy2(src,dest/src.name)
            else:(dest/(src.name+'.gz')).write_bytes(gzip.compress(src.read_bytes(),mtime=0))
        suites[name]=dict(summary=data,uncompressed_sha256=hashes)
    required={'normal-modes','native','poison','cold','asan','asan-native','repeated','cli','production-native'}
    required.update(prefix+'-'+tool for prefix in ['cuda','modes','cold']
                    for tool in ['memcheck','initcheck','synccheck','racecheck'])
    assert required <= suites.keys(), required-suites.keys()
    builds={}
    for source in sorted(args.replay.glob('clean-*')):
        dest=out/'builds'/source.name;dest.mkdir(parents=True,exist_ok=True)
        for name in ['build.json','build.log']:
            (dest/(name+'.gz')).write_bytes(gzip.compress((source/name).read_bytes(),mtime=0))
        builds[source.name]=json.loads((source/'build.json').read_text())['binaries']
    baseline=HERE/'_work/baseline-optimized'
    baseline_hashes={f.name:sha(f) for f in (baseline/'source').iterdir() if f.is_file()}
    (out/'baseline-build.log.gz').write_bytes(gzip.compress((baseline/'build.log').read_bytes(),mtime=0))
    summary=dict(totals=total,graphs=len(cases),max_vertices=max(c['n'] for c in cases),
                 max_edges=max(len(c['edges']) for c in cases),
                 manifest_sha256=sha(HERE/'manifest.json'),repair_sha256=sha(HERE/'repair.patch'),
                 baseline=dict(optimized_binary_sha256=sha(baseline/'raw_probe'),
                               debug_binary_sha256=sha(HERE/'_work/baseline-find_cliques'),
                               optimized_source_sha256=baseline_hashes),
                 builds=builds,suites=suites)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(totals=total,graphs=len(cases))),flush=True)


if __name__=='__main__':main()
