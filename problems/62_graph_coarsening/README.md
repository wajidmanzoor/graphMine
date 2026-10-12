Graph Coarsening and Quotient Construction
==========================================

Map every vertex to a nonempty coarse cluster and construct the weighted quotient graph with declared edge and feature aggregation.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 1 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2019_pyg_average_pool](papers/2019_pyg_average_pool/README.md) | local | local | yes |
| [2026_cugraph_quotient](papers/2026_cugraph_quotient/README.md) | missing | local | no |
| [2026_nvgraph_contraction](papers/2026_nvgraph_contraction/README.md) | missing | local | no |

GPU quotient construction is available in cuGraph, nvGRAPH and PyG. Only PyG currently has a paired framework PDF; supplied assignment and clustering generation are separate stages.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
