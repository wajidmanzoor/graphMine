#!/usr/bin/env python3
"""Additional independent oracles for expansion candidates."""
import itertools
import math
import sys
from run import *


def save(name,cases,limitations=()):
    failures=[c for c in cases if not c['passed']]
    result={'backend':name,'seed':SEED,'status':'correctness_fail' if failures else ('partial_pass' if limitations else 'pass'),
            'passed':len(cases)-len(failures),'total':len(cases),'cases':cases,'limitations':list(limitations)}
    write_json(HERE/'results'/(name+'.json'),result)
    print(name,result['status'],str(result['passed'])+'/'+str(result['total']),flush=True)
    for c in failures:print('FAILED',c['name'],c.get('error'),c.get('expected'),c.get('observed'),flush=True)


def canonical(n,edges,directed=False):
    return {'graph':{'id':'validation','directed':directed,'allows_self_loops':False,'allows_parallel_edges':False},
            'vertices':[{'id':v} for v in range(n)],
            'edges':[{'id':i,'source':e[0],'target':e[1],**({'weight':e[2]} if len(e)>2 else {})} for i,e in enumerate(edges)]}


def reachability():
    name='gdlog_tc';folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    for key,n,edges in list(scc_cases())[:4]+[(f'random_{k}',32,[(u,v) for u in range(32) for v in range(32) if u!=v and random.Random(SEED+k+u*32+v).random()<0.08]) for k in range(4)]:
        graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_edges_from(edges)
        expected=sorted((u,v) for u in range(n) for v in {u}|nx.descendants(graph,u))
        # Canonical reachability includes length-zero paths, including isolated vertices.
        path=folder/(key+'.tsv');path.write_text(''.join(f'{u}\t{v}\n' for u,v in sorted(set(edges)|{(v,v) for v in range(n)})))
        rec,text=run_command(name+'_'+key,[HERE/'bin'/name,path,'1'],timeout=40)
        try:
            output=text.split('Relation tuples >>> validation\n')[1].split('end <<<')[0]
            count=int(re.search(r'Total tuples counts:\s+(\d+)',output)[1])
            observed=sorted(tuple(map(int,m)) for m in re.findall(r'^(\d+)\s+(\d+)\s*$',output,re.M))
            passed=rec['exit_code']==0 and count==len(observed)==len(set(observed)) and observed==expected
            details={'expected':expected,'observed':observed,'reported_count':count}
        except (IndexError,ValueError,TypeError) as e:passed=False;details={'error':str(e),'expected':expected}
        cases.append({'name':key,'passed':passed,**rec,**details})
    save(name,cases)


def butterflies():
    name='graphminer_butterfly';folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    pattern=folder/'square.json';write_json(pattern,canonical(4,[(0,1),(1,2),(2,3),(3,0)]))
    graphs=[('single',2,2,[(u,2+v) for u in range(2) for v in range(2)]),
            ('star',1,6,[(0,v) for v in range(1,7)]),('isolated',3,3,[]),
            ('complete',5,7,[(u,5+v) for u in range(5) for v in range(7)])]
    for k in range(8):
        rng=random.Random(SEED+k);left,right=(5,7) if k<4 else (32,40)
        graphs.append((f'random_{k}',left,right,[(u,left+v) for u in range(left) for v in range(right) if rng.random()<0.25]))
    for key,left,right,edges in graphs:
        neighbors={u:{v for a,v in edges if a==u} for u in range(left)}
        expected=sum(math.comb(len(neighbors[u]&neighbors[v]),2) for u,v in itertools.combinations(range(left),2))
        path=folder/(key+'.json');write_json(path,canonical(left+right,edges))
        output=folder/(key+'.result.json')
        rec,text=run_command(name+'_'+key,[ROOT/'library/build/graphmine','run','graph-motifs','--graph',path,'--motif',pattern,'--backend','graphminer','--induced','--output',output],timeout=40)
        try:
            result=json.loads(output.read_text());motif=result['output']['motifs'][0]
            observed=motif['count']
            passed=rec['exit_code']==0 and result['ok'] and observed==expected
            details={'expected':expected,'observed':observed,'provenance':result.get('provenance')}
        except (OSError,ValueError,KeyError,IndexError) as e:passed=False;details={'error':str(e),'expected':expected}
        cases.append({'name':key,'passed':passed,**rec,**details})
    save(name,cases,['Global exact butterfly count only; alpha/beta-core and participation modes are not validated by this suite.'])


def influence(name):
    folder=HERE/'datasets'/name;folder.mkdir(parents=True,exist_ok=True);cases=[]
    graphs=[]
    for n in [8,64]:
        graphs.extend([(f'star_{n}',n,[(0,v,1.0) for v in range(1,n)],1),
                       (f'chain_{n}',n,[(v,v+1,1.0) for v in range(n-1)],1),
                       (f'two_stars_{n}',n,[(0,v,1.0) for v in range(1,n//2)]+[(n//2,v,1.0) for v in range(n//2+1,n)],2)])
    for key,n,edges,k in graphs:
        graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_weighted_edges_from(edges,weight='probability')
        reach={u:{u}|nx.descendants(graph,u) for u in graph}
        optimum=max(len(set().union(*(reach[v] for v in seeds))) for seeds in itertools.combinations(range(n),k))
        path=folder/(key+'.txt');path.write_text((f'{n} {len(edges)}\n' if name=='superfuser' else '')+''.join(f'{u} {v} {p}\n' for u,v,p in edges))
        for repetition in range(3):
            command=[HERE/'bin'/name,'-g','1','-K',k,'-R','256',path] if name=='superfuser' else [HERE/'bin'/name,path,k,0.2,1]
            rec,text=run_command(name+'_'+key+'_'+str(repetition),command,timeout=40)
            try:
                if name=='gim':
                    chosen=list(map(int,text.split('List of nodes in the seed set:')[1].splitlines()[0].split()))
                else:
                    lines=re.findall(r'^(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+).*$',text,re.M)
                    chosen=[int(row[0]) for row in lines][-k:]
                feasible=len(chosen)==k and len(set(chosen))==k and all(v in reach for v in chosen)
                actual=len(set().union(*(reach[v] for v in chosen))) if feasible else None
                passed=rec['exit_code']==0 and feasible and actual>=0.63*optimum
                details={'expected_optimum':optimum,'observed_exact_spread':actual,'seeds':chosen,'minimum_quality_ratio':0.63}
            except (IndexError,ValueError) as e:passed=False;details={'error':str(e)}
            cases.append({'name':key+'_'+str(repetition),'passed':passed,**rec,**details})
    save(name,cases,['Deterministic probability-one independent-cascade fixtures only. General probabilities, linear-threshold behavior, spread-estimator calibration and the requested failure probability are not certified.'])


if __name__=='__main__':
    for name in sys.argv[1:]:
        if name=='gdlog_tc':reachability()
        elif name=='graphminer_butterfly':butterflies()
        elif name in ['gim','superfuser']:influence(name)
        else:raise ValueError(name)
