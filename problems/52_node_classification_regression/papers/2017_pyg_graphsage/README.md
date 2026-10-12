GraphSAGE node classification
=============================

PyTorch CUDA sampled-neighborhood aggregation and training.

Original GraphSAGE paper; PyG example. Sampling can run on CPU depending on loader configuration; do not describe the whole pipeline as GPU-resident.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1706.02216) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [torch_geometric/nn/conv/sage_conv.py](code/torch_geometric/nn/conv/sage_conv.py)
- [examples/reddit.py](code/examples/reddit.py)

[Supporting framework paper](https://arxiv.org/abs/1903.02428) · [Local PDF](pyg_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
