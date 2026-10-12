GraphBLAST sparse linear-algebra BFS
====================================

CUDA GraphBLAS Boolean-semiring traversal.

Produces single-source reachability levels; predecessor and cutoff support must be checked by an adapter.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1908.01407) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/graphblast) · [Local source snapshot](code/)

Snapshot: `f56f9677276c574c6fe4f1cc104d51f13717e165`. Full provenance: [source manifest](../../../_sources/graphblast.json).

Implementation entry points:

- [graphblas/algorithm/bfs.hpp](code/graphblas/algorithm/bfs.hpp)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
