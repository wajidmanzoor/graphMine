DeepHypergraph HYPERGCN
=======================

Problem: [Hypergraph Node Classification and Regression](../../problem.json).

Hypergraph node-learning model on native incidence data. The model-specific propagation or mediator expansion is explicit; choose CUDA for both model and hypergraph tensors.

GPU execution: PyTorch sparse/dense CUDA operations; CPU dataset preparation and training orchestration.

Paper relationship: algorithm.
Paper: https://papers.nips.cc/paper/2019/hash/1efa39bcaec6f3900149160693694536-Abstract.html
Source: https://github.com/iMoonLab/DeepHypergraph
Pinned commit: `b4f80211c2173b890d2779539683a3a65c4648ac`.

Implementation paths:

- `code/dhg/models/hypergraphs/hypergcn.py`
- `code/dhg/structure/hypergraphs/hypergraph.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
