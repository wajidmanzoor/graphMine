GraphBLAST seeded residual-push PageRank
========================================

Problem: [Personalized PageRank and Random Walk with Restart](../../problem.json).

Single-seed approximate PageRank vector from GPU residual pushing. The source uses a lazy walk: to match ordinary-walk restart probability r, use upstream alpha=r/(2-r). Restrict to undirected graphs with positive degree, report approximation and iteration termination, and check residual/missing mass before claiming the requested tolerance. The routine alone does not return a local community.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1908.01407
Source: https://github.com/gunrock/graphblast
Pinned commit: `f56f9677276c574c6fe4f1cc104d51f13717e165`.

Implementation paths:

- `code/graphblas/algorithm/lgc.hpp`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
