#!/usr/bin/env python3
"""Reproducible differential CLI sweep, one isolated subprocess per GPU case.

Exact operations use independent exhaustive references. Community partitions
are checked for coverage and their actual modularity, not global optimality.
PPR error and heuristic influence quality are measurements, not certificates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))
from graphmine_agent.learning.catalog_grade import grade_output


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph(n, pairs, *, directed=False, left=None, weights=None, times=None, mixed=False):
    ids = [(-7 if i == 0 else "0" if i == 1 else 0 if i == 2 else f"v {i}")
           if mixed else i for i in range(n)]
    result = {"graph": {"id": "sweep", "directed": directed,
                        "allows_self_loops": False, "allows_parallel_edges": times is not None},
              "vertices": [{"id": v} for v in ids], "edges": []}
    if left is not None:
        for i, v in enumerate(result["vertices"]):
            v["attributes"] = {"side": "left" if i < left else "right"}
    for i, (a, b) in enumerate(pairs):
        e = {"id": f"e{i}", "source": ids[a], "target": ids[b]}
        if weights is not None: e["weight"] = weights[i]
        if times is not None: e["timestamp"] = times[i]
        result["edges"].append(e)
    return result


def generate(mode):
    cases = []
    rng = random.Random(20261009)
    def add(name, operation, backend, data, parameters=None, outputs=(), attachments=None, custom=None):
        cases.append({"id": f"{len(cases):06d}-{name}-{backend}", "backend": backend,
                      "graph": data, "attachments": attachments or {}, "custom": custom,
                      "task": {"operation_id": operation, "parameters": parameters or {},
                               "optional_outputs": list(outputs), "expected_status": "ready",
                               "intent": {"filters": []}}})
    patterns = []
    for p in nx.graph_atlas_g():
        if len(p) in (3, 4) and nx.is_connected(p):
            data = graph(len(p), list(p.edges()))
            data["graph"]["id"] = f"pattern-{len(patterns)}"
            patterns.append({"content": data})
    atlas = [g for g in nx.graph_atlas_g() if 1 <= len(g) <= (4 if mode == "smoke" else 6)]
    for i, g in enumerate(atlas):
        n = len(g); pairs = list(g.edges()); data = graph(n, pairs, mixed=i % 3 == 0)
        name = f"atlas-{i}-n{n}"
        for b in ["mce-gpu", "g2-aimd", "rdmce"]:
            add(name, "maximal-cliques", b, data, {"minimum_clique_size": 1}, ["total_count"])
        for b in ["cuda-ms", "gpu-maximum-clique", "maximum-clique-on-gpu"]:
            add(name, "maximum-clique", b, data, {"return_all_ties": b == "gpu-maximum-clique"}, ["upper_bound"])
        for b in ["kcgpu", "gamma", "graphset"]:
            for k in [3, 4, 5, 6]:
                add(name+f"-k{k}", "k-cliques", b, data, {"k": k}, ["cliques", "per_vertex_count"])
        for ratio in [0.5, 0.75, 1.0]:
            add(name+f"-ratio{ratio}", "quasi-cliques", "cuqc", data,
                {"minimum_size": 2, "minimum_degree_ratio": ratio}, ["total_count"])
        add(name, "k-core", "kcore-gpu", data, {"requested_k": i % 8},
            ["requested_core_vertices", "requested_core_edges"])
        for b in ["tot", "wetric"]:
            add(name, "triangle-counting", b, data, outputs=["triangles", "per_vertex_count", "per_edge_count"])
        ids = [v["id"] for v in data["vertices"]]
        updates = []
        if pairs:
            a,b = pairs[0];updates.append({"kind": "delete", "source": ids[a], "target": ids[b]})
        missing = next(((a,b) for a,b in itertools.combinations(range(n),2) if not g.has_edge(a,b)), None)
        if missing:
            a,b = missing;updates.append({"kind": "insert", "source": ids[a], "target": ids[b]})
        add(name, "dynamic-triangle-counting", "edtc", data,
            outputs=["initial_global_triangle_count", "final_global_triangle_count", "deleted_triangles", "inserted_triangles"],
            attachments={"updates": [{"content": {"updates": updates}}]})
        for b in ["graphminer", "graphset", "dumato"]:
            add(name, "graph-motifs", b, data,
                {"induced": b != "graphset", "occurrence_identity": "unique-vertex-set-and-mapping-class"},
                ["instances", "per_vertex_participation"], {"motifs": patterns})
        for pi in [0, 1, 3]:
            add(name+f"-query{pi}", "subgraph-isomorphism", "gmatch", data,
                {"ignore_vertex_labels": True}, ["embeddings"], {"query_graph": [patterns[pi]]})
        for b in ["gleiden", "parallel-louvain", "parallel-leiden", "parallel-leiden-plus"]:
            for resolution in ([1.0] if b == "gleiden" else [0.25, 1.0, 2.0]):
                add(name+f"-r{resolution}", "community-detection", b, data,
                    {"resolution": resolution}, ["communities", "edge_cut"])
        add(name, "betweenness-centrality", "turbo-bc", data, outputs=["ranking", "maximum"])
        add(name, "k-truss", "acctd", data)
        for k in [2, 3, 4, 6]:
            add(name+f"-order{k}", "densest-subgraph", "cds", data, {"clique_order": k})
    for mask in range(16 if mode == "smoke" else 512):
        pairs = [(a,3+b) for a in range(3) for b in range(3) if mask >> (a*3+b) & 1]
        data = graph(6, pairs, left=3, mixed=mask%3 == 0)
        left = [v["id"] for v in data["vertices"][:3]]
        add(f"bipartite-{mask}", "maximal-bicliques", "cumbe", data,
            {"minimum_left_size": 1, "minimum_right_size": 1}, ["total_count"],
            {"left_partition": [{"content": {"left_partition": left}}]})
        add(f"bipartite-{mask}", "maximal-biclique-counting", "mbe-gpu", data)
        for b in ["graphminer", "gamma-butterfly"]:
            add(f"bipartite-{mask}", "butterfly-counting", b, data)
    arcs = list(itertools.permutations(range(3),2))
    directed = [(3,[e for i,e in enumerate(arcs) if mask>>i&1]) for mask in range(64)]
    for i in range(8 if mode == "smoke" else 120):
        n = rng.randint(4,6)
        pairs = [p for p in itertools.permutations(range(n),2) if rng.random()<0.3][:14]
        directed.append((n,pairs))
    if mode == "smoke": directed = directed[::8]
    for i,(n,pairs) in enumerate(directed):
        data = graph(n,pairs,directed=True,mixed=i%3==0); ids=[v["id"] for v in data["vertices"]]
        for kind in ["weakly_connected", "strongly_connected"]:
            add(f"directed-{i}-{kind}", "connected-components", "ecl-scc", data, {"connectivity_mode": kind})
        add(f"directed-{i}", "transitive-closure", "gdlog", data)
        add(f"directed-{i}", "personalized-pagerank", "kpar", data,
            {"seed_vertex": ids[i%n], "top_k": n, "restart_probability": 0.2, "epsilon": 0.01})
        flow=graph(n,pairs,directed=True,weights=[rng.randint(0,20) for _ in pairs],mixed=i%3==0)
        add(f"directed-{i}", "max-flow-min-cut", "ecl-maxflow", flow, {"source": ids[0], "sink": ids[-1]})
        influence=graph(n,pairs,directed=True,weights=[int(rng.random()<0.8) for _ in pairs],mixed=i%3==0)
        add(f"directed-{i}", "influence-maximization", "superfuser", influence,
            {"diffusion_model":"independent_cascade", "seed_set_size":1+i%min(3,n), "sample_count":32})
    for i in range(8 if mode == "smoke" else 160):
        n=rng.randint(3,6); pairs=[tuple(rng.sample(range(n),2)) for _ in range(rng.randint(0,12))]
        times=sorted(rng.randint(0,10) for _ in pairs)
        data=graph(n,pairs,directed=True,times=times,mixed=i%3==0)
        for b in ["everest","mayura"]:
            add(f"temporal-{i}","temporal-motif-mining",b,data,{"max_time_span":[0,1,5,20][i%4]},["instances"])
    for i in range(8 if mode == "smoke" else 200):
        n=1+i%4;pairs=[(a,n+b) for a in range(n) for b in range(n)]
        data=graph(n*2,pairs,left=n,weights=[rng.randint(0,999) for _ in pairs],mixed=i%3==0)
        add(f"assignment-{i}","linear-assignment","hungarian-cuda",data)
    for i in range(8 if mode == "smoke" else 160):
        n=rng.randint(2,6);pairs=[p for p in itertools.combinations(range(n),2) if rng.random()<0.5][:10]
        data=graph(n,pairs,weights=[rng.randint(0,9) for _ in pairs],mixed=i%3==0)
        ids=[v["id"] for v in data["vertices"]]
        groups=[rng.sample(ids,rng.randint(1,min(n,3))) for _ in range(1+i%5)]
        add(f"gst-{i}","group-steiner-tree","gpu4gst",data,{"groups":groups})
    for n in range(7,14):
        for seed in range(2 if mode == "smoke" else 12):
            g=nx.complete_graph(n) if seed==0 else nx.gnp_random_graph(n,0.55+seed%4*0.12,seed=100*n+seed)
            data=graph(n,list(g.edges()),mixed=True)
            for b, maximum in [("kcgpu",10),("gamma",7),("graphset",6),("auto",10)]:
                for k in range(6,maximum+1):
                    add(f"higher-k-{n}-{seed}-{k}","k-cliques",b,data,{"k":k},["cliques","per_vertex_count"],custom="cliques")
            for k in [5,6,7,10,n,n+1]:
                add(f"higher-density-{n}-{seed}-{k}","densest-subgraph","cds",data,{"clique_order":k},custom="density")
    return cases


def custom_check(case,out):
    data=case["graph"]; g=nx.Graph();g.add_nodes_from(v["id"] for v in data["vertices"])
    g.add_edges_from((e["source"],e["target"]) for e in data["edges"])
    k=case["task"]["parameters"].get("k",case["task"]["parameters"].get("clique_order"))
    cliques=[frozenset(s) for s in itertools.combinations(g,k) if all(g.has_edge(a,b) for a,b in itertools.combinations(s,2))]
    if case["custom"]=="cliques":
        assert out["count"]==len(cliques) and out["complete"]
        assert len(out["cliques"])==len(cliques) and {frozenset(c) for c in out["cliques"]}==set(cliques)
        assert {r["vertex"]:r["count"] for r in out["per_vertex_count"]}=={v:sum(v in c for c in cliques) for v in g}
    else:
        from fractions import Fraction
        ids=list(g);counts=[0]*(1<<len(ids));index={v:i for i,v in enumerate(ids)}
        for c in cliques:counts[sum(1<<index[v] for v in c)]+=1
        for bit in range(len(ids)):
            for mask in range(1<<len(ids)):
                if mask>>bit&1:counts[mask]+=counts[mask^(1<<bit)]
        best=max(Fraction(counts[m],m.bit_count()) for m in range(1,1<<len(ids)))
        chosen=set(out["vertices"]);count=sum(c<=chosen for c in cliques)
        assert chosen and len(chosen)==len(out["vertices"]) and chosen<=set(g)
        assert out["clique_order"]==k and out["clique_count"]==count and out["optimal"]
        assert out["induced_edge_value"]==g.subgraph(chosen).number_of_edges()
        assert Fraction(count,len(chosen))==best and math.isclose(out["density"],float(best),abs_tol=1e-12)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--binary",type=Path,default=ROOT/"library/build/graphmine")
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--mode",choices=["smoke","full","sanitizer"],default="full")
    parser.add_argument("--gpus",default="0,1")
    parser.add_argument("--workers-per-gpu",type=int,default=1)
    parser.add_argument("--only",help="Comma-separated backend IDs")
    args=parser.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    assert 1 <= args.workers_per_gpu <= 8
    input_hashes={"binary_sha256":digest(args.binary),"generator_sha256":digest(Path(__file__)),
                  "instructions_sha256":digest(ROOT/"agent/program_instructions.json"),
                  "worker_sha256":{p.name:digest(p) for p in (ROOT/"library/repaired-workers").glob("graphmine-worker-*") if p.is_file()}}
    (work/"run-input-hashes.json").write_text(json.dumps(input_hashes,indent=2)+"\n")
    programs={o["id"]:o for o in json.loads((ROOT/"agent/program_instructions.json").read_text())["operations"]}
    catalog=SimpleNamespace(operation=lambda op:SimpleNamespace(instruction=programs[op]))
    cases=generate("smoke" if args.mode=="sanitizer" else args.mode)
    if args.only:cases=[c for c in cases if c["backend"] in args.only.split(",")]
    if args.mode=="sanitizer":
        # Include nontrivial fixtures for each kernel and every extended order.
        selected={}
        for c in cases:
            task=c["task"];key=(task["operation_id"],c["backend"],json.dumps(task["parameters"],sort_keys=True))
            if task["parameters"].get("k",0)>len(c["graph"]["vertices"]) or task["parameters"].get("clique_order",0)>len(c["graph"]["vertices"]):continue
            if key not in selected or len(c["graph"]["edges"])>len(selected[key]["graph"]["edges"]):selected[key]=c
        cases=list(selected.values())
    (work/"cases.json").write_text(json.dumps(cases)+"\n")
    gpus=args.gpus.split(",");workers=gpus*args.workers_per_gpu;started=time.time()
    def shard(shard_id,gpu):
        results=[];folder=work/f"gpu-{gpu}-worker-{shard_id}";folder.mkdir(exist_ok=True)
        env={**os.environ,"CUDA_VISIBLE_DEVICES":gpu,"OMP_NUM_THREADS":"2","OPENBLAS_NUM_THREADS":"1",
             "GRAPHMINE_WORKER_INHERIT_PROCESS_GROUP":"1"}
        with (folder/"results.jsonl").open("w") as stream:
            for c in cases[shard_id::len(workers)]:
                begin=time.time();task=c["task"];op=task["operation_id"];spec=programs[op]
                case_dir=folder/c["id"];case_dir.mkdir(exist_ok=True)
                path=case_dir/"graph.json";path.write_text(json.dumps(c["graph"])+"\n")
                command=[str(args.binary.resolve()),"run",op,"--graph",str(path),"--backend",c["backend"]]
                for name,value in task["parameters"].items():
                    flag=spec["parameters"][name]["flag"]
                    if isinstance(value,bool):
                        if value:command.append(flag)
                    elif isinstance(value,(list,dict)):command.extend([flag,json.dumps(value)])
                    else:command.extend([flag,str(value)])
                for flag in dict.fromkeys(spec["optional_outputs"][name] for name in task["optional_outputs"]):command.append(flag)
                for name,items in c["attachments"].items():
                    for i,item in enumerate(items):
                        attachment=case_dir/f"{name}-{i}.json";attachment.write_text(json.dumps(item["content"])+"\n")
                        command.extend([spec["auxiliary_inputs"][name]["flag"],str(attachment)])
                if args.mode=="sanitizer":
                    command=["compute-sanitizer","--tool","memcheck","--target-processes","all","--error-exitcode","97",
                             "--log-file",str(case_dir/"sanitizer.log"),*command]
                record={"id":c["id"],"operation":op,"backend":c["backend"],"gpu":gpu,"command":command}
                try:
                    proc=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
                    try:stdout,stderr=proc.communicate(timeout=120)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate()
                        (case_dir/"stdout.json").write_text(stdout)
                        (case_dir/"stderr.log").write_text(stderr)
                        raise TimeoutError("120 second case timeout")
                    (case_dir/"stdout.json").write_text(stdout);(case_dir/"stderr.log").write_text(stderr)
                    payload=json.loads(stdout);record["exit_code"]=proc.returncode
                    assert proc.returncode==0 and payload.get("ok"),payload
                    if c["custom"]:custom_check(c,payload["output"])
                    else:
                        grade=grade_output(catalog,c,payload["output"]);record["grade"]=grade
                        assert not grade["issues"],grade
                    if args.mode=="sanitizer":
                        report=(case_dir/"sanitizer.log").read_text()
                        assert "ERROR SUMMARY: 0 errors" in report and not __import__("re").search(r"ERROR SUMMARY: [1-9]",report),report[-3000:]
                    record["passed"]=True
                except Exception as error:
                    record.update(passed=False,error=str(error)[:6000])
                    print("FAIL",c["id"],record["error"][:400],flush=True)
                record["seconds"]=time.time()-begin;results.append(record)
                stream.write(json.dumps(record)+"\n");stream.flush()
                if len(results)%100==0:print(f"GPU {gpu}: {len(results)} cases, {sum(not r['passed'] for r in results)} failures",flush=True)
        return results
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures=[pool.submit(shard,i,gpu) for i,gpu in enumerate(workers)]
        results=[r for f in futures for r in f.result()]
    coverage={}
    for r in results:
        key=r["operation"]+"/"+r["backend"];row=coverage.setdefault(key,{"passed":0,"failed":0})
        row["passed" if r["passed"] else "failed"]+=1
    assert input_hashes["binary_sha256"]==digest(args.binary),"Binary changed during sweep"
    assert input_hashes["generator_sha256"]==digest(Path(__file__)),"Generator changed during sweep"
    assert input_hashes["instructions_sha256"]==digest(ROOT/"agent/program_instructions.json"),"Instructions changed during sweep"
    for name,expected in input_hashes["worker_sha256"].items():
        assert expected==digest(ROOT/"library/repaired-workers"/name),f"Worker {name} changed during sweep"
    summary={"mode":args.mode,**input_hashes,"workers_per_gpu":args.workers_per_gpu,
             "gpus":gpus,"seconds":time.time()-started,"cases":len(results),"passed":sum(r["passed"] for r in results),
             "failed":sum(not r["passed"] for r in results),"coverage":coverage,
             "limitations":"Exact bounded oracles; heuristic partitions checked for score/feasibility, PPR errors measured, influence deterministic probabilities checked. No global optimality claim for heuristic operations."}
    (work/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    return bool(summary["failed"])


if __name__=="__main__":sys.exit(main())
