#!/usr/bin/env python3
import gzip,hashlib,json,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    work=HERE/'_work';tests=work/'final-tests';evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
    suites=json.loads((tests/'summary.json').read_text());artifacts={}
    def archive(path,name):
        dest=evidence/(name+'.gz');dest.write_bytes(gzip.compress(path.read_bytes(),mtime=0))
        artifacts[str(dest.relative_to(HERE))]=dict(raw_sha256=sha(path),gzip_sha256=sha(dest))
    for name,summary in suites.items():
        assert summary['status']=='passed' and summary['failures']==0
        for file in ['summary.json','results.json','commands.txt','invocation.json','run.log']:
            path=tests/name/file
            if path.exists():archive(path,name+'-'+file)
        if name in ['cli','asan-cli']:
            # Preserve every rejected input's actual diagnostic as well as its exit code.
            bundle=''.join(f'===== {p.name} =====\n'+p.read_text() for p in sorted((tests/name).glob('*.log')))
            path=tests/name/'diagnostics.txt';path.write_text(bundle);archive(path,name+'-diagnostics.txt')
    for name in ['numerical','repeat','memcheck']:archive(tests/name/'corpus.json',name+'-corpus.json')
    for tool in ['memcheck','initcheck','synccheck']:
        assert 'ERROR SUMMARY: 0 errors' in (tests/tool/'run.log').read_text()
    assert 'LEAK SUMMARY: 0 bytes leaked' in (tests/'memcheck/run.log').read_text()
    assert '(0 errors, 0 warnings)' in (tests/'racecheck/run.log').read_text()
    for variant in ['final-build','final-asan-build']:
        for file in ['build.json','TrimCDP-WB-build.log','probe-build.log']:archive(work/variant/file,variant+'-'+file)
    for file in ['native-cmake-build.log','native-make-build.log','baseline-fresh-build.log','baseline-fresh.json']:
        archive(work/file,file)
    for name in ['explore','explore-stage2','explore-stage3','explore-stage4']:
        archive(work/name/'summary.json',name+'-summary.json')
    for file in ['summary.json','results.json']:
        archive(work/'stage5-clean-tests/numerical'/file,'intermediate-completion-'+file)
    archive(work/'weighted-large-failure.log','intermediate-weighted-failure.log')
    corpus=json.loads((work/'stage5-clean-tests/numerical/corpus.json').read_text())
    selected=[c for c in corpus if c['name']=='weighted-023-repeat-0']
    path=work/'completion-counterexample.json';path.write_text(json.dumps(selected));archive(path,'completion-counterexample.json')
    production=json.loads((work/'production/summary.json').read_text())
    archive(work/'production/summary.json','production-summary.json')
    archive(work/'production/results.json','production-results.json')
    for label in ['make','cmake']:
        archive(work/'production'/label/'results.json','production-'+label+'-results.json')
    totals=dict(numerical_checks=sum(suites[n]['checks'] for n in ['numerical','repeat','asan'])+
        sum(suites[n]['positive_checks'] for n in ['cli','asan-cli'])+production['checks'],
        cuda_sanitizer_checks=sum(suites[n]['checks'] for n in ['memcheck','initcheck','racecheck','synccheck']),
        rejection_checks=sum(suites[n]['rejections'] for n in ['cli','asan-cli'])+production['rejections'])
    report=dict(status='passed',totals=totals,suites=suites,production=production,gpu='physical GPU 1, NVIDIA RTX 6000 Ada Generation (SM 89)')
    (HERE/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    provenance=dict(manifest=json.loads((HERE/'manifest.json').read_text()),historical_baseline_sha256=sha(work/'baseline-device0'),
        fresh_baseline_sha256=sha(work/'baseline-fresh-device0'),normal_build=json.loads((work/'final-build/build.json').read_text()),
        asan_build=json.loads((work/'final-asan-build/build.json').read_text()),production=production,evidence=artifacts)
    (HERE/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n');print(json.dumps(totals))
if __name__=='__main__':main()
