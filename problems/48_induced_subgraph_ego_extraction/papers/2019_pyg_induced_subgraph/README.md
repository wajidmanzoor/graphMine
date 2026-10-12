PyG mask-based induced subgraph
===============================

PyTorch indexing/masking runs on CUDA when edge_index and subset tensors are on CUDA.

Entry function subgraph. This is a framework implementation and its framework paper, not a separate extraction research paper.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1903.02428) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [torch_geometric/utils/_subgraph.py](code/torch_geometric/utils/_subgraph.py)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
