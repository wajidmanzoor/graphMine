GARDENIA speculative greedy coloring
====================================

CUDA tentative coloring and conflict resolution.

Distance-1 coloring. Several CUDA schedules are included; they are one algorithm entry here.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1606.06025) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/chenxuhao/gardenia) · [Local source snapshot](code/)

Snapshot: `5894df11cf47f8839945edadff43dc79e260216d`. Full provenance: [source manifest](../../../_sources/gardenia.json).

Implementation entry points:

- [src/vc/linear_bitset.cu](code/src/vc/linear_bitset.cu)
- [src/vc/topo_bitset.cu](code/src/vc/topo_bitset.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
