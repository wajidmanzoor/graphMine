PyTorch Cluster weighted greedy matching
========================================

Problem: [General-Graph Weighted Matching](../../problem.json).

CUDA randomized red/blue greedy matching from the paper cited by upstream. Cluster IDs encode matched pairs or singletons; select the weighted mode and reconstruct pair endpoints.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://research-portal.uu.nl/en/publications/a-gpu-algorithm-for-greedy-graph-matching
Source: https://github.com/rusty1s/pytorch_cluster
Pinned commit: `e9a855c284b45edcbf0282cf70ac09bee0ce4e49`.

Implementation paths:

- `code/torch_cluster/graclus.py`
- `code/csrc/cuda/graclus_cuda.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
