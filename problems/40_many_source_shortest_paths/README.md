Many-Source and All-Pairs Shortest Distances
============================================

Compute a matrix of minimum path-weight sums for selected origins and destinations, including all-pairs queries.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 4 records; 3 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2010_blocked_cuda_floyd_warshall](papers/2010_blocked_cuda_floyd_warshall/README.md) | local | local | yes |
| [2023_tensor_floyd_warshall](papers/2023_tensor_floyd_warshall/README.md) | local | local | yes |
| [2023_tensor_r_kleene](papers/2023_tensor_r_kleene/README.md) | local | local | yes |
| [2026_cugraph_od_distances](papers/2026_cugraph_od_distances/README.md) | missing | local | no |

The collection target is met for the documented variants.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
