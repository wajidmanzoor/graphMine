#!/usr/bin/env python3
"""Independent reachability/live-graph oracles for repaired GPU SuperFuser."""
import argparse,decimal,functools,itertools,json,math,os,random,struct,subprocess,time
from pathlib import Path
MASK=(1<<64)-1
EDGE_KEY=0x6a09e667f3bcc909
RANK_KEY=0xbb67ae8584caa73b
EVAL_KEY=0x3c6ef372fe94f82b

def mix(x):
    x&=MASK;x^=x>>30;x=x*0xbf58476d1ce4e5b9&MASK;x^=x>>27;x=x*0x94d049bb133111eb&MASK;return x^(x>>31)
def draw(key,item,sample):return mix(key^mix(item+0x9e3779b97f4a7c15)^mix(sample+0xd1b54a32d192ed03))
def normalize(edges):
    buckets={}
    with decimal.localcontext() as ctx:
        ctx.prec=60
        for u,v,p in edges:
            if u==v:continue
            buckets.setdefault((u,v),[]).append(decimal.Decimal(str(p)))
        result=[]
        for (u,v),ps in sorted(buckets.items()):
            remain=decimal.Decimal(1)
            for p in ps:remain*=1-p
            threshold=int((1-remain)*(1<<32))
            if threshold:result.append((u,v,threshold))
    return result

def closure(n,edges):
    reach=[1<<v for v in range(n)]
    for u,v in edges:reach[u]|=1<<v
    for k in range(n):
        bit=1<<k
        for v in range(n):
            if reach[v]&bit:reach[v]|=reach[k]
    return tuple(reach)
def ensemble(n,edges,R,seed):
    edges=normalize(edges)
    if all(p==(1<<32) for u,v,p in edges):return [closure(n,[(u,v) for u,v,p in edges])]*R
    return [closure(n,[(u,v) for e,(u,v,p) in enumerate(edges) if draw(seed^EDGE_KEY,e,r)>>32<p]) for r in range(R)]
def covered(reach,seeds):
    bits=0
    for s in seeds:bits|=reach[s]
    return bits

def prefix_spread(samples,seeds):
    return [sum(covered(reach,seeds[:k]).bit_count() for reach in samples)/len(samples) for k in range(1,len(seeds)+1)]

def true_spreads(n,edges):
    """Enumerate every independent live-edge outcome, then every seed subset."""
    edges=normalize(edges);fixed=[(u,v) for u,v,p in edges if p==(1<<32)];variable=[(u,v,p/(1<<32)) for u,v,p in edges if p<(1<<32)]
    assert len(variable)<=14
    expected=[0.]*(1<<n)
    for mask in range(1<<len(variable)):
        probability=1.;live=list(fixed)
        for e,(u,v,p) in enumerate(variable):
            probability*=p if mask>>e&1 else 1-p
            if mask>>e&1:live.append((u,v))
        if not probability:continue
        reach=closure(n,live);unions=[0]*(1<<n)
        for seedmask in range(1,1<<n):
            bit=seedmask&-seedmask;unions[seedmask]=unions[seedmask^bit]|reach[bit.bit_length()-1]
            expected[seedmask]+=probability*unions[seedmask].bit_count()
    return expected

def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
@functools.lru_cache(maxsize=96)
def ranks(n,R,seed,chars):
    out=[]
    for v in range(n):
        row=[]
        for r in range(R):
            nonce=draw(seed^RANK_KEY,v,r)
            if chars:value=65-nonce.bit_length()
            else:
                reciprocal=0.
                for k in range(4):
                    nonce=mix(nonce+k+1);reciprocal=f32(reciprocal+f32(1/(65-nonce.bit_length())))
                value=f32(4/reciprocal)
            row.append(value)
        out.append(row)
    return out

def core_oracle(c):
    samples=ensemble(c['n'],c['edges'],c['R'],c['seed']);initial=ranks(c['n'],c['R'],c['seed'],c['chars']);values=[]
    for k in range(c['K']+1):
        active=[covered(reach,list(range(k))) for reach in samples]
        for v in range(c['n']):
            for r,reach in enumerate(samples):
                if active[r]>>v&1:values.append(-1.);continue
                vertices=reach[v]&~active[r];value=0.
                while vertices:
                    bit=vertices&-vertices;vertices-=bit;value=max(value,initial[bit.bit_length()-1][r])
                values.append(value)
    return struct.pack('<'+'f'*len(values),*values)

def config(name,n,edges,K=1,R=256,seed=42,chars=False,B=256,parts=1,mode='solve',quality=True):
    return dict(name=name,n=n,edges=edges,K=K,R=R,seed=seed,chars=chars,B=B,parts=parts,mode=mode,quality=quality)

