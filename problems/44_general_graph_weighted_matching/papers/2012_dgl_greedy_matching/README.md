DGL weighted neighbor matching
==============================

Problem: [General-Graph Weighted Matching](../../problem.json).

Independent DGL CUDA implementation of the same Auer-Bisseling greedy matching publication used by PyTorch Cluster. Pair/singleton cluster IDs require output conversion.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://research-portal.uu.nl/en/publications/a-gpu-algorithm-for-greedy-graph-matching
Source: https://github.com/dmlc/dgl
Pinned commit: `3d16000b4170fa741ed9e9667f22ba84d3493026`.

Implementation paths:

- `code/python/dgl/geometry/edge_coarsening.py`
- `code/src/geometry/cuda/edge_coarsening_impl.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
