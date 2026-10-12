dyGRASS incremental spectral sparsifier updates
===============================================

CUDA non-backtracking walks for inserted-edge updates; Julia/CPU spectral work.

Requires the dynamic-update mode, an initial sparsifier and insertion updates. Not a standalone from-scratch static sparsifier; condition-number diagnostics are not a universal epsilon certificate.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2505.02741) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/Feng-Research/dyGRASS) · [Local source snapshot](code/)

Snapshot: `3a69c8b45bf044fbf3b60b47cb5efa8c40576691`. Full provenance: [source manifest](../../../_sources/dygrass.json).

Implementation entry points:

- [random_walk_incremental/main.cu](code/random_walk_incremental/main.cu)
- [random_walk_incremental/functions.cpp](code/random_walk_incremental/functions.cpp)
- [dyGRASS.jl](code/dyGRASS.jl)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
