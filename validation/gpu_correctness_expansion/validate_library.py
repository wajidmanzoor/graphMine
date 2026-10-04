#!/usr/bin/env python3
"""Exercise the public CLI, including normalization, rich outputs and rejection."""
from validate_extra import *

CLI=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'library/build/graphmine'
CASES=[]
FOLDER=HERE/'datasets/library';FOLDER.mkdir(parents=True,exist_ok=True)


def invoke(key,operation,data,flags=(),check=lambda out: True,expected_failure=False):
    path=FOLDER/(key+'.json');write_json(path,data)
    rec,text=run_command('library_'+key,[CLI,'run',operation,'--graph',path,*flags],timeout=65)
    try:
        result=json.loads(text)
        if expected_failure:
            passed=rec['exit_code']!=0 and result.get('ok') is False and 'error' in result
        else:passed=rec['exit_code']==0 and result.get('ok') is True and check(result['output'])
        details={'result':result}
    except (ValueError,KeyError,IndexError,TypeError,AssertionError) as e:passed=False;details={'error':str(e)}
    CASES.append({'name':key,'passed':bool(passed),**rec,**details})
    if not passed:print('FAILED',key,text[-1200:],flush=True)


def component_check(data,mode,out):
    graph=nx.DiGraph() if data['graph']['directed'] else nx.Graph()
    graph.add_nodes_from(v['id'] for v in data['vertices']);graph.add_edges_from((e['source'],e['target']) for e in data['edges'])
    expected=list(nx.strongly_connected_components(graph) if graph.is_directed() and mode=='strongly_connected' else nx.connected_components(graph.to_undirected()))
    # ExternalId orders integer ids before string ids, then by value.
    order=lambda v:(isinstance(v,str),v)
    expected.sort(key=lambda c:order(min(c,key=order)))
    labels={v:i for i,c in enumerate(expected) for v in c}
    observed={row['vertex']:row['component'] for row in out['component_assignment']}
    return labels==observed and len(out['component_assignment'])==len(labels) and out['component_sizes']==list(map(len,expected)) and out['component_count']==len(expected)


def components():
    fixtures=[(key,canonical(n,edges,True)) for key,n,edges in scc_cases()]
    fixtures.append(('empty',canonical(0,[],True)))
    special=canonical(5,[(0,1),(1,0),(0,1),(2,2),(3,4)],True)
    special['graph'].update(allows_self_loops=True,allows_parallel_edges=True)
    mapping={0:'z',1:42,2:'a',3:-9,4:'0'}
    for vertex in special['vertices']:vertex['id']=mapping[vertex['id']]
    for edge in special['edges']:edge['source']=mapping[edge['source']];edge['target']=mapping[edge['target']]
    fixtures.append(('external_ids_loops_parallel',special))
    fixtures.append(('undirected',canonical(8,[(0,1),(1,2),(3,4)])))
    for key,data in fixtures:
        for mode in ['weakly_connected','strongly_connected']:
            invoke('components_'+key+'_'+mode,'connected-components',data,['--connectivity-mode',mode],lambda out:component_check(data,mode,out))


def flow_check(data,s,t,unit,out):
    graph=nx.DiGraph();graph.add_nodes_from(v['id'] for v in data['vertices'])
    original={e['id']:e for e in data['edges']};capacities={e['id']:1 if unit else e['weight'] for e in data['edges']}
    for edge in data['edges']:
        u,v=edge['source'],edge['target']
        if u!=v:graph.add_edge(u,v,capacity=graph.get_edge_data(u,v,{}).get('capacity',0)+capacities[edge['id']])
    expected=nx.maximum_flow_value(graph,s,t)
    flows={row['edge']:row['flow'] for row in out['flow_assignment']}
    if len(flows)!=len(out['flow_assignment']) or set(flows)!=set(original):return False
    balance={v:0 for v in graph}
    for key,flow in flows.items():
        if not 0<=flow<=capacities[key]:return False
        edge=original[key];balance[edge['source']]-=flow;balance[edge['target']]+=flow
    side=set(out['source_side_vertices'])
    cut={e['id'] for e in data['edges'] if e['source'] in side and e['target'] not in side}
    remaining=graph.copy()
    for key in cut:
        e=original[key]
        if remaining.has_edge(e['source'],e['target']):remaining.remove_edge(e['source'],e['target'])
    return (s in side and t not in side and len(side)==len(out['source_side_vertices']) and cut==set(out['min_cut_edges'])
            and expected==out['max_flow_value']==out['min_cut_value']==sum(capacities[k] for k in cut)==balance[t]==-balance[s]
            and all(value==0 for v,value in balance.items() if v not in [s,t]) and not nx.has_path(remaining,s,t) and out['optimal'])


