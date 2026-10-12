#!/usr/bin/env python3
"""Independent acceptance/rejection checks at native parameter boundaries."""
import itertools
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

from validate import graph

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent/"results/boundaries"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--binary",type=Path,default=ROOT/"library/build/graphmine")
    args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True);rows=[]
    binary=args.binary.resolve()
    binary_hash=hashlib.sha256(binary.read_bytes()).hexdigest()
    def run(name,op,backend,data,flags=(),check=None,reject=False,query=None):
        folder=WORK/name;folder.mkdir(exist_ok=True)
        path=folder/"graph.json";path.write_text(json.dumps(data))
        command=[str(binary),"run",op,"--backend",backend,"--graph",str(path),*map(str,flags)]
        if query is not None:
            path=folder/"query.json";path.write_text(json.dumps(query));command += ["--query-graph",str(path)]
        started=time.time();record={"id":name,"operation":op,"backend":backend,"command":command,"expected_rejection":reject}
        try:
            proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                                  env={**os.environ,"CUDA_VISIBLE_DEVICES":"0","OMP_NUM_THREADS":"2"},start_new_session=True)
            try:stdout,stderr=proc.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate();raise RuntimeError("timeout")
            (folder/"stdout.json").write_text(stdout);(folder/"stderr.log").write_text(stderr)
            payload=json.loads(stdout);record.update(exit_code=proc.returncode)
            if reject:
                assert not payload.get("ok") and proc.returncode!=0,payload
                assert payload.get("error",{}).get("code") in ["unsupported","invalid_argument","invalid_input"],payload
            else:
                assert payload.get("ok") and proc.returncode==0,payload
                if check:check(payload["output"])
            record["passed"]=True
        except Exception as error:record.update(passed=False,error=str(error))
        record["seconds"]=time.time()-started;rows.append(record)
        (WORK/"results.json").write_text(json.dumps(rows,indent=2)+"\n")
        print(name,"PASS" if record["passed"] else record.get("error"),flush=True)
    def equals(out,name,value):
        assert out[name]==value,(name,out[name],value)
    complete=lambda n:graph(n,list(itertools.combinations(range(n),2)))
    for backend,k in [("kcgpu",10),("gamma",7),("graphset",6),("auto",10)]:
        run(f"{backend}-highest","k-cliques",backend,complete(16),["--k",k],lambda o:equals(o,"count",math.comb(16,k)))
        run(f"{backend}-too-high","k-cliques",backend,complete(16),["--k",k+1],reject=True)
    for n,k in [(16,6),(16,8),(16,10),(16,14),(16,16),(20,10),(4,2147483647)]:
        def density_check(o):
            equals(o,"clique_order",k)
            if k>n:
                equals(o,"clique_count",0);equals(o,"density",0);assert o["vertices"]
            else:
                equals(o,"clique_count",math.comb(n,k));assert math.isclose(o["density"],math.comb(n,k)/n,rel_tol=1e-12)
        run(f"cds-K{n}-k{k}","densest-subgraph","cds",complete(n),["--clique-order",k],density_check)
    for n in [405,514,1001]:
        run(f"kcgpu-pivot-depth-{n}","k-cliques","kcgpu",complete(n),["--k",3],lambda o:equals(o,"count",math.comb(n,3)))
    run("kcgpu-forward-degree-too-large","k-cliques","kcgpu",complete(1002),["--k",3],reject=True)
    run("kcgpu-count-bound-overflow","k-cliques","kcgpu",complete(514),["--k",10],reject=True)
    for backend in ["parallel-louvain","parallel-leiden","parallel-leiden-plus","auto"]:
        for resolution in [0,.01,8,16,1000]:
            data=graph(7,[(i,i+1) for i in range(6)])
            def modularity_check(o):
                groups={}
                # The exact field layout is the public CLI's community result.
                labels=o["assignment_by_vertex"]
                for row in labels:groups.setdefault(row["community"],set()).add(row["vertex"])
                edges=[(i,i+1) for i in range(6)];degree={i:(1 if i in [0,6] else 2) for i in range(7)}
                expected=sum(sum(a in s and b in s for a,b in edges)/6-resolution*(sum(degree[v] for v in s)/12)**2 for s in groups.values())
                assert math.isclose(o["modularity"],expected,rel_tol=1e-7,abs_tol=1e-7),(o,expected)
            run(f"{backend}-resolution-{resolution}","community-detection",backend,data,["--resolution",resolution],modularity_check)
    for spread in [1,47,48]:
        run(f"wetric-spread-{spread}","triangle-counting","wetric",complete(8),["--wetric-spread",spread],lambda o:equals(o,"global_triangle_count",56),reject=spread==48)
    for length in [32,64,96,128,192]:
        run(f"wetric-length-{length}","triangle-counting","wetric",complete(8),["--wetric-adjacency-matrix-length",length],lambda o:equals(o,"global_triangle_count",56),reject=length%64!=0)
    for n in [2,16,17]:
        path=graph(n,[(i,i+1) for i in range(n-1)])
        run(f"gmatch-query-{n}","subgraph-isomorphism","gmatch",path,["--ignore-vertex-labels","--initial-match-capacity",1],lambda o:equals(o,"count",2),reject=n>16,query=path)
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==binary_hash,"Binary changed during boundary checks"
    summary={"binary_sha256":binary_hash,"cases":len(rows),"passed":sum(r["passed"] for r in rows),"failed":sum(not r["passed"] for r in rows)}
    (WORK/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(summary)


if __name__=="__main__":main()
