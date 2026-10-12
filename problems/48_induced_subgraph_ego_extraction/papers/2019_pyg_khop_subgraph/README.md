PyG frontier-expansion k-hop subgraph
=====================================

CUDA tensor frontier expansion followed by edge masking.

Entry function k_hop_subgraph. Flow direction and directed flag affect semantics; directed=False retains all edges among the selected nodes. Separate algorithm from direct mask extraction, same framework paper.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1903.02428) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [torch_geometric/utils/_subgraph.py](code/torch_geometric/utils/_subgraph.py)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
