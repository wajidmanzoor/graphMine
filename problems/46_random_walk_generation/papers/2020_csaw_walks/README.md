C-SAW GPU random walks
======================

CUDA sampling with in-memory and streaming execution.

Distribution, walk-length convention, and dead-end behavior need to be mapped to the problem contract.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2009.09103) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/concept-inversion/C-SAW) · [Local source snapshot](code/)

Snapshot: `d91ff3ac896a90a3ea7b71e9251d5e79f67f8c6c`. Full provenance: [source manifest](../../../_sources/csaw.json).

Implementation entry points:

- [non-stream/main.cu](code/non-stream/main.cu)
- [non-stream/sampler.cuh](code/non-stream/sampler.cuh)
- [streaming/streaming_sampling.cu](code/streaming/streaming_sampling.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
