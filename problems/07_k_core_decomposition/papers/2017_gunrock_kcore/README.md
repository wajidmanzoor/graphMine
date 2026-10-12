Gunrock kcore
=============

Problem: [k-Core Decomposition](../../problem.json).

Core decomposition for simple undirected graphs. Paired with the Gunrock framework publication.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1701.01170
Source: https://github.com/gunrock/gunrock
Pinned commit: `748f79e66cc26762cd3f99422b028e742a737bde`.

Implementation paths:

- `code/include/gunrock/algorithms/kcore.hxx`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
