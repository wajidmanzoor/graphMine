Ripser++
========

Problem: [Flag-Complex Persistent Homology](../../problem.json).

GPU-accelerated Vietoris-Rips/flag persistence. Use supported sparse or distance-matrix input with absent edges represented correctly; verify supported coefficient field and cutoff semantics.

GPU execution: GPU filtration/apparent-pair stages with CPU residual reduction; this is a hybrid algorithm.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2003.07989
Source: https://github.com/simonzhang00/ripser-plusplus
Pinned commit: `30243c0c752de26d7fdf6e41f08bf7b840ca4744`.

Implementation paths:

- `code/ripserplusplus/ripser++.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
