Gunrock connected components
============================

Problem: [Connected Components (Weakly and Strongly Connected)](../../problem.json).

Legacy Gunrock connected-components implementation for the undirected/weak-connectivity variant.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1701.01170
Source: https://github.com/gunrock/gunrock
Pinned commit: `386d04450b9ae11097e9789a648042d4d310f199`.

Implementation paths:

- `code/gunrock/app/cc/cc_enactor.cuh`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
