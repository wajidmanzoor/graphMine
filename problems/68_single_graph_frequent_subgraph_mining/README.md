Frequent Subgraphs in One Labeled Graph
=======================================

Enumerate or count connected labeled patterns meeting a declared minimum-image-support threshold in one labeled host graph.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 2 records; 2 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2022_graphminer_mni](papers/2022_graphminer_mni/README.md) | local | local | yes |
| [2022_pangolin_mni](papers/2022_pangolin_mni/README.md) | local | local | yes |

Two upstream GPU MNI mining implementations are included. Their count-only interfaces and compiled size limits remain explicit; transaction-support mining is separate.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
