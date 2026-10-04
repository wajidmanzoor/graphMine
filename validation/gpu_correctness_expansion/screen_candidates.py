#!/usr/bin/env python3
"""Bounded additional screening; passing a scalar check does not certify a contract."""
from validate_extra import *


def wbpr():
    name='wbpr';folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    for key,n,edges,s,t in list(flow_cases())[:6]:
        graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_weighted_edges_from(edges,weight='capacity')
        expected=nx.maximum_flow_value(graph,s,t)
        path=folder/(key+'.dimacs')
        path.write_text(f'p max {n} {len(edges)}\nn {s+1} s\nn {t+1} t\n'+''.join(f'a {u+1} {v+1} {c}\n' for u,v,c in edges))
        for algorithm in [0,1]:
            rec,text=run_command(name+'_'+key+'_'+str(algorithm),[HERE/'adapted/wbpr/maxflow','-v','2','-f',path,'-a',algorithm],timeout=15)
            match=re.search(r'parallel implementation is\s+(-?\d+)',text)
            observed=int(match[1]) if match else None
            cases.append({'name':key+'_'+str(algorithm),'passed':rec['exit_code']==0 and observed==expected,'expected':expected,'observed':observed,**rec})
    save(name,cases,['Scalar value screening only: flow conservation and returned cut not certified. The license found in maxflow-bcsr2 does not establish the license of maxflow-cuda.'])


def gamma():
    name='gamma_butterfly';folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    query=folder/'square.query';query.write_text('4\n0 0 0 0\n2 1 3\n2 0 2\n2 1 3\n2 0 2\n0\n0\n0\n0\n')
    reference=json.loads((HERE/'results/graphminer_butterfly.json').read_text())
    for ref in reference['cases']:
        key=ref['name'];data=json.loads((HERE/'datasets/graphminer_butterfly'/(key+'.json')).read_text());n=len(data['vertices'])
        arcs=sorted([(e['source'],e['target']) for e in data['edges']]+[(e['target'],e['source']) for e in data['edges']])
        offsets=[0]
        for u in range(n):offsets.append(offsets[-1]+sum(a==u for a,b in arcs))
        path=folder/key
        path.with_suffix('.col').write_bytes(struct.pack('<I',n)+struct.pack('<'+'Q'*(n+1),*offsets))
        path.with_suffix('.dst').write_bytes(struct.pack('<Q',len(arcs))+struct.pack('<'+'I'*len(arcs),*(v for u,v in arcs)))
        path.with_suffix('.vlabel').write_bytes(struct.pack('<I',n)+bytes(n))
        rec,text=run_command(name+'_'+key,[HERE/'bin'/name,path,query,'0','debug'],timeout=15)
        matches=re.findall(r'valid emb number is (\d+)',text)
        embeddings=int(matches[-1]) if matches else None
        actual=embeddings//8 if embeddings is not None and embeddings%8==0 else None
        cases.append({'name':key,'passed':rec['exit_code']==0 and actual==ref['expected'],'expected':ref['expected'],'observed':actual,'raw_embeddings':embeddings,**rec})
    save(name,cases,['Global count only. No explicit license detected.'])


def gpusteiner():
    name='gpusteiner';folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    graphs=[('path',6,[(i,i+1,1) for i in range(5)],[0,5]),('star',8,[(0,i,i) for i in range(1,8)],[1,3,7])]
    for k in range(6):
        rng=random.Random(SEED+k)
        n=9 if k<3 else 128
        edges=[(i,rng.randrange(i),rng.randrange(1,10)) for i in range(1,n)]
        graphs.append((f'tree_{k}',n,edges,rng.sample(range(n),4)))
    for key,n,edges,terminals in graphs:
        g=nx.Graph();g.add_weighted_edges_from(edges)
        required=set()
        for t in terminals[1:]:
            path=nx.shortest_path(g,terminals[0],t)
            required.update(tuple(sorted(e)) for e in zip(path,path[1:]))
        expected=sum(g[u][v]['weight'] for u,v in required)
        arcs=sorted(edges+[(v,u,w) for u,v,w in edges]);offset=0;rows=[]
        for u in range(n):
            degree=sum(a==u for a,b,w in arcs);rows.append(f'{offset} {degree}');offset+=degree
        path=folder/(key+'.txt');path.write_text(f'{n}\n'+'\n'.join(rows)+f'\n0\n{len(arcs)}\n'+''.join(f'{v} {w}\n' for u,v,w in arcs)+str(len(terminals))+'\n'+' '.join(map(str,terminals))+'\n')
        rec,text=run_command(name+'_'+key,[HERE/'bin'/name,'16','-v'],stdin_path=path,timeout=20)
        match=re.search(r'VALUE (\d+)',text);actual=int(match[1]) if match else None
        # Upstream prints one-based tree endpoints; all these fixtures have a unique optimal subtree.
        chosen={tuple(sorted((int(u)-1,int(v)-1))) for u,v in re.findall(r'^(\d+) (\d+)\s*$',text,re.M)}
        feasible=chosen==required
        cases.append({'name':key,'passed':rec['exit_code']==0 and actual==expected and feasible,'expected':expected,'observed':actual,'expected_edges':sorted(required),'observed_edges':sorted(chosen),'feasible':feasible,**rec})
    save(name,cases,['Only ordinary Steiner trees (singleton groups), on tree inputs. General group constraints and approximation certificates are unsupported by this executable.'])


if __name__=='__main__':
    for name in sys.argv[1:]:globals()[name]()
