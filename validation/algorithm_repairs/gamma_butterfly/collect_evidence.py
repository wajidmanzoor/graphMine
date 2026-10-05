#!/usr/bin/env python3
import gzip
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    work=HERE/'_work';tests=work/'final-tests';evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
    summaries=json.loads((tests/'summary.json').read_text());artifacts={}
    def archive(path,name):
        target=evidence/(name+'.gz');target.write_bytes(gzip.compress(path.read_bytes(),mtime=0))
        artifacts[str(target.relative_to(HERE))]=dict(raw_sha256=sha(path),gzip_sha256=sha(target))
    for name,summary in summaries.items():
        assert summary.get('failures',0)==0
        for filename in ['summary.json','expected.json','results.txt','results.json','commands.txt','run.log']:
            path=tests/name/filename
            if path.exists():archive(path,name+'-'+filename)
    for tool in ['memcheck','initcheck','synccheck']:
        log=(tests/tool/'run.log').read_text();assert 'ERROR SUMMARY: 0 errors' in log
    assert 'LEAK SUMMARY: 0 bytes leaked' in (tests/'memcheck/run.log').read_text()
    assert '(0 errors, 0 warnings)' in (tests/'racecheck/run.log').read_text()
    for name in ['numerical','overflow']:archive(tests/name/'graphs.json',name+'-corpus.json')
    for variant in ['final-build','final-asan-build']:
        for filename in ['build.json','sm-build.log','probe-build.log']:archive(work/variant/filename,variant+'-'+filename)
    for filename in ['summary.json','results.json']:archive(work/'production'/filename,'production-'+filename)
    archive(work/'production-build.log','production-build.log')
    production=json.loads((work/'production/summary.json').read_text())
    totals=dict(numerical_checks=sum(summaries[name]['checks'] for name in ['numerical','poison','asan','overflow'])+
                sum(summaries[name]['positive_checks'] for name in ['cli','asan-cli'])+production['checks'],
                cuda_sanitizer_checks=sum(summaries[name]['checks'] for name in ['memcheck','initcheck','synccheck','racecheck']),
                rejection_checks=sum(summaries[name]['rejections'] for name in ['cli','asan-cli']))
    report=dict(status='passed',totals=totals,suites=summaries,production=production,gpu='physical GPU 1, NVIDIA RTX 6000 Ada Generation (SM 89)')
    (HERE/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    provenance=dict(manifest=json.loads((HERE/'manifest.json').read_text()),baseline_binary_sha256=sha(work/'baseline-binary'),
        normal_build=json.loads((work/'final-build/build.json').read_text()),asan_build=json.loads((work/'final-asan-build/build.json').read_text()),
        production_binary_sha256=production['binary_sha256'],evidence=artifacts)
    (HERE/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n');print(json.dumps(totals))
if __name__=='__main__':main()
