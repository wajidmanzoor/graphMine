dyGRASS decremental spectral sparsifier updates
===============================================

CUDA localized random walks for edge-deletion updates.

Deletion-specific algorithm in the same paper as incremental dyGRASS. Use the dynamic-update mode with an initial sparsifier and deletion updates; preprocessing and spectral analysis include CPU stages.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2505.02741) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/Feng-Research/dyGRASS) · [Local source snapshot](code/)

Snapshot: `3a69c8b45bf044fbf3b60b47cb5efa8c40576691`. Full provenance: [source manifest](../../../_sources/dygrass.json).

Implementation entry points:

- [random_walk_decremental/main.cu](code/random_walk_decremental/main.cu)
- [random_walk_decremental/functions.cpp](code/random_walk_decremental/functions.cpp)
- [dyGRASS.jl](code/dyGRASS.jl)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
