GraphSlim DOSCOND
=================

Problem: [Learned Graph Condensation](../../problem.json).

GPU graph condensation implementation. GraphSlim adapts one-step gradient matching to its node-learning pipeline; this is not a claim of reproducing every original graph-classification experiment. Synthetic graph utility must be measured under a fixed train/validation/test protocol. GraphSlim CPU sparsification routines are not GPU spectral sparsifiers.

GPU execution: PyTorch CUDA optimization when the device is configured; preprocessing and evaluation orchestration may use CPU.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2206.07746
Source: https://github.com/Emory-Melody/GraphSlim
Pinned commit: `2a120ed49e501a39a7c94bdabfc4c33c8c032235`.

Implementation paths:

- `code/graphslim/condensation/doscond.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
