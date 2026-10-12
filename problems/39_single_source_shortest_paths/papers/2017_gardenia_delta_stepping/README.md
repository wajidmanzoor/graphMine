GARDENIA delta-stepping SSSP
============================

CUDA bucketed shortest-path relaxation.

Delta is an implementation tuning parameter. Input conversion must preserve edge weights.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1708.04567) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/chenxuhao/gardenia) · [Local source snapshot](code/)

Snapshot: `5894df11cf47f8839945edadff43dc79e260216d`. Full provenance: [source manifest](../../../_sources/gardenia.json).

Implementation entry points:

- [src/sssp/dstep.cu](code/src/sssp/dstep.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
