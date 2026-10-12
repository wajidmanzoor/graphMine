cuVS GPU NN-Descent
===================

Problem: [k-Nearest-Neighbor Graph Construction](../../problem.json).

Approximate kNN graph construction; recall must be measured. The cuVS implementation cites GPU NN-Descent. CAGRA navigation-graph pruning is not treated as an exact kNN output.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://doi.org/10.1145/3459637.3482344
Source: https://github.com/rapidsai/cuvs
Pinned commit: `24b0b17069ee1547354d15847d9c614dd4fb4a43`.

Implementation paths:

- `code/cpp/src/neighbors/nn_descent.cu`
- `code/cpp/src/neighbors/detail/nn_descent.cuh`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
