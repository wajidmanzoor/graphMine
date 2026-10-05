#!/usr/bin/env python3
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from validate import config,write_graph,ensemble,prefix_spread,mix,EVAL_KEY,MASK

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True);binary=str(args.binary.resolve())
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    base=config('base',5,[(0,1,.5),(1,2,.25),(2,3,.75),(0,4,.5),(3,4,1)],2,R=96)
    path=work/'graph with spaces.txt';write_graph(path,base)
    results=[];positive_checks=0;prefix_checks=0
    def invoke(name,words,okay,c=None,output=None,custom_env=None):
        nonlocal positive_checks,prefix_checks
        r=subprocess.run([binary,*words],capture_output=True,text=True,timeout=40,env=custom_env or env)
        text=r.stdout+r.stderr;(work/(name+'.log')).write_text(text)
        assert (r.returncode==0)==okay,(name,r.returncode,text)
        assert 'AddressSanitizer' not in text and 'runtime error:' not in text,(name,text)
        decoded=None
        if okay:
            positive_checks+=1
            if c is not None:
                source=output.read_text() if output else r.stdout
                if output:assert not r.stdout
                if '--json' in words:
                    decoded=json.loads(source);seeds=decoded['seed_set'];spread=decoded['prefix_spread']
                    assert decoded['diffusion_model']=='independent_cascade' and decoded['guarantee_met'] is False
                    assert decoded['random_seed']==c['seed'] and decoded['sample_count']==decoded['evaluation_sample_count']==c['R']
                    assert decoded['training_prefix_spread']==prefix_spread(ensemble(c['n'],c['edges'],c['R'],c['seed']),seeds)
                    assert decoded['expected_spread']==(spread[-1] if spread else 0)
                else:
                    rows=[line.split() for line in source.splitlines()];assert all(len(row)==3 for row in rows)
                    seeds=[int(row[0]) for row in rows];spread=[float(row[1]) for row in rows];assert all(float(row[2])>=0 for row in rows)
                assert len(seeds)==c['K'] and len(set(seeds))==len(seeds) and all(0<=v<c['n'] for v in seeds)
                assert spread==prefix_spread(ensemble(c['n'],c['edges'],c['R'],mix(c['seed']^EVAL_KEY)),seeds)
                prefix_checks+=len(seeds)
        results.append(dict(name=name,kind='positive' if okay else 'rejection',exit=r.returncode,arguments=words))
        return decoded
    invoke('help',['--help'],True)
    valid=['-g','1','-K','2','-R','96','--json',str(path)]
    expected=invoke('basic',valid,True,base)
    invoke('legacy-tsv',[x for x in valid if x!='--json'],True,base)
    for name,extra in [('method-super',['-M','super']),('model-ic',['--model','independent_cascade']),('block32',['-B','32']),('block1024',['-B','1024'])]:
        assert invoke(name,extra+valid,True,base)==expected
    char={**base,'chars':True};invoke('char',['-M','char',*valid],True,char)
    largest={**base,'seed':MASK};invoke('uint64-seed',['--seed',str(MASK),*valid],True,largest)
    output=work/'result with spaces.json';invoke('output-file',['-o',str(output),*valid],True,base,output)
    # Neighbor order, whitespace, comments and repeated arcs normalize consistently.
    path.write_text('# graph\n\n5 5 # counts\n'+''.join(f'{u}\t{v} {p} # edge\n' for u,v,p in base['edges']))
    assert invoke('normalized-order',valid,True,base)==expected
    for c in [config('empty',0,[],0,R=32),config('edgeless',4,[],4,R=32),config('single',1,[],1,R=32),
              config('duplicates',3,[(0,1,.5),(0,1,.5),(1,2,1),(1,1,1)],1,R=4096),config('zero-budget',3,[(0,1,1)],0,R=32)]:
        p=work/(c['name']+'.txt');write_graph(p,c);invoke(c['name'],['-K',str(c['K']),'-R',str(c['R']),'--json',str(p)],True,c)
    for name,words in {
        'no-arguments':[], 'missing-value':['-K'], 'unknown-option':['--bogus',str(path)],'ignored-old-tolerance':['-e','.1',str(path)],
        'bad-method':['-M','bad',str(path)], 'unsupported-lt':['--model','linear_threshold',str(path)],
        'two-files':[str(path),str(path)], 'missing-file':['-K','1',str(work/'absent')],
        'k-negative':['-K','-1',str(path)],'k-fraction':['-K','1.5',str(path)],'k-too-large':['-K','6',str(path)],
        'k-overflow':['-K',str(1<<32),str(path)], 'r-zero':['-R','0',str(path)], 'r31':['-R','31',str(path)],'r33':['-R','33',str(path)],
        'r-too-large':['-R',str((1<<24)+32),str(path)],'r-junk':['-R','32x',str(path)],'r-negative':['-R','-32',str(path)],
        'g-zero':['-g','0',str(path)],'g-negative':['-g','-1',str(path)],'g-invisible':['-g','2',str(path)],'g-too-large':['-g','65',str(path)],
        'b-small':['-B','16',str(path)],'b-large':['-B','2048',str(path)],'b-nonpower':['-B','96',str(path)],
        'seed-negative':['--seed','-1',str(path)],'seed-overflow':['--seed',str(1<<64),str(path)],
        'input-output-identical':['-o',str(path),*valid], 'output-directory':['-o',str(work),*valid],
    }.items():invoke(name,words,False)
    before=hashlib.sha256(path.read_bytes()).hexdigest();alias=work/'alias.txt';alias.symlink_to(path)
    invoke('input-output-alias',['-o',str(alias),*valid],False);assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    malformed={
        'empty-file':'', 'header-missing-count':'3\n','header-extra':'3 0 1\n','negative-n':'-1 0\n','negative-m':'3 -1\n',
        'large-n':f'{1<<32} 0\n','huge-count':f'3 {MASK}\n','bad-n':'3x 0\n',
        'too-few':'3 1\n','too-many':'3 0\n0 1 .5\n','short-edge':'3 1\n0 1\n','extra-edge-column':'3 1\n0 1 .5 1\n',
        'negative-source':'3 1\n-1 1 .5\n','negative-dest':'3 1\n0 -1 .5\n','source-range':'3 1\n3 0 .5\n','dest-range':'3 1\n0 3 .5\n',
        'nan':'3 1\n0 1 nan\n','infinity':'3 1\n0 1 inf\n','negative-p':'3 1\n0 1 -.1\n','p-over-one':'3 1\n0 1 1.01\n',
        'p-suffix':'3 1\n0 1 .5x\n','p-text':'3 1\n0 1 maybe\n','empty-with-edge':'0 1\n0 0 1\n',
    }
    for name,text in malformed.items():
        p=work/(name+'.txt');p.write_text(text);invoke(name,['-K','1',str(p)],False)
    invoke('no-visible-device',valid,False,custom_env={**env,'CUDA_VISIBLE_DEVICES':''})
    summary=dict(status='passed',positive_checks=positive_checks,prefix_checks=prefix_checks,rejections=sum(r['kind']=='rejection' for r in results),failures=0,binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
    (work/'results.json').write_text(json.dumps(results,indent=2)+'\n');(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