def flows():
    for key,n,edges,s,t in flow_cases():
        data=canonical(n,edges,True)
        invoke('flow_'+key,'max-flow-min-cut',data,['--source',str(s),'--sink',str(t)],lambda out:flow_check(data,s,t,False,out))
    data=canonical(4,[(0,1,7),(0,1,5),(1,2,9),(2,3,8),(1,3,3),(0,0,999)],True)
    data['graph'].update(allows_self_loops=True,allows_parallel_edges=True)
    invoke('flow_parallel_loops','max-flow-min-cut',data,['--source','0','--sink','3'],lambda out:flow_check(data,0,3,False,out))
    for e in data['edges']:e.pop('weight')
    invoke('flow_unit','max-flow-min-cut',data,['--source','0','--sink','3','--unit-capacity'],lambda out:flow_check(data,0,3,True,out))
    data=canonical(3,[(2,0,1000000000)],True)
    invoke('flow_int_boundary','max-flow-min-cut',data,['--source','2','--sink','0'],lambda out:flow_check(data,2,0,False,out))


def assignment_graph(matrix):
    n=len(matrix);data=canonical(2*n,[(r,n+c,int(matrix[r,c])) for r in range(n) for c in range(n)])
    for v in data['vertices']:v['attributes']={'side':'left' if v['id']<n else 'right'}
    return data


def assignment_check(matrix,data,out):
    n=len(matrix);rows,cols=linear_sum_assignment(matrix);expected=int(matrix[rows,cols].sum());chosen=out['matching_edges'];original={e['id']:e for e in data['edges']}
    if len(chosen)!=n or len(set(chosen))!=n or any(e not in original for e in chosen):return False
    endpoints=[v for e in chosen for v in [original[e]['source'],original[e]['target']]]
    return len(set(endpoints))==2*n and sum(original[e]['weight'] for e in chosen)==expected==out['objective_value'] and out['matching_size']==n and out['feasible'] and out['optimal']


def assignments():
    for path in sorted((HERE/'datasets/hungarian').glob('*.txt')):
        numbers=list(map(int,path.read_text().split()));n=numbers[0];matrix=np.array(numbers[1:]).reshape((n,n));data=assignment_graph(matrix)
        invoke('assignment_'+path.stem,'linear-assignment',data,check=lambda out:assignment_check(matrix,data,out))
    matrix=np.empty((0,0),dtype=int);data=assignment_graph(matrix)
    invoke('assignment_empty','linear-assignment',data,check=lambda out:assignment_check(matrix,data,out))
    matrix=np.array([[4,1],[0,3]]);data=assignment_graph(matrix);data['graph']['allows_parallel_edges']=True
    data['edges'].append({'id':'expensive','source':2,'target':0,'weight':5})
    invoke('assignment_parallel','linear-assignment',data,check=lambda out:assignment_check(matrix,data,out))


def closure():
    graphs=list(scc_cases())[:4]+[('medium_cycle',128,[(v,(v+1)%128) for v in range(128)]),('empty',0,[])]
    for key,n,edges in graphs:
        data=canonical(n,edges,True);graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_edges_from(edges)
        expected={(u,v) for u in graph for v in {u}|nx.descendants(graph,u)}
        def check(out):
            pairs=[(p['source'],p['target']) for p in out['transitive_closure_edges']]
            return set(pairs)==expected and len(pairs)==len(expected)==out['reachable_pair_count'] and out['complete']
        invoke('closure_'+key,'transitive-closure',data,check=check)