def numerical():
    cases=[];pairs=list(itertools.permutations(range(4),2))
    for mask in range(4096):
        edges=[(u,v,1) for e,(u,v) in enumerate(pairs) if mask>>e&1]
        for k in [1,2,4]:cases.append(config(f'directed4-{mask:04d}-k{k}',4,edges,k,R=32,chars=(mask+k)%2==0,B=[32,128,256][k%3]))
    pairs3=list(itertools.permutations(range(3),2))
    for i,weights in enumerate(itertools.product([0,.5,1],repeat=6)):
        edges=[(u,v,p) for (u,v),p in zip(pairs3,weights) if p]
        for k in [1,2]:cases.append(config(f'probability3-{i:03d}-k{k}',3,edges,k,R=256,seed=i%5,chars=i%2==0))
    rng=random.Random(20261004)
    for i in range(90):
        n=rng.randrange(2,7);pairs=list(itertools.permutations(range(n),2));rng.shuffle(pairs)
        edges=[(u,v,rng.choice([0,.25,.5,.75,1])) for u,v in pairs[:rng.randrange(min(len(pairs),10)+1)]]
        k=rng.randrange(1,n+1)
        cases.append(config(f'weighted-{i:03d}',n,edges,k,R=[32,64,96,256,1024][i%5],seed=[0,42,MASK][i%3],chars=i%2==0,B=[32,64,128,256,512,1024][i%6]))
    return cases+stress()

def stress():
    cases=[config('empty',0,[],0),config('isolates',7,[],7,R=32),config('all-zero',5,[(i,(i+1)%5,0) for i in range(5)],5,R=96),
        config('parallel-loops',4,[(0,0,1),(0,1,.5),(0,1,.5),(1,2,.25),(2,3,1),(2,3,0),(3,3,.5)],2,R=1024)]
    for n in [8,64,257,513]:
        path=[(v,v+1,1) for v in range(n-1)]
        cases.append(config(f'path-{n}',n,path,1,R=32,quality=False))
        cases.append(config(f'reverse-path-{n}',n,[(n-1-u,n-1-v,p) for u,v,p in path],1,R=32,quality=False))
        cases.append(config(f'star-{n}',n,[(0,v,1) for v in range(1,n)],2,R=32,quality=False))
        cases.append(config(f'fan-in-{n}',n,[(v,n-1,1) for v in range(n-1)],min(3,n),R=96,quality=False))
    cases.append(config('star-4097',4097,[(0,v,1) for v in range(1,4097)],2,R=32,quality=False))
    n=65;edges=[(u,v,1) for u in range(n) for v in range(n) if u!=v]
    cases.append(config('dense65',n,edges,3,R=32,quality=False))
    weighted=[(0,1,.5),(1,2,.5),(2,3,.5),(0,3,.25),(3,4,.5),(1,4,.75)]
    for parts in [1,2,3,5]:
        for B in [32,256,1024]:cases.append(config(f'partition-{parts}-block-{B}',5,weighted,3,R=96,parts=parts,B=B))
    # Large ensembles expose correlated edge draws and biased spread reporting.
    for i,edges in enumerate([[(0,1,.5),(1,2,.5)],[(0,1,.25),(1,2,.75)],[(0,1,.5),(0,2,.5),(1,2,.5)],[(0,1,.5),(1,2,.5),(2,0,.5)]]):
        cases.append(config(f'calibration-{i}',3,edges,1,R=65536,seed=117+i))
    return cases

def core_cases():
    cases=[];pairs=list(itertools.permutations(range(3),2))
    for mask in range(64):
        edges=[(u,v,.5 if mask%3==0 else 1) for e,(u,v) in enumerate(pairs) if mask>>e&1]
        for chars in [False,True]:
            for parts in [1,3]:cases.append(config(f'core3-{mask}-{int(chars)}-p{parts}',3,edges,3,R=96,seed=mask%7,chars=chars,B=32 if parts==1 else 256,parts=parts,mode='core'))
    cases += [config('core-star-65',65,[(0,v,1) for v in range(1,65)],2,R=32,mode='core'),
              config('core-cycle-17',17,[(v,(v+1)%17,.75) for v in range(17)],2,R=96,parts=5,B=1024,mode='core'),
              config('core-star-4097',4097,[(0,v,1) for v in range(1,4097)],1,R=32,B=32,mode='core')]
    return cases

def selected(suite):
    if suite=='numerical':return numerical()
    if suite=='core':return core_cases()
    if suite=='stress':return stress()
    if suite=='sanitizer':
        return core_cases()[::23]+core_cases()[-1:]+[c for c in stress() if c['name'] in ['empty','isolates','parallel-loops','path-64','reverse-path-64','star-257','fan-in-257','dense65','partition-3-block-32','partition-5-block-1024']]
    raise ValueError(suite)

