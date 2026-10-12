Dynamic programming self-trained MIS
====================================

Problem: [Maximum Independent Set](../../problem.json).

Learned heuristic for maximum-cardinality independent sets. CPU graph recursion calls a CUDA neural comparator. No optimality certificate is supplied.

GPU execution: Hybrid NetworkX/NumPy recursion with PyTorch CUDA neural inference.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2310.18672
Source: https://github.com/LIONS-EPFL/dynamic-MIS
Pinned commit: `32462fa7fb4bd5c459364a9efb6b749d9c06b53f`.

Implementation paths:

- `code/MIS/model.py`
- `code/MIS/recursive_tree.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
