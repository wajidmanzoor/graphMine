Skywalker alias-method neighbor sampling
========================================

CUDA weighted alias tables and parallel neighbor selection.

Select the neighbor-sampling mode. Check the upstream newsampler flag and result-layout notes in README.md.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://ieeexplore.ieee.org/document/9563020) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/sjtu-SAIL-lab/Skywalker) · [Local source snapshot](code/)

Snapshot: `b12bb95d01c5feabb69699985b85a6ea3cbdc944`. Full provenance: [source manifest](../../../_sources/skywalker.json).

Implementation entry points:

- [src/main.cu](code/src/main.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
