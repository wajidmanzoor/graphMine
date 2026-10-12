Weighted Single-Source Shortest Paths
=====================================

Compute minimum path-weight sums from one source to every vertex in a graph with nonnegative edge weights.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 5 records; 4 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2017_gardenia_delta_stepping](papers/2017_gardenia_delta_stepping/README.md) | local | local | yes |
| [2017_gunrock_sssp](papers/2017_gunrock_sssp/README.md) | local | local | yes |
| [2018_hornet_sssp](papers/2018_hornet_sssp/README.md) | local | local | yes |
| [2019_graphblast_sssp](papers/2019_graphblast_sssp/README.md) | local | local | yes |
| [2026_cugraph_sssp](papers/2026_cugraph_sssp/README.md) | missing | local | no |

The collection target is met for the documented variants.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
