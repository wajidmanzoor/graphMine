GraphBLAST tc
=============

Problem: [Triangle Counting and Listing](../../problem.json).

Triangle count expressed as sparse linear algebra. This is a framework-paper pairing.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1908.01407
Source: https://github.com/gunrock/graphblast
Pinned commit: `f56f9677276c574c6fe4f1cc104d51f13717e165`.

Implementation paths:

- `code/graphblas/algorithm/tc.hpp`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
