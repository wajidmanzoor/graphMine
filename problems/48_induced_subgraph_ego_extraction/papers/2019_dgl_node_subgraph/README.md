DGL sparse graph slicing for induced subgraphs
==============================================

DGL CUDA sparse-matrix slicing on a graph stored on a CUDA device.

Entry function node_subgraph. Preserve relabeling maps and copied feature identities. Framework paper.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1909.01315) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/dmlc/dgl) · [Local source snapshot](code/)

Snapshot: `3d16000b4170fa741ed9e9667f22ba84d3493026`. Full provenance: [source manifest](../../../_sources/dgl.json).

Implementation entry points:

- [python/dgl/subgraph.py](code/python/dgl/subgraph.py)
- [src/array/cuda/spmat_op_impl_csr.cu](code/src/array/cuda/spmat_op_impl_csr.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
