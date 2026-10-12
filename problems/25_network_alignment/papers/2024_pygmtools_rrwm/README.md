pygmtools RRWM
==============

Problem: [Pairwise Network Alignment](../../problem.json).

Quadratic graph matching using an explicit node/edge affinity tensor. Different solver entrypoints share the same backend file. Discretization can use a CPU Hungarian step; an affinity definition and a mapping adapter are required. This is network alignment, not a certified GED solver.

GPU execution: PyTorch solver iterations can run on CUDA; affinity preparation and Hungarian discretization may use CPU.

Paper relationship: framework.
Paper: https://jmlr.org/papers/v25/23-0572.html
Source: https://github.com/Thinklab-SJTU/pygmtools
Pinned commit: `5b7b3f84a34528e455a6df6404822c306aa45dc1`.

Implementation paths:

- `code/pygmtools/classic_solvers.py`
- `code/pygmtools/pytorch_backend.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
