Seeded Local Community Detection
================================

Find a nontrivial low-conductance vertex subset containing a specified seed set.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 0 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2017_gunrock_ppr](papers/2017_gunrock_ppr/README.md) | local | local | no |
| [2017_gunrock_regularized_ppr](papers/2017_gunrock_regularized_ppr/README.md) | local | local | no |
| [2019_graphblast_lgc](papers/2019_graphblast_lgc/README.md) | local | local | no |

PPR/diffusion kernels omit the required seed-containing conductance sweep and community result. They remain building blocks, not complete local-community algorithms.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
