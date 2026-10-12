General-Graph Weighted Matching
===============================

Find a matching of high total nonnegative edge weight in an undirected graph without a bipartiteness assumption.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 6 records; 3 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2012_dgl_greedy_matching](papers/2012_dgl_greedy_matching/README.md) | local | local | yes |
| [2012_torch_cluster_greedy_matching](papers/2012_torch_cluster_greedy_matching/README.md) | local | local | yes |
| [2015_gpu_suitor_kepler](papers/2015_gpu_suitor_kepler/README.md) | missing | missing | no |
| [2018_bootcmatch_suitor](papers/2018_bootcmatch_suitor/README.md) | local | local | yes |
| [2024_locally_dominant_gpu](papers/2024_locally_dominant_gpu/README.md) | missing | missing | no |
| [2026_cugraph_weighted_matching](papers/2026_cugraph_weighted_matching/README.md) | missing | local | no |

The collection target is met for the documented variants.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
