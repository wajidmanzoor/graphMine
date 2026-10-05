#!/usr/bin/env python3
"""Archive final evidence without counting development or startup failures."""
import gzip
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    work=HERE/'_work';tests=work/'final-tests'; evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
    mapping={'numerical':'numerical','tight-epsilon':'tight-epsilon','asan':'asan-compatible',
             'memcheck':'memcheck-leaks','initcheck':'initcheck','synccheck':'synccheck','racecheck':'racecheck',
             'cli':'cli','asan-cli':'asan-cli'}
    summaries={}; artifacts={}
    def archive(path,name):
        target=evidence/(name+'.gz');target.write_bytes(gzip.compress(path.read_bytes(),mtime=0))
        artifacts[str(target.relative_to(HERE))]={'raw_sha256':sha(path),'gzip_sha256':sha(target)}
    for name,folder in mapping.items():
        path=tests/folder
        summaries[name]=json.loads((path/'summary.json').read_text())
        assert summaries[name].get('failures',0)==0
        for filename in ['summary.json','results.txt','results.json','run.log','commands.txt']:
            if (path/filename).exists():archive(path/filename,name+'-'+filename)
        if name in ['memcheck','initcheck','synccheck']:
            assert 'ERROR SUMMARY: 0 errors' in (path/'run.log').read_text()
        if name=='memcheck': assert 'LEAK SUMMARY: 0 bytes leaked' in (path/'run.log').read_text()
        if name=='racecheck':assert '(0 errors, 0 warnings)' in (path/'run.log').read_text()
    archive(tests/'numerical/graphs.json','corpus.json')
    # Retain the failed default-ASan CUDA initialization as a separate environment finding.
    archive(tests/'asan/run.log','asan-default-startup-failure.log')
    for name in ['final-build','final-asan-build']:
        for filename in ['build.json','kpar-build.log','probe-build.log']:
            archive(work/name/filename,name+'-'+filename)
    for filename in ['summary.json','results.json']:archive(work/'production-smoke'/filename,'production-'+filename)
    production=json.loads((work/'production-smoke/summary.json').read_text())
    totals={
        'numerical_queries':sum(summaries[k]['queries'] for k in ['numerical','tight-epsilon','asan'])+
                            sum(summaries[k]['positive_queries'] for k in ['cli','asan-cli'])+production['positive_queries'],
        'cuda_sanitizer_queries':sum(summaries[k]['queries'] for k in ['memcheck','initcheck','synccheck','racecheck']),
        'rejection_checks':sum(summaries[k]['rejections'] for k in ['cli','asan-cli']),
        'deterministic_index_rebuilds':sum(summaries[k]['deterministic_index_rebuilds'] for k in ['cli','asan-cli'])}
    report={'status':'passed','totals':totals,'suites':summaries,'production':production,
            'gpu':'physical GPU 1, NVIDIA RTX 6000 Ada Generation (SM 89)',
            'default_asan_startup_failure_excluded':True}
    (HERE/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest=json.loads((HERE/'manifest.json').read_text())
    provenance={'manifest':manifest,'baseline_binary_sha256':sha(work/'baseline-kpar'),
                'clean_build':json.loads((work/'final-build/build.json').read_text()),
                'asan_build':json.loads((work/'final-asan-build/build.json').read_text()),
                'production_binary_sha256':production['binary_sha256'],'evidence':artifacts}
    (HERE/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(totals))

if __name__=='__main__':main()
