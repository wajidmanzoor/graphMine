Spectral Graph Sparsification
=============================

Construct a sparse reweighted subgraph approximating the quadratic form of a weighted undirected graph Laplacian.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 2 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2024_ingrass_candidate](papers/2024_ingrass_candidate/README.md) | local | missing | no |
| [2025_dygrass_decremental](papers/2025_dygrass_decremental/README.md) | local | local | yes |
| [2025_dygrass_incremental](papers/2025_dygrass_incremental/README.md) | local | local | yes |

dyGRASS incremental and decremental variants require an initial sparsifier. No third licensed GPU source-and-paper pair was verified; GraphSlim sparsification uses CPU NetworKit.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
