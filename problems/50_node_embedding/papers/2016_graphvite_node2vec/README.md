GraphVite node2vec
==================

GraphVite CPU/GPU hybrid pipeline with CUDA embedding optimization.

Original model paper plus GraphVite framework paper. CPU sampling/preprocessing is part of the pipeline; this is not an entirely GPU-resident trainer.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1607.00653) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/DeepGraphLearning/graphvite) · [Local source snapshot](code/)

Snapshot: `5aad6dcc5e6318396a13d1c6a05f44a833b9c3bc`. Full provenance: [source manifest](../../../_sources/graphvite.json).

Implementation entry points:

- [include/instance/graph.cuh](code/include/instance/graph.cuh)
- [include/instance/gpu/graph.cuh](code/include/instance/gpu/graph.cuh)
- [python/graphvite/solver.py](code/python/graphvite/solver.py)

[Supporting framework paper](https://arxiv.org/abs/1903.00757) · [Local PDF](graphvite_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
