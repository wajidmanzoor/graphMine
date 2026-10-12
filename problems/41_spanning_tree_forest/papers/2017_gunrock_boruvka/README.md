Gunrock Boruvka-style minimum spanning tree
===========================================

CUDA component-minimum selection and merging.

The paper describes the Gunrock framework. This pinned implementation is a later revision, not the exact artifact evaluated in the 2017 paper. Verify disconnected-input handling; maximum forests require a supported weight transformation.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1701.01170) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `748f79e66cc26762cd3f99422b028e742a737bde`. Full provenance: [source manifest](../../../_sources/gunrock.json).

Implementation entry points:

- [include/gunrock/algorithms/mst.hxx](code/include/gunrock/algorithms/mst.hxx)
- [examples/algorithms/mst/mst.cu](code/examples/algorithms/mst/mst.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
