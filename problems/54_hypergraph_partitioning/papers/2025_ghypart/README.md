gHyPart multilevel hypergraph partitioning
==========================================

CUDA multilevel coarsening, partitioning, and refinement.

Source downloaded; public publisher PDF retrieval failed. Verified DOI retained. CPU baselines bundled in this repository are not additional GPU algorithms.

Collection status: shortfall or related artifact; see details below.

Paper role: `algorithm`.

[Publication](https://doi.org/10.1145/3711925) · Local PDF unavailable; see artifact_status.json.

[Upstream source](https://github.com/zlwu92/gHyPart_TACO) · [Local source snapshot](code/)

Snapshot: `97b517195c16afe1a8c46d5e3fc418109ed6972a`. Full provenance: [source manifest](../../../_sources/ghypart.json).

Implementation entry points:

- [main.cu](code/main.cu)
- [no_uvm_impl/kway_partition_no_uvm.cu](code/no_uvm_impl/kway_partition_no_uvm.cu)
- [kernels/coarsening_kernels.cu](code/kernels/coarsening_kernels.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
