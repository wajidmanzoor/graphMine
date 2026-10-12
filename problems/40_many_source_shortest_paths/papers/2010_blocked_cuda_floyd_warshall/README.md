Blocked CUDA Floyd-Warshall (Bojanowski implementation)
=======================================================

Problem: [Many-Source and All-Pairs Shortest Distances](../../problem.json).

Public MIT-licensed third-party implementation explicitly based on Lund and Smith. It is not represented as the paper authors original artifact. Dense integer-distance APSP; check infinity sentinel, overflow and block-size assumptions; selected source/destination pairs are extracted from the full matrix.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/1001.4108
Source: https://github.com/MTB90/cuda-floyd_warshall
Pinned commit: `c21f114eb4da7d4900a6017e293fdb0f43d94141`.

Implementation paths:

- `code/lib/cuda/cuda_apsp.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
