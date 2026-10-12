GraphBLAST residual-push local diffusion
========================================

CUDA GraphBLAS residual-push personalized PageRank.

lgc outputs PageRank scores, not a selected community. No conductance sweep exists in this routine; excluded from the complete-solver count.

Collection status: shortfall or related artifact; see details below.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1908.01407) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/graphblast) · [Local source snapshot](code/)

Snapshot: `f56f9677276c574c6fe4f1cc104d51f13717e165`. Full provenance: [source manifest](../../../_sources/graphblast.json).

Implementation entry points:

- [graphblas/algorithm/lgc.hpp](code/graphblas/algorithm/lgc.hpp)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
