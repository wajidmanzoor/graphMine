GCN node classification
=======================

PyTorch CUDA graph convolution and training.

Original GCN paper; PyG implementation. Provided example is classification. Regression requires a suitable output head and loss.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1609.02907) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [torch_geometric/nn/conv/gcn_conv.py](code/torch_geometric/nn/conv/gcn_conv.py)
- [examples/gcn.py](code/examples/gcn.py)

[Supporting framework paper](https://arxiv.org/abs/1903.02428) · [Local PDF](pyg_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
