PyGOD COLA
==========

Problem: [Graph Anomaly Detection](../../problem.json).

Attributed-graph node anomaly scores. This CoLA library variant uses neighbor sampling instead of the original paper random walks. GPU selection is explicit: the default gpu=-1 uses CPU. The PDF is the PyGOD framework paper, shared by three distinct models.

GPU execution: PyTorch/PyG tensor operations on CUDA when gpu>=0; preprocessing and sampling can include CPU stages.

Paper relationship: framework.
Paper: https://jmlr.org/papers/v25/23-0963.html
Source: https://github.com/pygod-team/pygod
Pinned commit: `c84dccafa9bf587cd03cfd3e89b9be7a8f3337e8`.

Implementation paths:

- `code/pygod/detector/cola.py`
- `code/pygod/nn/cola.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
