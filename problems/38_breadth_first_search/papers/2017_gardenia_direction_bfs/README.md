GARDENIA direction-optimizing BFS
=================================

CUDA push/pull traversal and degree-aware work distribution.

Benchmark-suite paper; select CUDA targets because this repository also includes CPU implementations.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1708.04567) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/chenxuhao/gardenia) · [Local source snapshot](code/)

Snapshot: `5894df11cf47f8839945edadff43dc79e260216d`. Full provenance: [source manifest](../../../_sources/gardenia.json).

Implementation entry points:

- [src/bfs/hybrid_lb.cu](code/src/bfs/hybrid_lb.cu)
- [src/bfs/bottom_up.cu](code/src/bfs/bottom_up.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
