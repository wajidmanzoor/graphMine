#!/usr/bin/env python3
"""Run the final tests sequentially; GPU 1 is isolated by each test driver."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--build',type=Path,required=True)
    ap.add_argument('--asan-build',type=Path,required=True);ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--only',default='',help='Comma-separated suite names; continue unaffected suites after a diagnosed failure')
    args=ap.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    summaries=json.loads((work/'summary.json').read_text()) if (work/'summary.json').exists() else {}
    def run(name,script,binary,flags):
        if args.only and name not in args.only.split(','): return
        out=work/name
        arg='--probe' if script=='validate.py' else '--binary'
        cmd=[sys.executable,str(HERE/script),arg,str(binary.resolve()),'--work',str(out),*flags]
        subprocess.run(cmd,check=True,env=env)
        summaries[name]=json.loads((out/'summary.json').read_text())
        (work/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    run('numerical','validate.py',args.build/'probe',['--full','--seeds','0,1,20261004'])
    run('tight-epsilon','validate.py',args.build/'probe',['--epsilons','0.01','--max-sources','2'])
    run('asan','validate.py',args.asan_build/'probe',['--full'])
    for tool in ['memcheck','initcheck','synccheck','racecheck']:
        run(tool,'validate.py',args.build/'probe',['--full','--case-filter',
            'singleton,isolates,digraph3_49,chain_33,star_33,cycle_513,biclique_550,random_45',
            '--max-sources','1','--k-values','4','--epsilons','0.1','--tool',tool])
    run('cli','cli_suite.py',args.build/'kpar',[])
    run('asan-cli','cli_suite.py',args.asan_build/'kpar',[])
    print('Requested kPAR suites passed',flush=True)

if __name__=='__main__':main()
