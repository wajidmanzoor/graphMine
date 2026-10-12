Induced Subgraph and Ego-Network Extraction
===========================================

Extract the graph induced by an explicit vertex set or by vertices within a hop radius of declared seeds.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 5 records; 3 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2019_dgl_node_subgraph](papers/2019_dgl_node_subgraph/README.md) | local | local | yes |
| [2019_pyg_induced_subgraph](papers/2019_pyg_induced_subgraph/README.md) | local | local | yes |
| [2019_pyg_khop_subgraph](papers/2019_pyg_khop_subgraph/README.md) | local | local | yes |
| [2026_cugraph_egonet](papers/2026_cugraph_egonet/README.md) | missing | local | no |
| [2026_cugraph_induced_subgraph](papers/2026_cugraph_induced_subgraph/README.md) | missing | local | no |

The collection target is met for the documented variants.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
