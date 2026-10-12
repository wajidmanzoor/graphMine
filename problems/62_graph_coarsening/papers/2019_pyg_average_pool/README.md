PyG quotient construction with average feature pooling
======================================================

Problem: [Graph Coarsening and Quotient Construction](../../problem.json).

Uses a supplied assignment and tensor scatter/coalesce to form a pooled graph. Select mean feature aggregation and drop internal self-loops to match upstream behavior; cluster assignment generation is separate.

GPU execution: PyTorch scatter/coalesce operations on CUDA when graph tensors are CUDA-resident.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1903.02428
Source: https://github.com/pyg-team/pytorch_geometric
Pinned commit: `79d33965a40b7fa83616a9f598a0f8619f25d939`.

Implementation paths:

- `code/torch_geometric/nn/pool/avg_pool.py`
- `code/torch_geometric/nn/pool/pool.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
