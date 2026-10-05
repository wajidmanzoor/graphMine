#!/usr/bin/env python3
"""Clean rebuild and sequential replay; only the selected physical GPU is used."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-checkout',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--existing-builds',type=Path,help='Use clean-normal/poison/cold/asan in this directory')
    p.add_argument('--skip-normal',action='store_true',help='Normal six-mode suite was already run separately')
    p.add_argument('--gpu',type=int,default=1)
    args=p.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    builds=args.existing_builds.resolve() if args.existing_builds else output

    def call(script,*opts):
        command=[sys.executable,str(HERE/script),*map(str,opts)]
        print('RUN '+' '.join(command),flush=True)
        subprocess.run(command,check=True)

    if not args.existing_builds:
        for variant,flags in [('normal',[]),('poison',['--poison']),('cold',['--cold']),('asan',['--asan'])]:
            call('build.py','--source-checkout',args.source_checkout.resolve(),
                 '--output',builds/f'clean-{variant}',*flags)

    def check(name,variant='normal',native=False,extra=()):
        binary=builds/f'clean-{variant}'/('native_probe' if native else 'raw_probe')
        call('validate.py','--binary',binary,'--output',output/name,'--gpu',args.gpu,
             *(['--native'] if native else []),*extra)

    if not args.skip_normal: check('normal-modes',extra=['--modes',1,2,3,4,5,6])
    check('native',native=True)
    check('poison',variant='poison')
    check('cold',variant='cold')
    check('asan',variant='asan')
    check('asan-native',variant='asan',native=True)
    check('repeated',extra=['--ids','audit-9','complete-65','cycle-33',
                           'multipartite-4-9','star-129','planted-2049','--repeat',20])
    call('cli_suite.py','--binary',builds/'clean-normal/find_cliques','--output',output/'cli','--gpu',args.gpu)
    families=['audit-9','cycle_chords-01','complete-33','complete-65','complete-129',
              'cycle-33','star-129','bipartite-17','multipartite-4-9',
              'boundary-random-513','cycle-1025','planted-2049']
    for sanitizer in ['memcheck','initcheck','synccheck','racecheck']:
        check('cuda-'+sanitizer,extra=['--ids',*families,'--sanitizer',sanitizer])
        check('modes-'+sanitizer,extra=['--ids','audit-9','--modes',1,2,3,4,5,6,
                                      '--sanitizer',sanitizer])
        check('cold-'+sanitizer,variant='cold',extra=['--ids','audit-9','complete-65',
              'multipartite-4-9','boundary-random-513','--sanitizer',sanitizer])
    summaries={str(f.parent.relative_to(output)):json.loads(f.read_text())
               for f in output.rglob('summary.json')}
    (output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')


if __name__=='__main__':main()
