GAT node classification
=======================

PyTorch CUDA attention, scatter, and training.

Original GAT paper; PyG implementation. Feature tensors, graph indices, and model must share the CUDA device.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1710.10903) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [torch_geometric/nn/conv/gat_conv.py](code/torch_geometric/nn/conv/gat_conv.py)
- [examples/gat.py](code/examples/gat.py)

[Supporting framework paper](https://arxiv.org/abs/1903.02428) · [Local PDF](pyg_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
