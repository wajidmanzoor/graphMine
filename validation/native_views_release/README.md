# CPU graph-view runtime release — 2026-11-16

This release builds the completed Steps 1–3 source at `adce2c72` as a pinned native runtime for production. It retains the existing GPU adapters; later GPU graph-view migration work remains paused. Application branches receive this release's evidence and deployment documentation together.

The final build has 82 verified CPU operations and all 59 existing GPU profiles across 36 operations. Source, binary, worker, dependency and report hashes match the execution gate. See [summary.json](summary.json), [capabilities.json](capabilities.json), and the repository's `catalog/native_execution_evidence.json`.

Validation passed: 53 CTests; 161 CPU completion tests; 43 CPU binding checks; 129,073 CPU native oracle requests; and 44,884 native oracle requests on each GPU. The extension suites passed 34 tests on GPU 1 and 33 on GPU 0, with the resource-limited case described below excluded from GPU 0 admission.

## Existing GPU memory limitation

The unchanged `mbe-gpu` maximal-biclique-counting worker reserves 11,427,905,536 bytes (about 10.64 GiB) for its fixed scratch buffer, in addition to its other allocations. It runs out of memory on GPU 0 while the production LLM remains loaded, including an isolated-process retry after other oracle workers exited. It passes on GPU 1. Failed full-suite and isolated reports are retained in [resource-contention](resource-contention/context.json), and never used as passing evidence. That backend is admitted only for GPU 1; all other existing GPU profiles are verified on both cards. CPU maximal-biclique counting remains available. This deployment preserves the existing shared-GPU configuration and keeps vLLM running.

## Build and recovery details

The previous `/tmp/pggc-deps/install` dependency files had been cleared. The first build therefore omitted parallel Louvain/Leiden despite their configured options. That build's interrupted validation is retained under [preliminary-missing-pggc](preliminary-missing-pggc/README.md) and is excluded from admission.

The final build restores CUDA-enabled, position-independent Kokkos and KokkosKernels 4.7.00 in `library/build/native-dependencies/`, with source URLs and archive hashes in [dependency-sources.json](dependency-sources.json). Reproduction commands are in [dependency-build-commands.json](dependency-build-commands.json) and [build-configuration-final.json](build-configuration-final.json). The compiled GPU profile inventory was checked against the previous runtime before validation restarted.

Production and testing use separate data stores. The deployment controller records final application checks, authenticated acceptance, the production data snapshot and promotion privately under `graphmine-data/environments/state/`. Existing models, conversations and datasets are preserved.
