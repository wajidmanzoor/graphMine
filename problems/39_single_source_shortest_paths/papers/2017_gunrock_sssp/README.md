Gunrock frontier-based weighted relaxation
==========================================

CUDA frontier expansion with atomic distance relaxation.

The paper describes the Gunrock framework. This pinned implementation is a later revision, not the exact artifact evaluated in the 2017 paper. Use nonnegative weights and verify predecessor output before exposing it.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1701.01170) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `748f79e66cc26762cd3f99422b028e742a737bde`. Full provenance: [source manifest](../../../_sources/gunrock.json).

Implementation entry points:

- [include/gunrock/algorithms/sssp.hxx](code/include/gunrock/algorithms/sssp.hxx)
- [examples/algorithms/sssp/sssp.cu](code/examples/algorithms/sssp/sssp.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
