Self-trained neural vertex-cover heuristic
==========================================

Problem: [Minimum Vertex Cover](../../problem.json).

The authors repository includes a separate MVC adaptation. It combines CPU branching with GPU neural scoring; minimum size is not certified.

GPU execution: Hybrid NumPy/NetworkX graph transformations and PyTorch CUDA inference.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/2310.18672
Source: https://github.com/LIONS-EPFL/dynamic-MIS
Pinned commit: `32462fa7fb4bd5c459364a9efb6b749d9c06b53f`.

Implementation paths:

- `code/MVC/model.py`
- `code/MVC/recursion_tree.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
