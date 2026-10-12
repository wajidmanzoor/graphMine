PyTorch Cluster kNN graph
=========================

Problem: [k-Nearest-Neighbor Graph Construction](../../problem.json).

CUDA nearest-neighbor graph operator used by the PyG ecosystem. Respect the pinned kernel k limit, batch partitioning, distance convention and self-loop flag.

GPU execution: CUDA kNN kernel selected for CUDA-resident tensors.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1903.02428
Source: https://github.com/rusty1s/pytorch_cluster
Pinned commit: `e9a855c284b45edcbf0282cf70ac09bee0ce4e49`.

Implementation paths:

- `code/torch_cluster/knn.py`
- `code/csrc/cuda/knn_cuda.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
