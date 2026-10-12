nvGRAPH max-min widest path
===========================

Problem: [Single-Source Widest Paths](../../problem.json).

Archived NVIDIA nvGRAPH source implements max-min path relaxation. The CUDA library manual documents the operation but is not a research paper.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: none.
Paper: No associated research paper verified.
Source: https://github.com/rapidsai/nvgraph
Pinned commit: `1ea93b51387bd3ff149b6ac8fa91d64edd43d31c`.

Implementation paths:

- `code/cpp/src/widest_path.cu`

Artifact state: paper=not_collected; code=downloaded_archive.
Counts toward three local pairs: false.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
