Gunrock personalized PageRank diffusion
=======================================

CUDA personalized PageRank primitive.

The paper describes the Gunrock framework. This pinned implementation is a later revision, not the exact artifact evaluated in the 2017 paper. Diffusion building block only; overlaps the existing PPR family. A community-selection stage is required.

Collection status: shortfall or related artifact; see details below.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1701.01170) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `748f79e66cc26762cd3f99422b028e742a737bde`. Full provenance: [source manifest](../../../_sources/gunrock.json).

Implementation entry points:

- [include/gunrock/algorithms/ppr.hxx](code/include/gunrock/algorithms/ppr.hxx)
- [examples/algorithms/ppr/ppr.cu](code/examples/algorithms/ppr/ppr.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
