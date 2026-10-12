NextDoor transit-parallel random walks
======================================

CUDA transit-parallel sampling and walk generation.

Collects walk generation, not embedding training. Node2vec and uniform walks are modes within this entry.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2009.06693) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/plasma-umass/NextDoor) · [Local source snapshot](code/)

Snapshot: `dcbc46d60bb9623616a10f5e7518fe5214575226`. Full provenance: [source manifest](../../../_sources/nextdoor.json).

Implementation entry points:

- [src/apps/randomwalks/deepwalk.cu](code/src/apps/randomwalks/deepwalk.cu)
- [src/apps/randomwalks/node2vec.cu](code/src/apps/randomwalks/node2vec.cu)
- [src/apps/randomwalks/randomWalks.cu](code/src/apps/randomwalks/randomWalks.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
