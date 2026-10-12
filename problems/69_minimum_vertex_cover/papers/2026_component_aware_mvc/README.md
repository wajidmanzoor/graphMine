Component-aware GPU vertex cover
================================

Problem: [Minimum Vertex Cover](../../problem.json).

Author implementation of exact and parameterized vertex-cover search with component-aware branching. The CLI reports optimum size/decision; a witness set is not guaranteed by its current interface.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2512.18334
Source: https://github.com/HusseinAmro/component-aware-vertex-cover-gpu
Pinned commit: `9adba41659d320ca2fd0e01c6907916db1f4fdf5`.

Implementation paths:

- `code/src/main.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
