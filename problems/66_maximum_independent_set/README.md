Maximum Independent Set
=======================

Find an independent vertex set of maximum cardinality in a simple undirected graph.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 2 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2023_difusco_mis](papers/2023_difusco_mis/README.md) | local | local | yes |
| [2023_dynamic_mis](papers/2023_dynamic_mis/README.md) | local | local | yes |
| [2025_pcqo_reference](papers/2025_pcqo_reference/README.md) | local | missing | no |

Dynamic-MIS and DIFUSCO are paired heuristic implementations. pCQO has a paper but its referenced branch/license availability prevents a new redistributable source snapshot.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
