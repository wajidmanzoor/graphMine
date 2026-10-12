GraphBLAST independent-set coloring
===================================

CUDA GraphBLAS repeated parallel color assignment.

Distance-1 heuristic; does not establish a chromatic-number optimum or distance-2 support.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1908.01407) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/graphblast) · [Local source snapshot](code/)

Snapshot: `f56f9677276c574c6fe4f1cc104d51f13717e165`. Full provenance: [source manifest](../../../_sources/graphblast.json).

Implementation entry points:

- [graphblas/algorithm/gc.hpp](code/graphblas/algorithm/gc.hpp)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
