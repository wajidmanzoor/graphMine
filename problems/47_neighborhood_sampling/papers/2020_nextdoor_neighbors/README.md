NextDoor transit-parallel neighborhood sampling
===============================================

CUDA transit-parallel k-hop and layer sampling.

Finite-fanout sampling is not exact induced ego-graph extraction. Replacement and fanout conventions must be declared.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2009.06693) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/plasma-umass/NextDoor) · [Local source snapshot](code/)

Snapshot: `dcbc46d60bb9623616a10f5e7518fe5214575226`. Full provenance: [source manifest](../../../_sources/nextdoor.json).

Implementation entry points:

- [src/apps/khop/khop.cu](code/src/apps/khop/khop.cu)
- [src/apps/layer/layerSampling.cu](code/src/apps/layer/layerSampling.cu)
- [src/sampler.cuh](code/src/sampler.cuh)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
