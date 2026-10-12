Gunrock max-flow-based sparse fused lasso
=========================================

Legacy CUDA graph operations with max-flow subproblems.

This is sparse fused lasso, not an ADMM implementation. The Gunrock report finds a serial normalization bottleneck and no multi-GPU benefit. Extra vertex sparsity penalty differs from the default TV contract. Retained for research, not recommended as a proven GPU speedup.

Collection status: shortfall or related artifact; see details below.

Paper role: `algorithm_background`.

[Publication](https://arxiv.org/abs/1410.7690) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/gunrock/gunrock) · [Local source snapshot](code/)

Snapshot: `386d04450b9ae11097e9789a648042d4d310f199`. Full provenance: [source manifest](../../../_sources/gunrock_legacy.json).

Implementation entry points:

- [gunrock/app/gtf/gtf_enactor.cuh](code/gunrock/app/gtf/gtf_enactor.cuh)
- [gunrock/app/gtf/gtf_problem.cuh](code/gunrock/app/gtf/gtf_problem.cuh)
- [gunrock/app/gtf/gtf_app.cu](code/gunrock/app/gtf/gtf_app.cu)

[Supporting documentation](https://gunrock.github.io/gunrock/gunrock.wiki/darpa_hive/phase_2/hive_sparse_graph_trend_filtering_phase2.html)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
