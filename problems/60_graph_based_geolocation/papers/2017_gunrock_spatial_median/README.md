Gunrock spatial-median propagation
==================================

CUDA neighbor-location aggregation and spatial-median iterations.

The paper describes the Gunrock framework. This pinned implementation is a later revision, not the exact artifact evaluated in the 2017 paper. Method details are in the linked HIVE report, not in the framework paper. Keep social-graph propagation distinct from learned IP-network geolocation.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1701.01170) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `748f79e66cc26762cd3f99422b028e742a737bde`. Full provenance: [source manifest](../../../_sources/gunrock.json).

Implementation entry points:

- [include/gunrock/algorithms/geo.hxx](code/include/gunrock/algorithms/geo.hxx)
- [examples/algorithms/geo/geo.cu](code/examples/algorithms/geo/geo.cu)

[Supporting documentation](https://gunrock.github.io/gunrock/gunrock.wiki/darpa_hive/phase_2/hive_geolocation_phase2.html)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
