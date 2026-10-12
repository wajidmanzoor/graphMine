CuPy Dense Hermitian eigensolver
================================

Problem: [Graph Laplacian Eigenpairs](../../problem.json).

Apply the upstream eigensolver to the explicitly constructed symmetric graph Laplacian. These are three numerical algorithms sharing the CuPy framework paper, not three graph-specific publications. Laplacian assembly and canonical output conversion are adapter requirements; verify residuals and nullspace multiplicity.

GPU execution: CUDA/CuPy matrix operations and device eigensolver routines; iterative control is host-driven.

Paper relationship: framework.
Paper: https://learningsys.github.io/nips17/schedule.html
Source: https://github.com/cupy/cupy
Pinned commit: `379a2bedbca90d59a947d8bc26d02e7378ee1eb0`.

Implementation paths:

- `code/cupy/linalg/_eigenvalue.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
