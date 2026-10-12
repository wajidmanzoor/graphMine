LonestarGPU priority-based MIS
==============================

IrGL-generated CUDA priority selection.

Compiler paper paired with the distributed upstream GPU example; no maximum-cardinality claim.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1607.05707) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/IntelligentSoftwareSystems/Galois) · [Local source snapshot](code/)

Snapshot: `b67f94206a8c47fd414446621f6633a31c49fd98`. Full provenance: [source manifest](../../../_sources/galois.json).

Implementation entry points:

- [lonestar/analytics/gpu/independentset/mis.cu](code/lonestar/analytics/gpu/independentset/mis.cu)
- [lonestar/analytics/gpu/independentset/README.md](code/lonestar/analytics/gpu/independentset/README.md)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
