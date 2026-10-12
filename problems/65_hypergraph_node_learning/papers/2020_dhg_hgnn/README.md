DeepHypergraph HGNN
===================

Problem: [Hypergraph Node Classification and Regression](../../problem.json).

Hypergraph node-learning model on native incidence data. The model-specific propagation or mediator expansion is explicit; choose CUDA for both model and hypergraph tensors.

GPU execution: PyTorch sparse/dense CUDA operations; CPU dataset preparation and training orchestration.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/1809.09401
Source: https://github.com/iMoonLab/DeepHypergraph
Pinned commit: `b4f80211c2173b890d2779539683a3a65c4648ac`.

Implementation paths:

- `code/dhg/models/hypergraphs/hgnn.py`
- `code/dhg/structure/hypergraphs/hypergraph.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
