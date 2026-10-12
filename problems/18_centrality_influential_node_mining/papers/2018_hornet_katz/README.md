Hornet Katz centrality
======================

Problem: [Centrality and Influential-Node Mining](../../problem.json).

Katz iteration with declared attenuation and stopping rule. The associated PDF describes the Hornet GPU framework; it is not a separate paper for each routine.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://davidbader.net/publication/2018-bgbb/
Source: https://github.com/hornet-gt/hornet
Pinned commit: `2441ccabd44a09dbf16f521dbd0bc856ab5001f8`.

Implementation paths:

- `code/hornetsnest/src/Static/KatzCentrality/Katz.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