def write_graph(path,c):
    path.write_text(f"{c['n']} {len(c['edges'])}\n"+''.join(f'{u} {v} {p}\n' for u,v,p in reversed(c['edges'])))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--suite',choices=['numerical','core','stress','sanitizer'],default='numerical');ap.add_argument('--tool',choices=['memcheck','initcheck','racecheck','synccheck']);ap.add_argument('--repeat',type=int,default=1);ap.add_argument('--corpus',type=Path);args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True);inputs=work/'inputs';inputs.mkdir(exist_ok=True)
    source=json.loads(args.corpus.read_text()) if args.corpus else selected(args.suite)
    cases=[{**c,'name':c['name']+f'-r{r}'} for r in range(args.repeat) for c in source]
    (work/'corpus.json').write_text(json.dumps(cases));commands=[]
    for c in cases:
        path=inputs/(c['name']+'.txt');write_graph(path,c)
        command=f"{c['name']} {json.dumps(str(path))} {c['K']} {c['R']} {c['seed']} {c['B']} {int(c['chars'])} {c['parts']} {c['mode']}"
        if c['mode']=='core':
            truth=inputs/(c['name']+'.truth');truth.write_bytes(core_oracle(c));command+=' '+json.dumps(str(truth))
        commands.append(command)
    text='\n'.join(commands)+'\n';(work/'commands.txt').write_text(text)
    cmd=[str(args.binary.resolve())]
    if args.tool:cmd=['compute-sanitizer','--tool',args.tool,'--error-exitcode','97',*(['--leak-check','full'] if args.tool=='memcheck' else []),*cmd]
    (work/'invocation.json').write_text(json.dumps(cmd))
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    start=time.monotonic()
    with (work/'run.log').open('w') as log:r=subprocess.run(cmd,input=text,text=True,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=2400)
    log=(work/'run.log').read_text();results={json.loads(line)['name']:json.loads(line) for line in log.splitlines() if line.startswith('{')}
    errors=[];checks=0;prefix_checks=0;core_checks=0;quality=[];stat_checks=0
    for c in cases:
        try:
            result=results[c['name']]
            if c['mode']=='core':assert result['core_checks']==c['n']*c['R']*(c['K']+1);core_checks+=result['core_checks']
            else:
                seeds=result['seeds'];assert len(seeds)==c['K'] and len(set(seeds))==len(seeds) and all(0<=s<c['n'] for s in seeds)
                training=prefix_spread(ensemble(c['n'],c['edges'],c['R'],c['seed']),seeds)
                holdout=prefix_spread(ensemble(c['n'],c['edges'],c['R'],mix(c['seed']^EVAL_KEY)),seeds)
                assert result['training']==training,(result['training'],training)
                assert result['spread']==holdout,(result['spread'],holdout)
                assert all(a<=b for a,b in zip(holdout,holdout[1:]))
                prefix_checks+=len(seeds)
                if c['quality'] and seeds:
                    truth=true_spreads(c['n'],c['edges']);observed=truth[sum(1<<v for v in seeds)]
                    optimum=max(v for mask,v in enumerate(truth) if mask.bit_count()==len(seeds))
                    ratio=observed/optimum if optimum else 1
                    quality.append(dict(name=c['name'],ratio=ratio,exact_spread=observed,optimum=optimum))
                    assert ratio+1e-12>=.63,('quality',ratio,observed,optimum,seeds)
                    # Predeclared Hoeffding accuracy screen, applied to an
                    # independent evaluation ensemble; no quality certificate.
                    tolerance=c['n']*math.sqrt(math.log(2*max(1,len(cases))/1e-6)/(2*c['R']))
                    assert abs(holdout[-1]-observed)<=tolerance,('calibration',holdout[-1],observed,tolerance)
                    stat_checks+=1
                if c['name'].startswith('path-'):
                    assert result['spread']==[c['n']] and result['training']==[c['n']],('path optimum',seeds,result)
                elif c['name'].startswith('reverse-path-'):
                    assert result['spread'][-1]>=.63*c['n'],('path quality',seeds,result)
            checks+=1
        except (AssertionError,KeyError,ValueError) as e:errors.append(dict(name=c['name'],error=str(e)))
    if r.returncode:errors.append(dict(process_exit=r.returncode))
    if args.tool and args.tool!='racecheck' and 'ERROR SUMMARY: 0 errors' not in log:errors.append(dict(sanitizer='missing clean summary'))
    if args.tool=='racecheck' and '(0 errors, 0 warnings)' not in log:errors.append(dict(sanitizer='racecheck not clean'))
    if args.tool=='memcheck' and 'LEAK SUMMARY: 0 bytes leaked' not in log:errors.append(dict(sanitizer='leak summary not clean'))
    # Sharding and launch-size changes must preserve the actual sampled problem.
    partitioned=[results[c['name']] for c in cases if c['name'].startswith('partition-') and c['name'] in results]
    if partitioned:
        target={k:partitioned[0][k] for k in ['seeds','training','spread']}
        for p in partitioned:
            if {k:p[k] for k in target}!=target:errors.append(dict(partition=p['name']))
    summary=dict(status='passed' if not errors else 'failed',cases=len(cases),checks=checks,prefix_checks=prefix_checks,core_state_checks=core_checks,quality_checks=len(quality),minimum_quality_ratio=min((q['ratio'] for q in quality),default=None),calibration_checks=stat_checks,failures=len(errors),process_exit=r.returncode,seconds=round(time.monotonic()-start,3))
    (work/'results.json').write_text(json.dumps(dict(results=results,quality=quality,failures=errors),indent=2));(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));print(json.dumps(errors[:5]))
    raise SystemExit(bool(errors))
if __name__=='__main__':main()
