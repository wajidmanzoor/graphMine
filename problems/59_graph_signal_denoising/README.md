Graph Signal Denoising and Trend Filtering
==========================================

Estimate a vertex signal from noisy observations using a declared graph-difference regularizer.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 0 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2014_gtf_admm](papers/2014_gtf_admm/README.md) | local | missing | no |
| [2014_gtf_projected_newton](papers/2014_gtf_projected_newton/README.md) | local | missing | no |
| [2014_gunrock_sparse_fused_lasso](papers/2014_gunrock_sparse_fused_lasso/README.md) | local | local | no |

No complete matching GPU graph-signal denoising solver was verified. Sparse fused-lasso primitives and learned node classifiers do not establish the specified denoising objective.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
