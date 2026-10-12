AxonCUDA constrained hypergraph partitioning
============================================

CUDA coarsening/refinement under incidence and size constraints.

Use the k-way mode for the balanced-partition contract. Upstream k-way mode uses Mt-KaHyPar on CPU for initial partitioning; the default incidence-constrained objective is a different variant.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2605.20497) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/EMJzero/AxonCUDA) · [Local source snapshot](code/)

Snapshot: `48bf283f7a370f57bacd7e88677fb4e099bb7f8a`. Full provenance: [source manifest](../../../_sources/axon_cuda.json).

Implementation entry points:

- [sources/main.cu](code/sources/main.cu)
- [sources/coarsening.cu](code/sources/coarsening.cu)
- [sources/refinement.cu](code/sources/refinement.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
