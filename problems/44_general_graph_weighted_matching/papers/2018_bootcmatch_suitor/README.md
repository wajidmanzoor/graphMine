BootCMatchG GPU Suitor weighted matching
========================================

CUDA approximate weighted matching inside an algebraic multigrid pipeline.

The kernel is reusable but the executable solves AMG systems. A standalone graph adapter must supply original graph weights and expose the matching, rather than AMG-generated weights.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1810.04221) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/bootcmatch/BootCMatchG) · [Local source snapshot](code/)

Snapshot: `e4636be918902feeb8dde63f3c5ee207ae3a5d94`. Full provenance: [source manifest](../../../_sources/bootcmatch.json).

Implementation entry points:

- [src/AMG/suitor.cu](code/src/AMG/suitor.cu)
- [src/AMG/matchingAggregation.cu](code/src/AMG/matchingAggregation.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
