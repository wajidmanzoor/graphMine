#!/usr/bin/env python3
"""Scoped GPU checks of collected upstream implementations, outside the CLI.

No result here promotes an algorithm into the agent. Exact numerical/graph
checks, model execution checks, and missing integrations remain distinct.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import sys
import time
import traceback

import networkx as nx
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCES = ROOT / "problems/_sources"
SEED = 20261009


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Evidence:
    def __init__(self, family, gpu):
        self.family, self.gpu = family, gpu
        self.folder = HERE / "results" / family
        self.folder.mkdir(parents=True, exist_ok=True)
        self.stream = (self.folder / "cases.jsonl").open("w")
        self.cases = []

    def case(self, backend, label, scope, fixture, check):
        started = time.time()
        row = dict(backend=backend, case=label, scope=scope, fixture=fixture, gpu=self.gpu)
        try:
            row["measurements"] = check() or {}
            row["passed"] = True
        except Exception as error:
            row.update(passed=False, error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        row["elapsed_seconds"] = time.time()-started
        self.cases.append(row)
        self.stream.write(json.dumps(row)+"\n")
        self.stream.flush()

    def finish(self, error=None):
        summary = dict(family=self.family, gpu=self.gpu, cases=len(self.cases),
                       passed=sum(r["passed"] for r in self.cases),
                       failed=sum(not r["passed"] for r in self.cases),
                       startup_error=error, by_backend={},
                       python=sys.version, numpy=np.__version__,
                       script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        for row in self.cases:
            counts=summary["by_backend"].setdefault(row["backend"],dict(passed=0,failed=0,scope=row["scope"]))
            counts["passed" if row["passed"] else "failed"]+=1
        (self.folder/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        self.stream.close()
        print(json.dumps(summary),flush=True)


def small_graphs():
    yield from (g for g in nx.graph_atlas_g() if 1 <= len(g) <= 6)
    for i in range(80):
        yield nx.gnp_random_graph(7+i%6, [0.1,0.3,0.6,0.9][i%4], seed=SEED+i)


def pyg(evidence):
    sys.path.insert(0,str(SOURCES/"pyg-79d33965a40b"))
    import torch
    from torch_geometric.data import Data
    from torch_geometric.nn import avg_pool
    from torch_geometric.utils import subgraph, k_hop_subgraph
    torch.set_num_threads(2)
    rng=np.random.default_rng(SEED)
    for i,g in enumerate(small_graphs()):
        n=len(g); pairs=list(g.edges()); arcs=pairs+[(v,u) for u,v in pairs]
        index=torch.tensor(arcs,dtype=torch.long,device="cuda").reshape(-1,2).t().contiguous()
        assignment=rng.integers(0,max(1,n//2),n)
        _,cluster=np.unique(assignment,return_inverse=True)
        features=rng.normal(size=(n,3)).astype(np.float32)
        weights=np.arange(1,len(pairs)+1,dtype=np.float32)
        def pool_check():
            out=avg_pool(torch.tensor(assignment,device="cuda"),Data(
                x=torch.tensor(features,device="cuda"),edge_index=index,
                edge_attr=torch.tensor(np.tile(weights,2),device="cuda")))
            expected_x=np.stack([features[cluster==c].mean(axis=0) for c in range(max(cluster)+1)])
            np.testing.assert_allclose(out.x.cpu().numpy(),expected_x,rtol=1e-6,atol=1e-6)
            expected={}
            for (u,v),w in zip(arcs,np.tile(weights,2)):
                a,b=int(cluster[u]),int(cluster[v])
                if a!=b:expected[a,b]=expected.get((a,b),0)+float(w)
            actual={tuple(e):float(w) for e,w in zip(out.edge_index.t().cpu().tolist(),out.edge_attr.cpu().tolist())}
            assert actual==expected,(actual,expected)
            assert out.x.is_cuda
            return {"coarse_vertices":len(expected_x),"coarse_arcs":len(expected)}
        fixture={"n":n,"edges":pairs,"assignment":assignment.tolist(),"features":features.tolist(),"weights":weights.tolist()}
        evidence.case("pyg-average-pool",str(i),"Exact quotient for supplied assignment, drop self-loops, mean features, sum weights; no clustering generation",fixture,pool_check)
        chosen=sorted(rng.choice(n,size=max(1,n//2),replace=False).tolist())
        def induced_check():
            out,_=subgraph(torch.tensor(chosen,device="cuda"),index,num_nodes=n)
            expected={(u,v) for u,v in arcs if u in chosen and v in chosen}
            assert {tuple(e) for e in out.t().cpu().tolist()}==expected
            assert out.is_cuda
        evidence.case("pyg-induced-subgraph",str(i),"Exact selected-vertex edge extraction; caller preserves isolated vertices",{"n":n,"edges":pairs,"chosen":chosen},induced_check)
        hops=i%4;seed=i%n
        def khop_check():
            vertices,out,_,_=k_hop_subgraph(seed,hops,index,num_nodes=n)
            expected=set(nx.single_source_shortest_path_length(g,seed,cutoff=hops))
            assert set(vertices.cpu().tolist())==expected
            assert {tuple(e) for e in out.t().cpu().tolist()}=={(a,b) for a,b in arcs if a in expected and b in expected}
        evidence.case("pyg-khop-subgraph",str(i),"Exact undirected k-hop induced extraction",{"n":n,"edges":pairs,"seed":seed,"hops":hops},khop_check)


def knn(evidence):
    sys.path.insert(0,str(HERE/"build/torch_cluster"))
    import torch
    from torch_cluster import knn_graph
    rng=np.random.default_rng(SEED)
    fixtures=[]
    for i in range(200):
        n=2+i%19;dim=1+i%5;k=i%n
        x=rng.integers(-4,5,(n,dim)).astype(np.float32)
        fixtures.append((x,k))
    fixtures.extend((np.zeros((n,2),dtype=np.float32),k) for n in range(2,11) for k in range(n))
    for i,(x,k) in enumerate(fixtures):
        n=len(x)
        def check():
            result=knn_graph(torch.tensor(x,device="cuda"),k,loop=False,flow="target_to_source")
            rows=result.t().cpu().tolist()
            assert len(rows)==n*k,{"observed_edges":len(rows),"expected_edges":n*k,"neighbors":rows}
            distance=((x[:,None,:]-x[None,:,:])**2).sum(axis=2)
            np.fill_diagonal(distance,np.inf)
            for u in range(n):
                neighbors=[v for a,v in rows if a==u]
                assert len(neighbors)==len(set(neighbors))==k and u not in neighbors
                np.testing.assert_allclose(sorted(distance[u,neighbors]),sorted(distance[u])[:k])
            assert result.is_cuda
        evidence.case("torch-cluster-knn",str(i),"Exact squared-Euclidean directed kNN, distinct IDs including tied/duplicate vectors",{"vectors":x.tolist(),"k":k},check)


def models(evidence):
    sys.path.insert(0,str(SOURCES/"pyg-79d33965a40b"))
    import torch
    from torch_geometric.nn import GCNConv,GATConv,SAGEConv,GINConv,SAGPooling,dense_diff_pool
    torch.set_num_threads(2)
    for i,g in enumerate(list(small_graphs())[::5]):
        n=len(g);pairs=list(g.edges());arcs=pairs+[(v,u) for u,v in pairs]
        edge=torch.tensor(arcs,dtype=torch.long).reshape(-1,2).t().contiguous()
        torch.manual_seed(SEED+i);features=torch.randn(n,4)
        for label,make in [("pyg-gcn",lambda:GCNConv(4,3)),("pyg-gat",lambda:GATConv(4,3)),
                           ("pyg-graphsage",lambda:SAGEConv(4,3)),("pyg-gin",lambda:GINConv(torch.nn.Linear(4,3)))]:
            def check():
                torch.manual_seed(SEED+i);cpu=make().eval();gpu=copy.deepcopy(cpu).cuda()
                a=cpu(features,edge);b=gpu(features.cuda(),edge.cuda())
                torch.testing.assert_close(a,b.cpu(),rtol=2e-5,atol=2e-5)
                b.square().mean().backward()
                assert b.shape==(n,3) and torch.isfinite(b).all()
                assert all(p.grad is None or torch.isfinite(p.grad).all() for p in gpu.parameters())
            evidence.case(label,str(i),"Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim",{"n":n,"edges":pairs,"seed":SEED+i},check)
        def diffpool_check():
            adj=torch.tensor(nx.to_numpy_array(g),dtype=torch.float32)[None]
            x=features[None];s=torch.randn(1,n,max(1,n//2))
            a=dense_diff_pool(x,adj,s);b=dense_diff_pool(x.cuda(),adj.cuda(),s.cuda())
            for cpu,gpu in zip(a,b):torch.testing.assert_close(cpu,gpu.cpu(),rtol=2e-5,atol=2e-5)
        evidence.case("pyg-diffpool",str(i),"CUDA/CPU layer-output parity only; no trained graph classifier",{"n":n,"edges":pairs,"seed":SEED+i},diffpool_check)
        def sag_check():
            torch.manual_seed(SEED+i);cpu=SAGPooling(4,ratio=.5).eval();gpu=copy.deepcopy(cpu).cuda()
            a=cpu(features,edge);b=gpu(features.cuda(),edge.cuda())
            for ca,cb in zip(a,b):
                if ca is not None:torch.testing.assert_close(ca,cb.cpu(),rtol=2e-5,atol=2e-5)
        evidence.case("pyg-sagpool",str(i),"CUDA/CPU pooling parity only; no trained graph classifier",{"n":n,"edges":pairs,"seed":SEED+i},sag_check)


def faiss(evidence):
    rng=np.random.default_rng(SEED)
    fixtures=[]
    for i in range(200):
        n=2+i%19;dim=1+i%5;k=i%n
        fixtures.append((rng.integers(-4,5,(n,dim)).astype(np.float32),k))
    text="".join(f"{len(x)} {x.shape[1]} {k}\n"+" ".join(map(str,x.ravel()))+"\n" for x,k in fixtures)
    proc=subprocess.run([str(HERE/"build/faiss_knn")],input=text,text=True,capture_output=True,timeout=180)
    (evidence.folder/"stderr.log").write_text(proc.stderr)
    assert proc.returncode==0,proc.stderr[-4000:]
    outputs=proc.stdout.splitlines();assert len(outputs)==len(fixtures)
    for i,((x,k),output) in enumerate(zip(fixtures,outputs)):
        def check():
            rows=json.loads(output);assert len(rows)==len(x)
            distance=((x[:,None,:]-x[None,:,:])**2).sum(axis=2)
            np.fill_diagonal(distance,np.inf)
            for u,candidates in enumerate(rows):
                chosen=[(v,d) for v,d in candidates if v!=u][:k]
                assert len(chosen)==len(set(v for v,d in chosen))==k
                np.testing.assert_allclose([d for v,d in chosen],[distance[u,v] for v,d in chosen],atol=1e-5)
                np.testing.assert_allclose(sorted(d for v,d in chosen),sorted(distance[u])[:k],atol=1e-5)
        evidence.case("faiss-flat-knn",str(i),"Collected GPU FlatL2 search plus explicit self-ID removal, exact distances and tied-neighbor optimum vs NumPy",{"vectors":x.tolist(),"k":k},check)


def hypergraph(evidence):
    sys.path.insert(0,str(SOURCES/"dhg-b4f80211c217"))
    import torch
    import dhg
    from dhg.models import HGNN,HNHN,HyperGCN
    torch.set_num_threads(2);rng=random.Random(SEED)
    for i in range(100):
        n=3+i%10;edges=sorted({tuple(sorted(rng.sample(range(n),rng.randint(1,n)))) for _ in range(1+i%8)})
        hg=dhg.Hypergraph(n,edges);torch.manual_seed(SEED+i);features=torch.randn(n,4)
        for name,model_type in [("dhg-hgnn",HGNN),("dhg-hnhn",HNHN),("dhg-hypergcn",HyperGCN)]:
            def check():
                torch.manual_seed(SEED+i);model=model_type(4,5,3,drop_rate=0).eval().cuda()
                if name=="dhg-hypergcn" and any(len(e)<2 for e in edges):
                    try:model(features.cuda(),copy.deepcopy(hg).to(torch.device("cuda")))
                    except AssertionError as error:
                        assert "greater than or equal to 2" in str(error)
                        return {"expected_rejection":"HyperGCN requires at least two vertices in every hyperedge"}
                    raise AssertionError("Expected singleton-hyperedge rejection")
                logits=model(features.cuda(),copy.deepcopy(hg).to(torch.device("cuda")))
                assert logits.is_cuda and logits.shape==(n,3) and torch.isfinite(logits).all()
                torch.nn.functional.cross_entropy(logits,torch.arange(n,device="cuda")%3).backward()
                assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
                if name!="dhg-hypergcn":
                    cpu=model.cpu();expected=cpu(features,copy.deepcopy(hg))
                    torch.testing.assert_close(logits.cpu(),expected,rtol=3e-5,atol=3e-5)
                # HyperGCN makes random device-specific graph reductions, so
                # CPU/GPU path equality would not be a valid assertion.
            rejected=name=="dhg-hypergcn" and any(len(e)<2 for e in edges)
            evidence.case(name+("-domain-rejection" if rejected else ""),str(i),
                          "Expected rejection of singleton hyperedges; no model output" if rejected else "Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim",
                          {"n":n,"hyperedges":edges,"seed":SEED+i},check)
        def hgnn_formula():
            layer=dhg.nn.HGNNConv(4,3,is_last=True).eval().cuda()
            x=features.cuda();out=layer(x,copy.deepcopy(hg).to(torch.device("cuda")))
            incidence=np.zeros((n,len(edges)))
            for j,e in enumerate(edges):incidence[list(e),j]=1
            dv=incidence.sum(axis=1);de=incidence.sum(axis=0)
            inv=np.zeros(n);np.divide(1,np.sqrt(dv),out=inv,where=dv>0)
            normalized=(inv[:,None]*incidence) @ np.diag(1/de) @ (incidence.T*inv[None,:])
            linear=features.numpy() @ layer.theta.weight.detach().cpu().numpy().T + layer.theta.bias.detach().cpu().numpy()
            np.testing.assert_allclose(out.detach().cpu().numpy(),normalized@linear,rtol=3e-5,atol=3e-5)
        evidence.case("dhg-hgnn-formula",str(i),"Independent dense NumPy incidence-matrix formula for HGNN convolution",{"n":n,"hyperedges":edges,"seed":SEED+i},hgnn_formula)


def eigen(evidence):
    os.environ.setdefault("CUDA_PATH","/usr")
    import cupy as cp
    import cupyx.scipy.sparse as sparse
    source=SOURCES/"cupy-379a2bedbca9"
    dense=load_file("collected_cupy_dense",source/"cupy/linalg/_eigenvalue.py")
    lanczos=load_file("collected_cupy_lanczos",source/"cupyx/scipy/sparse/linalg/_eigen.py")
    lobpcg=load_file("collected_cupy_lobpcg",source/"cupyx/scipy/sparse/linalg/_lobpcg.py")
    graphs=list(small_graphs())
    graphs.extend(nx.path_graph(n) for n in [25,32,64])
    graphs.extend(nx.gnp_random_graph(32,.2,seed=SEED+i) for i in range(10))
    for i,g in enumerate(graphs):
        a=nx.to_numpy_array(g);lap=np.diag(a.sum(axis=1))-a;n=len(g)
        expected=np.linalg.eigvalsh(lap)
        methods=[("cupy-dense-eigh",lambda:dense.eigh(cp.asarray(lap)),n)]
        if n>1:
            k=min(2,n-1)
            methods += [("cupy-lanczos",lambda:lanczos.eigsh(sparse.csr_matrix(cp.asarray(lap)),k=k,which="SA",tol=1e-9,maxiter=1000,rng=SEED),k),
                        ("cupy-lobpcg",lambda:lobpcg.lobpcg(sparse.csr_matrix(cp.asarray(lap)),cp.random.RandomState(SEED).normal(size=(n,k)),largest=False,tol=1e-9,maxiter=300),k)]
        for name,solve,k in methods:
            def check():
                values,vectors=solve();w=cp.asnumpy(values);v=cp.asnumpy(vectors)
                np.testing.assert_allclose(np.sort(w),expected[:k],rtol=1e-5,atol=1e-6)
                residual=float(np.linalg.norm(lap@v-v*w,ord=2))
                orthogonality=float(np.linalg.norm(v.T@v-np.eye(k),ord=2))
                assert residual<=1e-6*max(1,np.linalg.norm(lap,ord=2)),residual
                assert orthogonality<=1e-5,orthogonality
                return {"residual":residual,"orthogonality":orthogonality,"runtime_cupy":cp.__version__,
                        "source":"Collected Python algorithm over CuPy 14.2 compiled runtime", "values":w.tolist()}
            evidence.case(name,str(i),"Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues",{"n":n,"edges":list(g.edges()),"k":k},check)


def persistence_reference(distance, dimension=2):
    """Elementary F2 boundary-matrix reduction; zero-length bars omitted."""
    n=len(distance);simplices=[]
    for size in range(1,dimension+3):
        for vertices in itertools.combinations(range(n),size):
            birth=max((distance[a,b] for a,b in itertools.combinations(vertices,2)),default=0)
            simplices.append((float(birth),size-1,vertices))
    simplices.sort();lookup={s[2]:i for i,s in enumerate(simplices)}
    reduced={};pivots={};births=set();paired=set();bars={d:[] for d in range(dimension+1)}
    for j,(death,dim,vertices) in enumerate(simplices):
        column={lookup[vertices[:i]+vertices[i+1:]] for i in range(len(vertices))} if dim else set()
        while column and max(column) in pivots:column ^= reduced[pivots[max(column)]]
        reduced[j]=column
        if not column:births.add(j)
        else:
            pivot=max(column);pivots[pivot]=j;paired.add(pivot)
            birth,bdim,_=simplices[pivot]
            if bdim<=dimension and death>birth:bars[bdim].append((birth,death))
    for j in births-paired:
        birth,dim,_=simplices[j]
        if dim<=dimension:bars[dim].append((birth,float("inf")))
    return {d:sorted(b) for d,b in bars.items()}


def persistence(evidence):
    sys.path.insert(0,str(HERE/"build/ripser-python"))
    import ripserplusplus
    rng=np.random.default_rng(SEED)
    for i in range(100):
        n=2+i%11;points=rng.integers(-3,4,(n,2)).astype(float)
        distance=np.sqrt(((points[:,None]-points[None,:])**2).sum(axis=2)).astype(np.float32)
        expected=persistence_reference(distance)
        result=ripserplusplus.run("--format distance --dim 2",distance)
        def check():
            for dimension in range(3):
                arr=result.get(dimension,np.empty((0,2)))
                rows=[(float(r[0]),float(r[1])) for r in arr]
                actual=sorted((a,b) for a,b in rows if b>a and math.isfinite(b))
                finite=[(a,b) for a,b in expected[dimension] if math.isfinite(b)]
                np.testing.assert_allclose(np.array(actual).reshape(-1,2),np.array(finite).reshape(-1,2),rtol=1e-6,atol=1e-6)
        evidence.case("ripserplusplus-finite-bars",str(i),"Hybrid upstream implementation vs independent F2 boundary reduction, finite intervals H0 through H2",{"points":points.tolist()},check)
        def essential_check():
            actual=[(float(a),float(b)) for a,b in result.get(0,[]) if math.isinf(b)]
            essential=[(a,b) for a,b in expected[0] if math.isinf(b)]
            assert actual==essential,{"observed":actual,"expected":essential}
        evidence.case("ripserplusplus-essential-h0",str(i),"Full barcode contract: Python export must include essential H0 interval",{"points":points.tolist()},essential_check)


def mvc(evidence):
    binary=HERE/"build/mvc_components/output"
    for i,g in enumerate(small_graphs()):
        n=len(g);pairs=list(g.edges())
        optimum=next(k for k in range(n+1) if any(all(a in s or b in s for a,b in pairs) for s in map(set,itertools.combinations(range(n),k))))
        path=evidence.folder/f"graph-{i}.txt";path.write_text(f"{n} {len(pairs)}\n"+"".join(f"{a} {b}\n" for a,b in pairs))
        for mode in ["hybrid","stackonly"]:
            def check():
                command=[str(binary),"-f",str(path),"-v",mode,"-q","1024","-c","4096"]
                with (evidence.folder/f"{i}-{mode}.log").open("w") as log:
                    process=subprocess.Popen(command,cwd=evidence.folder,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    try:code=process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait();raise RuntimeError("15-second timeout")
                text=(evidence.folder/f"{i}-{mode}.log").read_text(errors="replace")
                match=re.search(r"Size of minimum vertex cover:\s*(\d+)",text)
                actual=int(match[1]) if match else None
                assert code==0 and actual==optimum,{"exit":code,"observed":actual,"expected":optimum}
                return {"observed":actual,"expected":optimum,"command":command}
            evidence.case("component-aware-mvc-"+mode,str(i),"Exact optimum SIZE vs exhaustive subsets; upstream exports no cover witness",{"n":n,"edges":pairs},check)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("family",choices=["pyg","knn","faiss","models","hypergraph","eigen","persistence","mvc"])
    parser.add_argument("--gpu",default="0");args=parser.parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"]=args.gpu
    os.environ["OMP_NUM_THREADS"]="2"
    evidence=Evidence(args.family,args.gpu)
    try:globals()[args.family](evidence)
    except Exception:
        evidence.finish(traceback.format_exc());raise
    else:evidence.finish()


if __name__=="__main__":main()
