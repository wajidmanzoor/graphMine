Faiss GPU exhaustive nearest neighbors
======================================

Problem: [k-Nearest-Neighbor Graph Construction](../../problem.json).

Query every input vector against a GPU flat index and remove its own ID. Distinct vectors with identical values remain valid neighbors. k+1 retrieval and tie handling must preserve k non-self outputs.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: algorithm.
Paper: https://arxiv.org/abs/1702.08734
Source: https://github.com/facebookresearch/faiss
Pinned commit: `07979b10e64d39a611196483f103b2d7b349b5f7`.

Implementation paths:

- `code/faiss/gpu/GpuIndexFlat.cu`
- `code/faiss/gpu/impl/FlatIndex.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
