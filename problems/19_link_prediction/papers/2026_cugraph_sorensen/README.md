cuGraph Sorensen-Dice link scores
=================================

Problem: [Link Prediction](../../problem.json).

Score 2|N(u) intersect N(v)|/(deg(u)+deg(v)); this is a link-scoring variant, not SimRank. No associated GPU research paper was verified for this specific implementation; documentation is retained as documentation.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: none.
Paper: No associated research paper verified.
Source: https://github.com/rapidsai/cugraph
Pinned commit: `5931900cf6be7063cf855ef230fa14d4216b61de`.

Implementation paths:

- `code/cpp/src/link_prediction/sorensen_impl.cuh`

Artifact state: paper=not_collected; code=downloaded_archive.
Counts toward three local pairs: false.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
