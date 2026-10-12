DiffPool graph classification
=============================

PyTorch CUDA differentiable dense pooling.

Original model paper and upstream classification example. Dense intermediate adjacency can limit graph size.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1806.08804) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/pyg-team/pytorch_geometric) · [Local source snapshot](code/)

Snapshot: `79d33965a40b7fa83616a9f598a0f8619f25d939`. Full provenance: [source manifest](../../../_sources/pyg.json).

Implementation entry points:

- [benchmark/kernel/diff_pool.py](code/benchmark/kernel/diff_pool.py)
- [examples/proteins_diff_pool.py](code/examples/proteins_diff_pool.py)
- [torch_geometric/nn/dense/diff_pool.py](code/torch_geometric/nn/dense/diff_pool.py)

[Supporting framework paper](https://arxiv.org/abs/1903.02428) · [Local PDF](pyg_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
