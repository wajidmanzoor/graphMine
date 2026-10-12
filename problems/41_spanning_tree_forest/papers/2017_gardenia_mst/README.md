GARDENIA GPU minimum spanning tree
==================================

CUDA minimum-edge selection and component merging.

Minimum-spanning-tree benchmark; disconnected forest behavior and supported weight types need integration checks.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1708.04567) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/chenxuhao/gardenia) · [Local source snapshot](code/)

Snapshot: `5894df11cf47f8839945edadff43dc79e260216d`. Full provenance: [source manifest](../../../_sources/gardenia.json).

Implementation entry points:

- [src/mst/main.cu](code/src/mst/main.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
