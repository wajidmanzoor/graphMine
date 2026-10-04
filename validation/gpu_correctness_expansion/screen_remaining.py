#!/usr/bin/env python3
"""Limited screening of approximate/contract-mismatched remaining artifacts."""
import csv
from validate_extra import *


def kpar():
    name='kpar';base=HERE/'datasets/kpar';cwd=base/'run';cwd.mkdir(parents=True,exist_ok=True);cases=[]
    for n in [16,64]:
        key='cycle_'+str(n);folder=base/'data'/key;folder.mkdir(parents=True,exist_ok=True)
        (folder/'attribute.txt').write_text(f'n={n}\nm={n}\n');(folder/'graph.txt').write_text(''.join(f'{u} {(u+1)%n}\n' for u in range(n)))
        (folder/'queries.txt').write_text('0\n')
        rec,text=run_command(name+'_'+key+'_index',[HERE/'bin/kpar','indexing','--dataset',key,'--epsilon','0.5'],cwd=cwd,timeout=20)
        if rec['exit_code']:
            cases.append({'name':key,'passed':False,'stage':'index',**rec});continue
        rec,text=run_command(name+'_'+key+'_query',[HERE/'bin/kpar','query','--gpu_idx','0','--dataset',key,'--query_size','1','--epsilon','0.5','--k','4'],cwd=cwd,timeout=20)
        try:
            values=[(int(row.split()[0]),float(row.split()[1])) for row in (folder/'result/0.txt').read_text().splitlines()]
            expected=[(u,0.2*0.8**u/(1-0.8**n)) for u in range(4)]
            # epsilon=.5 is the requested score tolerance; also require exactly k rows.
            passed=rec['exit_code']==0 and len(values)==4 and [v for v,s in values]==list(range(4)) and all(abs(score-exact)<=0.5*exact for (_,score),(_,exact) in zip(values,expected))
            details={'observed':values,'expected':expected}
        except (OSError,ValueError) as e:passed=False;details={'error':str(e)}
        cases.append({'name':key,'passed':passed,**rec,**details})
    save(name,cases,['Cycle top-4 personalized PageRank only; restart .2 fixed by artifact. This small screen does not certify stochastic failure bounds or general weighted/personalized inputs.'])


def signed(name):
    folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    for key,edges in [('positive_triangle',[(0,1,1),(1,2,1),(0,2,1)]),('balanced_triangle',[(0,1,-1),(1,2,-1),(0,2,1)]),('unbalanced_triangle',[(0,1,-1),(1,2,1),(0,2,1)])]:
        path=folder/(key+'.csv');path.write_text('source,target,sign\n'+''.join(f'{u},{v},{s}\n' for u,v,s in edges))
        prefix=folder/(key+'.out');rec,text=run_command(name+'_'+key,[HERE/'bin'/name,path,'32',prefix],timeout=20)
        outputs=list(folder.glob(key+'.out*'));headers={p.name:p.read_text().splitlines()[0] for p in outputs if p.is_file() and p.stat().st_size}
        cases.append({'name':key,'passed':rec['exit_code']==0 and bool(headers),'smoke_test_only':True,'output_headers':headers,**rec})
    save(name,cases,['Execution/output smoke checks only, not mathematical correctness. Executables emit tree-sampling statistics; no returned partition, frustrated-edge set, minimum-frustration value or optimality certificate. Not promoted.'])


def gst_vlsi():
    name='gst_vlsi';cases=[]
    for n in [8,64]:
        folder=HERE/'datasets'/name/str(n);folder.mkdir(parents=True,exist_ok=True);path=folder/'graph.txt'
        path.write_text(f'{n} {n-1}\n'+''.join(f'{i} {i+1} 1\n' for i in range(1,n))+f'{n}\n'+' '.join(str(v) for v in range(1,n+1))+'\n2\n1 1\n1 '+str(n)+'\n')
        rec,text=run_command(name+'_'+str(n),[HERE/'bin'/name,'-o'],stdin_path=path,cwd=folder,timeout=20)
        output=(folder/'debug.out').read_text(errors='replace') if (folder/'debug.out').exists() else ''
        match=re.search(r'Final Graph Cost:\s*(\d+)',output);observed=int(match[1]) if match else None
        cases.append({'name':'path_'+str(n),'passed':rec['exit_code']==0 and observed==n-1,'observed':observed,'expected':n-1,'solution_log':str((folder/'debug.out').relative_to(HERE)),**rec})
    save(name,cases,['Only two singleton groups on a path; no general group coverage/approximation certificate validation. No explicit license detected.'])


def gpu4gst():
    name='gpu4gst';code=source('27_group_steiner_tree','2025_gpu4gst')/'code/TrimCDP-WB'
    target=adapt(code/'src/GSTnonHop.cu','gpu4gst.cu',lambda t:replace_once(replace_once(t,'cudaSetDevice(3);','cudaSetDevice(0);'),'for (int i = 0; i < 4; i++)','for (int i = 0; i < 1; i++)'))
    rec,text=run_command('gpu4gst_device_adapter',['nvcc','-O2','-arch=sm_89','-std=c++17','--extended-lambda',target,'-I',code/'include','-o',HERE/'bin/gpu4gst_device0'],kind='builds',timeout=90)
    if rec['exit_code']:print(text[-1000:]);return
    cases=[]
    for n in [8,64]:
        folder=HERE/'datasets'/name/str(n);(folder/'result').mkdir(parents=True,exist_ok=True);arcs=sorted([(i,i+1,1) for i in range(n-1)]+[(i+1,i,1) for i in range(n-1)]);offset=[0]
        for u in range(n):offset.append(offset[-1]+sum(a==u for a,b,w in arcs))
        for suffix,values in [('beg_pos',offset),('csr',[v for u,v,w in arcs]),('weight',[w for u,v,w in arcs])]:
            (folder/('graph_'+suffix+'.bin')).write_bytes(struct.pack('<'+'q'*len(values),*values))
        (folder/'graph.g').write_text(f'g1: 0\ng2: {n-1}\n');(folder/'graph2.csv').write_text('0 1\n')
        rec,text=run_command(name+'_'+str(n),[HERE/'bin/gpu4gst_device0','unused',str(folder)+'/', 'graph','2','0','0'],timeout=20)
        match=re.search(r'min cost (\d+)',text);observed=int(match[1]) if match else None
        cases.append({'name':'path_'+str(n),'passed':rec['exit_code']==0 and observed==n-1,'observed':observed,'expected':n-1,**rec})
    save(name,cases,['Scalar cost only on two singleton groups; executable returns no tree/edge witness. General group constraints and exactness not certified. No explicit license detected.'])


if __name__=='__main__':
    for name in sys.argv[1:]:
        if name in ['graphbplus','ecl_sgb']:signed(name)
        else:globals()[name]()
