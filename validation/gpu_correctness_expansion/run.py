#!/usr/bin/env python3
"""Reproducible, bounded validation of the newly cataloged GPU artifacts.

Upstream sources are never edited. Adaptations expose results in scratch copies;
every build/run keeps its command, exit status, timing, and complete output.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import hashlib
import json
import os
from pathlib import Path
import random
import re
import resource
import struct
import subprocess
import time

import networkx as nx
import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = Path(os.environ.get("GRAPHMINE_VALIDATION_ROOT", Path(__file__).resolve().parent)).resolve()
ROOT = Path(__file__).resolve().parents[2]
PROBLEMS = ROOT / "problems"
SEED = 20261004
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def source(problem, paper):
    return PROBLEMS / problem / "papers" / paper / "code"


SCC = source("35_connected_components", "2023_eclscc")
FLOW = source("22_max_flow_min_cut", "2025_ecl_maxflow")
ASSIGNMENT = source("31_bipartite_matching_assignment", "2019_hungariangpu")
GIM = source("28_influence_maximization", "2021_gim")
SUPERFUSER = source("28_influence_maximization", "2021_superfuser")


def run_command(name, command, *, cwd=ROOT, timeout=120, kind="runs", stdin_path=None):
    directory = HERE / kind
    directory.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "0"), "OMP_NUM_THREADS": "4"}
    started = time.monotonic()
    with (directory / (name + ".log")).open("w") as log, (Path(stdin_path) if stdin_path else Path('/dev/null')).open('rb') as input_stream:
        process = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env,
                                   stdin=input_stream,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            code, timed_out = 124, True
    record = {"command": list(map(str, command)), "cwd": str(cwd),
              "stdin_path": str(stdin_path) if stdin_path else None,
              "exit_code": code, "timeout": timed_out,
              "elapsed_seconds": time.monotonic() - started,
              "log": str((directory / (name + ".log")).relative_to(HERE))}
    write_json(directory / (name + ".json"), record)
    return record, (directory / (name + ".log")).read_text(errors="replace")


def adapt(original, name, transform):
    text = original.read_text()
    updated = transform(text)
    target = HERE / "adapted" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated)
    (target.parent / (name + ".patch")).write_text("".join(difflib.unified_diff(
        text.splitlines(True), updated.splitlines(True),
        fromfile=str(original.relative_to(ROOT)), tofile=name)))
    write_json(target.parent / (name + ".source.json"), {
        "source": str(original.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "adapted_sha256": hashlib.sha256(updated.encode()).hexdigest(),
        "purpose": "host input/output instrumentation; original GPU kernels retained"})
    return target


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Expected one adaptation anchor: {before!r}")
    return text.replace(before, after, 1)


def prepare():
    (HERE / "bin").mkdir(parents=True, exist_ok=True)
    adapt(SCC / "source/ECL-SCC_10.cu", "ecl_scc.cu", lambda text: replace_once(
        text, '  // output SCC sizes and frequency',
        '  printf("VALIDATION_COMPONENTS");\n'
        '  for (int v = 0; v < n; ++v) printf(" %d", iomax[v].x);\n'
        '  printf("\\n");\n  // output SCC sizes and frequency'))
    adapt(FLOW / "src/main.cu", "ecl_flow.cu", lambda text: replace_once(
        text, '  cudaFree(d_g.nindex);',
        '  CheckCuda();\n  printf("VALIDATION_FLOW");\n'
        '  for (int e = 0; e < g.edges; ++e) printf(" %d", flow[e]);\n'
        '  printf("\\n");\n  cudaFree(d_g.nindex);'))
    def assignment_adapter(text):
        text = replace_once(text, 'int main()', 'int upstream_main()')
        return text + r'''

// Matrix boundary only. Kernels and Hungarian_Algorithm are unchanged.
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  FILE* input = fopen(argv[1], "r");
  if (!input) return 3;
  int count = 0;
  if (fscanf(input, "%d", &count) != 1 || count < 1 || count > n) return 4;
  for (int c = 0; c < n; ++c) for (int r = 0; r < n; ++r)
    h_cost[c][r] = (c >= count && r < count) ? 100000000 : 0;
  for (int r = 0; r < count; ++r) for (int c = 0; c < count; ++c)
    if (fscanf(input, "%d", &h_cost[c][r]) != 1) return 5;
  fclose(input);
  checkCuda(cudaMemcpyToSymbol(slack, h_cost, sizeof(h_cost)));
  Hungarian_Algorithm();
  checkCuda(cudaDeviceSynchronize());
  checkCuda(cudaMemcpyFromSymbol(h_column_of_star_at_row,
      column_of_star_at_row, sizeof(h_column_of_star_at_row)));
  printf("VALIDATION_ASSIGNMENT");
  for (int r = 0; r < count; ++r) printf(" %d", h_column_of_star_at_row[r]);
  printf("\n");
  return 0;
}
'''
    adapt(ASSIGNMENT / "HungarianCUDA.cu", "hungarian.cu", assignment_adapter)


def build(names):
    prepare()
    commands = {
        "ecl_scc": ["nvcc", "-O2", "-arch=sm_89", "-std=c++17", HERE / "adapted/ecl_scc.cu", "-I", SCC / "source", "-o", HERE / "bin/ecl_scc"],
        "ecl_flow": ["nvcc", "-O2", "-arch=sm_89", "-std=c++17", HERE / "adapted/ecl_flow.cu", "-I", FLOW / "lib", "-I", FLOW / "src", "-o", HERE / "bin/ecl_flow"],
        "hungarian": ["nvcc", "-O2", "-arch=sm_89", "-std=c++17", "-D_n_=64", "-D_range_=100", HERE / "adapted/hungarian.cu", "-o", HERE / "bin/hungarian"],
        "gim": ["nvcc", "-O2", "-arch=sm_89", "-std=c++17", *sorted(GIM.glob("*.cu")), "-lcurand", "-o", HERE / "bin/gim"],
        "superfuser": ["nvcc", "-O2", "-arch=sm_89", "-std=c++17", "-Xcompiler=-fopenmp,-mavx2", SUPERFUSER / "src/gpu.cu", "-o", HERE / "bin/superfuser"],
    }
    selected = names or list(commands)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tasks = {pool.submit(run_command, name, commands[name], timeout=240, kind="builds"):name for name in selected}
        for future in concurrent.futures.as_completed(tasks):
            name = tasks[future]
            record, output = future.result()
            print(name, "build exit", record["exit_code"], flush=True)
            if record["exit_code"]:print(output[-2000:], flush=True)


def ecl_file(path, n, edges, weights=False):
    edges = sorted(edges)
    offsets = [0]
    for v in range(n):offsets.append(offsets[-1] + sum(e[0] == v for e in edges))
    values = [n, len(edges), *offsets, *(e[1] for e in edges)]
    if weights:values += [e[2] for e in edges]
    path.write_bytes(struct.pack("<" + "i" * len(values), *values))
    return edges


def partition(labels):
    groups = {}
    for vertex, label in enumerate(labels):groups.setdefault(label, []).append(vertex)
    return sorted(sorted(group) for group in groups.values())


def observation(text, label):
    match = re.search(r"^" + label + r"(.*)$", text, re.M)
    if not match:raise ValueError("Missing result marker " + label)
    return list(map(int, match.group(1).split()))


def scc_cases():
    yield "small", 10, [(0,1),(1,2),(2,0),(2,3),(3,4),(4,3),(4,5),(6,7),(7,6),(8,9)]
    yield "isolated", 4, []
    yield "single_vertex", 1, []
    yield "dag", 65, [(v,v+1) for v in range(64)]
    yield "cycle", 513, [(v,(v+1)%513) for v in range(513)]
    for k in range(8):
        rng=random.Random(SEED+k)
        n = 24 if k < 4 else 192
        edges=[(u,v) for u in range(n) for v in range(n) if u!=v and rng.random()<2.5/n]
        yield f"random_{k}", n, edges


def flow_cases():
    yield "small", 6, [(0,1,16),(0,2,13),(1,2,10),(2,1,4),(1,3,12),(3,2,9),(2,4,14),(4,3,7),(3,5,20),(4,5,4)],0,5
    yield "disconnected", 5, [(0,1,8),(1,2,3),(3,4,9)],0,4
    yield "zero_capacities",4,[(0,1,0),(1,3,8),(0,2,3),(2,3,0)],0,3
    yield "empty_edges",4,[],0,3
    yield "dead_end",5,[(0,1,10),(1,2,9),(0,3,4),(3,4,3)],0,4
    for k in range(8):
        rng=random.Random(SEED+100+k)
        n=12 if k<4 else 96
        edges=[(u,v,rng.randrange(0,30)) for u in range(n) for v in range(n) if u!=v and rng.random()<4/n]
        yield f"random_{k}",n,edges,0,n-1


def validate(name):
    cases=[]
    folder=HERE/"datasets"/name
    folder.mkdir(parents=True,exist_ok=True)
    if name=="ecl_scc":
        for key,n,edges in scc_cases():
            graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_edges_from(edges)
            expected=sorted(sorted(c) for c in nx.strongly_connected_components(graph))
            path=folder/(key+".egr");ecl_file(path,n,edges)
            rec,text=run_command(name+"_"+key,[HERE/"bin"/name,path],timeout=30)
            try:
                labels=observation(text,"VALIDATION_COMPONENTS")
                actual=partition(labels)
                passed=rec['exit_code']==0 and len(labels)==n and expected==actual
                detail={"expected":expected,"observed":actual}
            except ValueError as error:passed=False;detail={"error":str(error),"expected":expected}
            cases.append({"name":key,"passed":passed,**rec,**detail})
    elif name=="ecl_flow":
        for key,n,edges,s,t in flow_cases():
            graph=nx.DiGraph();graph.add_nodes_from(range(n));graph.add_weighted_edges_from(edges,weight="capacity")
            expected=nx.maximum_flow_value(graph,s,t)
            path=folder/(key+".egr");edges=ecl_file(path,n,edges,True)
            rec,text=run_command(name+"_"+key,[HERE/"bin"/name,path,s,t],timeout=30)
            try:
                flows=observation(text,"VALIDATION_FLOW")
                match=re.search(r'Maximum flow from nodes \d+ to \d+: (\d+)',text)
                actual=int(match[1]) if match else None
                balance=[0]*n;residual=nx.DiGraph();residual.add_nodes_from(range(n))
                bounded=len(flows)==len(edges)
                for (u,v,c),f in zip(edges,flows):
                    bounded=bounded and 0<=f<=c
                    balance[u]-=f;balance[v]+=f
                    if c-f>0:residual.add_edge(u,v)
                    if f>0:residual.add_edge(v,u)
                side={s}|nx.descendants(residual,s)
                cut=sum(c for u,v,c in edges if u in side and v not in side)
                conservation=all(balance[v]==0 for v in range(n) if v not in [s,t])
                passed=rec['exit_code']==0 and bounded and conservation and actual==expected==cut==balance[t]==-balance[s] and t not in side
                detail={"expected":expected,"observed":actual,"cut_capacity":cut,"flow_conservation":conservation,"capacity_bounds":bounded,"flows":flows}
            except ValueError as error:passed=False;detail={"error":str(error),"expected":expected}
            cases.append({"name":key,"passed":passed,**rec,**detail})
    elif name=="hungarian":
        matrices=[("small",np.array([[4,1,3],[2,0,5],[3,2,2]])),("single",np.array([[8]])),("ties",np.ones((5,5),dtype=int))]
        for k in range(8):
            rng=np.random.default_rng(SEED+k)
            n=7 if k<4 else 64
            matrices.append((f"random_{k}",rng.integers(0,1000,(n,n))))
        for key,matrix in matrices:
            n=len(matrix);rows,cols=linear_sum_assignment(matrix);expected=int(matrix[rows,cols].sum())
            path=folder/(key+".txt");path.write_text(str(n)+"\n"+"\n".join(" ".join(map(str,row)) for row in matrix)+"\n")
            rec,text=run_command(name+"_"+key,[HERE/"bin"/name,path],timeout=30)
            try:
                chosen=observation(text,"VALIDATION_ASSIGNMENT")
                feasible=len(chosen)==n and sorted(chosen)==list(range(n))
                actual=int(matrix[np.arange(n),chosen].sum()) if feasible else None
                passed=rec['exit_code']==0 and feasible and actual==expected
                detail={"expected":expected,"observed":actual,"matching":chosen,"feasible":feasible}
            except ValueError as error:passed=False;detail={"error":str(error),"expected":expected}
            cases.append({"name":key,"passed":passed,**rec,**detail})
    else:raise ValueError(name)
    result={"backend":name,"seed":SEED,"status":"pass" if all(c['passed'] for c in cases) else "correctness_fail","cases":cases,"passed":sum(c['passed'] for c in cases),"total":len(cases),"scope":"Only exercised semantics; see case records. Not a performance or general correctness claim."}
    write_json(HERE/"results"/(name+".json"),result)
    print(name,result['status'],f"{result['passed']}/{result['total']}",flush=True)
    for case in cases:
        if not case['passed']:print('FAILED',case['name'],case.get('error'),case.get('expected'),case.get('observed'),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['build','validate'])
    parser.add_argument('backends',nargs='*')
    args=parser.parse_args()
    if args.action=='build':build(args.backends)
    else:
        for backend in args.backends or ['ecl_scc','ecl_flow','hungarian']:validate(backend)
