#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--build',type=Path,required=True);ap.add_argument('--asan-build',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True);ap.add_argument('--only',default='');args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    summaries=json.loads((work/'summary.json').read_text()) if (work/'summary.json').exists() else {}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    def run(name,script,binary,flags):
        if args.only and name not in args.only.split(','):return
        out=work/name;argument='--probe' if script=='validate.py' else '--binary'
        cmd=[sys.executable,str(HERE/script),argument,str(binary.resolve()),'--work',str(out),*flags]
        subprocess.run(cmd,env=env,check=True)
        summaries[name]=json.loads((out/'summary.json').read_text());(work/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    run('numerical','validate.py',args.build/'probe',['--full'])
    run('poison','validate.py',args.build/'probe',['--full','--poison'])
    run('asan','validate.py',args.asan_build/'probe',['--full'])
    run('overflow','validate.py',args.build/'probe',['--overflow','--modes','0,1,2,3'])
    for tool in ['memcheck','initcheck','synccheck','racecheck']:
        run(tool,'validate.py',args.build/'probe',['--cases','empty_0,empty_4,complete_2_2,complete_8_9,complete_2_33,random_2,permuted_2,query_permutation_7,labels_5,wildcard,ordering,query_path_7,disconnected_query,complete_2_1001','--tool',tool])
    run('cli','cli_suite.py',args.build/'sm',[])
    run('asan-cli','cli_suite.py',args.asan_build/'sm',[])
    print('Requested GAMMA suites passed',flush=True)
if __name__=='__main__':main()
