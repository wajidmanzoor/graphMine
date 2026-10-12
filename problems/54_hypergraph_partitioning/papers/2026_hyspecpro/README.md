HySpecPro
=========

Problem: [Balanced Hypergraph Partitioning](../../problem.json).

GPU spectral-projection hypergraph bipartitioning. The public driver supports two-way partitioning; do not claim arbitrary k-way support or exact optimization.

GPU execution: PyTorch sparse and dense optimization on CUDA; Python orchestration and input loading remain on CPU.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2607.00055
Source: https://github.com/NVlabs/HySpecPro
Pinned commit: `1e9db172ce26a33be394369c94bedfba913ca41a`.

Implementation paths:

- `code/HySpecPro.py`
- `code/helper.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
