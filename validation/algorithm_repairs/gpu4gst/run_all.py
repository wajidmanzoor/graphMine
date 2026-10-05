#!/usr/bin/env python3
import argparse,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,default=HERE/'_work/final-tests');ap.add_argument('--normal-build',type=Path,default=HERE/'_work/final-build');ap.add_argument('--asan-build',type=Path,default=HERE/'_work/final-asan-build');args=ap.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    normal=args.normal_build.resolve();asan=args.asan_build.resolve();steps=[('numerical',normal/'probe','numerical',None,1),('repeat',normal/'probe','stress',None,10)]
    steps += [(tool,normal/'probe','sanitizer',tool,1) for tool in ['memcheck','initcheck','racecheck','synccheck']]
    steps += [('asan',asan/'probe','numerical',None,1)]
    summaries={}
    for name,binary,suite,tool,repeat in steps:
        cmd=[sys.executable,str(HERE/'validate.py'),'--binary',str(binary),'--work',str(work/name),'--suite',suite,'--repeat',str(repeat)]
        if tool:cmd+=['--tool',tool]
        print('RUN',name,flush=True);subprocess.run(cmd,check=True)
        summaries[name]=json.loads((work/name/'summary.json').read_text());(work/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    for name,build in [('cli',normal),('asan-cli',asan)]:
        print('RUN',name,flush=True)
        subprocess.run([sys.executable,str(HERE/'cli_suite.py'),'--binary',str(build/'TrimCDP-WB'),'--work',str(work/name)],check=True)
        summaries[name]=json.loads((work/name/'summary.json').read_text());(work/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print('All GPU4GST suites passed',flush=True)
if __name__=='__main__':main()
