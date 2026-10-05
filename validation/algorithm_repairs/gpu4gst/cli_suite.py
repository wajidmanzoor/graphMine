#!/usr/bin/env python3
import argparse,copy,hashlib,json,os,re,struct,subprocess
from pathlib import Path
from validate import case,write_case,check_witness

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--gpu',default='1');args=ap.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True);binary=str(args.binary.resolve())
    env={**os.environ,'CUDA_VISIBLE_DEVICES':args.gpu,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1:protect_shadow_gap=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
    base=case('base',4,[(0,1,2),(1,2,3),(2,3,4),(0,3,20)],[[0],[3],[1,2],[]],[[0,1],[0,2],[0,3],[1,1],[1,0]])
    results=[];checks=0
    def invoke(name,words,success,expected=None,c=None,first=0,custom_env=None):
        nonlocal checks
        r=subprocess.run([binary,*words],capture_output=True,text=True,timeout=30,env=custom_env or env)
        text=r.stdout+r.stderr;(work/(name+'.log')).write_text(text)
        assert (r.returncode==0)==success,(name,r.returncode,text[-2000:])
        assert 'AddressSanitizer' not in text and 'runtime error:' not in text,(name,text[-2000:])
        if success and expected is not None:
            answers=[None if s=='infeasible' else int(s) for s in re.findall(r'^min cost (\S+)$',text,re.M)]
            assert answers==expected,(name,answers,expected)
            trees={w['query']:w for w in [json.loads(line[8:]) for line in text.splitlines() if line.startswith('witness ')]}
            if '--witness' in words:
                for q,answer in enumerate(expected,first):
                    if answer is not None:check_witness(c,q,answer,trees[q])
            checks+=len(answers)
        if not success:assert not re.search(r'^min cost \d+',text,re.M),(name,text)
        results.append(dict(name=name,exit=r.returncode,kind='positive' if success else 'rejection',arguments=words))
    def fixture(name,c=base):
        folder=work/name;write_case(folder,c)
        return folder,['unused',str(folder),'graph',str(len(c['queries'][0])),'0',str(len(c['queries'])-1)]
    invoke('help',['--help'],True)
    p,words=fixture('space in path');invoke('space-path',words+['--witness'],True,base['expected'],base)
    invoke('range',words[:4]+['1','3','--witness'],True,base['expected'][1:4],base,1)
    invoke('legacy-cost-only',words,True,base['expected'],base)
    (p/'graph.g').write_text('\n g1: 0 0 \r\n g2: 3\t\n g3: 2 1 2\n g4:\n')
    (p/'graph2.csv').write_text('\n0\t1\n 0 2 \r\n0 3\n1 1\n1 0\n\n')
    invoke('whitespace-duplicates',words+['--witness'],True,base['expected'],base)
    positive_cases=[case('no-vertices',0,[],[[]],[[0]]),case('no-edges',1,[],[[0],[]],[[0],[1],[0]]),
        case('single-group',4,[(0,1,8),(1,2,0)],[[1],[3],[1,3]],[[0],[1],[2]]),
        case('cost-over-int32',3,[(0,1,2147483647),(1,2,17)],[[0],[2]],[[0,1]]),
        case('cost-over-float53',3,[(0,1,(1<<53)+1),(1,2,9)],[[0],[2]],[[0,1]])]
    for c in positive_cases:
        p,words=fixture(c['name'],c);invoke(c['name'],words+['--witness'],True,c['expected'],c)
    p,valid=fixture('valid-for-bad-cli')
    bad_args={
        'no-args':[], 'too-few':['unused'], 'too-many':valid+['extra'], 'unknown-option':valid+['--tree'],
        'groups-zero':valid[:3]+['0']+valid[4:], 'groups17':valid[:3]+['17']+valid[4:],
        'groups-negative':valid[:3]+['-1']+valid[4:], 'groups-junk':valid[:3]+['2x']+valid[4:],
        'groups-overflow':valid[:3]+['999999999999999999999']+valid[4:],
        'first-negative':valid[:4]+['-1','0'], 'first-junk':valid[:4]+['1x','2'],
        'range-reversed':valid[:4]+['2','1'], 'range-too-far':valid[:4]+['0','99'],
        'empty-stem':valid[:2]+['']+valid[3:], 'dot-stem':valid[:2]+['..']+valid[3:],
        'slash-stem':valid[:2]+['../graph']+valid[3:], 'missing-directory':['unused',str(work/'missing'),'graph','2','0','0']}
    for name,words in bad_args.items():invoke(name,words,False)
    def q64(values):return struct.pack('<'+'q'*len(values),*values)
    mutations={
        'missing-offset':('graph_beg_pos.bin',None), 'missing-dest':('graph_csr.bin',None),'missing-weight':('graph_weight.bin',None),
        'short-offset':('graph_beg_pos.bin',b'123'), 'short-dest':('graph_csr.bin',b'123'), 'short-weight':('graph_weight.bin',b'123'),
        'empty-offset':('graph_beg_pos.bin',b''), 'offset-first':('graph_beg_pos.bin',q64([1,2,4,6,8])),
        'offset-last':('graph_beg_pos.bin',q64([0,2,4,6,7])), 'offset-decreasing':('graph_beg_pos.bin',q64([0,3,2,6,8])),
        'offset-negative':('graph_beg_pos.bin',q64([0,-1,4,6,8])), 'offset-too-large':('graph_beg_pos.bin',q64([0,2,40,6,8])),
        'weight-length':('graph_weight.bin',q64([1])), 'dest-negative':('graph_csr.bin',q64([-1]*8)), 'dest-too-large':('graph_csr.bin',q64([4]*8)),
        'weight-negative':('graph_weight.bin',q64([-1]*8)), 'weight-infinity':('graph_weight.bin',q64([1<<58]*8)),
        'tree-cost-capacity':('graph_weight.bin',q64([(1<<58)//2]*8)),
        'missing-groups':('graph.g',None),'empty-groups':('graph.g',b''),'group-no-colon':('graph.g',b'g1 0\n'),
        'group-bad-prefix':('graph.g',b'h1: 0\n'), 'group-gap':('graph.g',b'g2: 0\n'), 'group-duplicate-id':('graph.g',b'g1: 0\ng1: 1\n'),
        'group-bad-id':('graph.g',b'g1x: 0\n'), 'group-negative-vertex':('graph.g',b'g1: -1\n'), 'group-large-vertex':('graph.g',b'g1: 4\n'),
        'group-bad-vertex':('graph.g',b'g1: 0x\n'),'missing-queries':('graph2.csv',None),'empty-queries':('graph2.csv',b'\n\t\n'),
        'query-bad-token':('graph2.csv',b'0 x\n'), 'query-negative':('graph2.csv',b'0 -1\n'), 'query-too-large':('graph2.csv',b'0 4\n'),
        'query-too-short':('graph2.csv',b'0\n'), 'query-too-long':('graph2.csv',b'0 1 2\n'),
    }
    for name,(file,data) in mutations.items():
        folder,words=fixture(name)
        target=folder/file
        if data is None:target.unlink()
        else:target.write_bytes(data)
        words[-1]='0';invoke(name,words,False)
    for name in ['asymmetric-weight','asymmetric-multiplicity','asymmetric-edge']:
        folder,words=fixture(name)
        if name=='asymmetric-weight':
            file=folder/'graph_weight.bin';values=list(struct.unpack('<8q',file.read_bytes()));values[0]+=1;file.write_bytes(q64(values))
        elif name=='asymmetric-edge':
            file=folder/'graph_csr.bin';values=list(struct.unpack('<8q',file.read_bytes()));values[0]=2;file.write_bytes(q64(values))
        else:
            (folder/'graph_beg_pos.bin').write_bytes(q64([0,2,3,3,3]));(folder/'graph_csr.bin').write_bytes(q64([1,1,0]));(folder/'graph_weight.bin').write_bytes(q64([1,1,1]))
        invoke(name,words,False)
    folder,words=fixture('blocked-result-directory');(folder/'result').write_text('not a directory');invoke('blocked-result-directory',words,False)
    invoke('no-visible-gpu',valid,False,custom_env={**env,'CUDA_VISIBLE_DEVICES':''})
    summary=dict(status='passed',positive_checks=checks,positive_invocations=sum(r['kind']=='positive' for r in results),rejections=sum(r['kind']=='rejection' for r in results),failures=0,binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
    (work/'results.json').write_text(json.dumps(results,indent=2)+'\n');(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
