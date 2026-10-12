Skywalker alias-table random walks
==================================

CUDA alias-method sampling with load balancing.

Select DeepWalk or node2vec modes. Later Skywalker+ extensions also exist in this snapshot; the attached PACT paper describes the original framework.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://ieeexplore.ieee.org/document/9563020) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/sjtu-SAIL-lab/Skywalker) · [Local source snapshot](code/)

Snapshot: `b12bb95d01c5feabb69699985b85a6ea3cbdc944`. Full provenance: [source manifest](../../../_sources/skywalker.json).

Implementation entry points:

- [src/main.cu](code/src/main.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
