Topological Sorting and DAG Levels
==================================

Determine whether a directed graph is acyclic and return a valid topological vertex order and optional dependency levels.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 0 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2017_nvidia_parallel_dag_dfs](papers/2017_nvidia_parallel_dag_dfs/README.md) | local | missing | no |
| [2026_cugraph_topological_levels](papers/2026_cugraph_topological_levels/README.md) | missing | local | no |
| [2026_topogpu_morse_sort](papers/2026_topogpu_morse_sort/README.md) | local | local | no |

cuGraph has CUDA topological levels, but no paired research PDF was verified. DGL topological traversal falls back to CPU, and TopoGPU solves a restricted image-derived DAG.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