def butterflies():
    reference=json.loads((HERE/'results/graphminer_butterfly.json').read_text())
    for case in reference['cases']:
        data=json.loads((HERE/'datasets/graphminer_butterfly'/(case['name']+'.json')).read_text())
        graph=nx.Graph();graph.add_nodes_from(v['id'] for v in data['vertices']);graph.add_edges_from((e['source'],e['target']) for e in data['edges'])
        colors=nx.bipartite.color(graph)
        for v in data['vertices']:v['attributes']={'side':'left' if colors[v['id']] else 'right'}
        invoke('butterfly_'+case['name'],'butterfly-counting',data,check=lambda out:out['butterfly_count']==case['expected'] and out['complete'])
    invoke('butterfly_empty','butterfly-counting',canonical(0,[]),check=lambda out:out['butterfly_count']==0 and out['complete'])


def rejections():
    flow=canonical(2,[(0,1,1)],True)
    for key,cost in [('negative',-1),('fraction',0.5),('overflow',1000000001)]:
        data=json.loads(json.dumps(flow));data['edges'][0]['weight']=cost
        invoke('reject_flow_'+key,'max-flow-min-cut',data,['--source','0','--sink','1'],expected_failure=True)
    invoke('reject_flow_same_terminal','max-flow-min-cut',flow,['--source','0','--sink','0'],expected_failure=True)
    invoke('reject_flow_missing_terminal','max-flow-min-cut',flow,['--source','0','--sink','99'],expected_failure=True)
    assignment=assignment_graph(np.ones((2,2),dtype=int))
    for key,mutate in [('missing_edge',lambda d:d['edges'].pop()),('negative_cost',lambda d:d['edges'][0].update(weight=-1)),('missing_side',lambda d:d['vertices'][0].pop('attributes'))]:
        data=json.loads(json.dumps(assignment));mutate(data);invoke('reject_assignment_'+key,'linear-assignment',data,expected_failure=True)
    data=assignment_graph(np.ones((65,65),dtype=int));invoke('reject_assignment_size','linear-assignment',data,expected_failure=True)
    invoke('reject_closure_size','transitive-closure',canonical(1025,[],True),expected_failure=True)
    invoke('reject_closure_direction','transitive-closure',canonical(2,[(0,1)]),expected_failure=True)
    invoke('reject_butterfly_side','butterfly-counting',canonical(4,[(0,1),(1,2),(2,3),(3,0)]),expected_failure=True)
    for flags,key in [(['--device','0,1'],'multiple_devices'),(['--timeout-seconds','0'],'timeout_zero'),(['--backend','unknown'],'backend'),(['--worker-directory',str(FOLDER/'missing')],'missing_worker')]:
        invoke('reject_'+key,'connected-components',flow,['--connectivity-mode','strongly_connected',*flags],expected_failure=True)
    fake=FOLDER/'fake';fake.mkdir(exist_ok=True);worker=fake/'graphmine-worker-ecl-scc'
    for key,script,flags in [('worker_failure','#!/bin/sh\nexit 17\n',[]),('worker_timeout','#!/bin/sh\nsleep 10\n',['--timeout-seconds','1']),('worker_malformed','#!/bin/sh\necho GRAPHMINE_COMPONENTS 999\n',[])]:
        worker.write_text(script);worker.chmod(0o700)
        invoke('reject_'+key,'connected-components',flow,['--connectivity-mode','strongly_connected','--worker-directory',str(fake),*flags],expected_failure=True)


if __name__=='__main__':
    components();flows();assignments();closure();butterflies();rejections()
    save('library_expansion',CASES)
    sys.exit(0 if all(c['passed'] for c in CASES) else 1)
