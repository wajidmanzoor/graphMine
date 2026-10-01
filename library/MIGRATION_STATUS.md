# GraphMine migration status

All implementations that passed the repository's GPU validation are now
available behind canonical in-memory APIs. Original kernels and search logic
remain the computational backend; adapters replace file/CLI boundaries,
restore external IDs, manage resources, and validate returned results.

A build-once/run-many `graphmine` executable now exposes all 13 public
operations and 26 validated backend selections through canonical JSON input,
JSON output, backend arguments, and optional-output flags. The consolidated
manifest embeds the 12 original problem specifications and documents every
invocation.

| Problem component | Validated backends | Library status |
|---|---|---|
| Maximal clique enumeration | mce-gpu, G2-AIMD, RDMCE | Complete; all three selectable, exact clique sets and optional total count cross-checked |
| Maximum clique | CUDA-MS, GPUMaximumClique, Maximum-Clique-on-GPU | Complete; all three selectable, feasible clique checked, ties supported where native, upper-bound flag available |
| k-core decomposition | KCoreGPU | Complete; core numbers and degeneracy required, requested core subgraph and peeling order optional |
| Triangle counting/listing | ToT, WeTriC | Complete; both selectable, exact optional instances and participation counts checked against GPU total |
| Dynamic triangle counting | EDTC | Complete; deletion/insertion batch semantics retained, changed instances and global counts optional |
| k-clique counting/enumeration | KCGPU, GraphSet, GAMMA | Complete; all three selectable, enumeration and per-vertex counts optional and cross-checked |
| Centrality | TurboBC | Complete; native score vector required, normalization/ranking/maximum optional |
| Maximal biclique enumeration | cuMBE | Complete; explicit canonical partition input and exact vertex-set materialization |
| Quasi-clique mining | cuQC | Complete; original CPU/GPU expansion, scheduling choice, limits, and typed outputs |
| Subgraph isomorphism | gMatch | Complete; canonical data/query graphs, count required, embeddings optional |
| Graph motif counting | GraphMiner/G2Miner, GraphSet, DuMato | Complete; all three selectable with typed motif results and optional common materialization |
| Temporal motif mining | Everest, Mayura | Complete for the validated ordered feed-forward triangle; count required, edge-ID instances optional |
| Community detection | gLeiden, pLouvain, pLeiden, pLeiden+ | Complete; original-vertex assignments, dense labels, modularity, optional groups and edge cut |

## Completion gate applied to each backend

1. Build from its pinned source commit and maintained compatibility patch.
2. Accept the canonical in-memory graph at the public boundary.
3. Declare semantic and optional-output capabilities explicitly.
4. Return typed required outputs with restored external IDs.
5. Preserve the original validated algorithm path and report provenance.
6. Check feasible/materialized outputs independently where practical.
7. Pass the preserved small correctness fixture through the library API.
8. Survive the complete installed-target build and package-consumer link test.
