Gunrock accelerated regularized PageRank diffusion
==================================================

CUDA gradient/proximal diffusion kernels.

Returns diffusion scores. A verified conductance sweep and seed-community result are missing; not a complete local-community implementation.

Collection status: shortfall or related artifact; see details below.

Paper role: `framework`.

[Publication](https://arxiv.org/abs/1701.01170) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `386d04450b9ae11097e9789a648042d4d310f199`. Full provenance: [source manifest](../../../_sources/gunrock_legacy.json).

Implementation entry points:

- [gunrock/app/pr_nibble/pr_nibble_enactor.cuh](code/gunrock/app/pr_nibble/pr_nibble_enactor.cuh)
- [gunrock/app/pr_nibble/pr_nibble_app.cu](code/gunrock/app/pr_nibble/pr_nibble_app.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
