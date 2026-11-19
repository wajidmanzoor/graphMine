# Standard graph views: Step 3 completion

All **82 CPU operations** now consume declared views across **141 profiles** in `devlopment`. The work was committed in 47 family checkpoints, following the prerequisite extensions. The implementation checkpoint is `255d45a6`. Production was not changed.

The final checkpoint passes **53 CTests, 238 Python tests, the 129,073-request C++ oracle replay, and all 82 CPU capability admissions**, with no evidence verification issues. The Python total includes binding/native tests, evidence gates and three real agent capability checks.

Input goldens cover **6,571 datasets per family**, totaling **1,090,786 profile/parameter cases** and **2,181,572 cold/warm comparisons**. No unresolved input mismatch remains. Each family report records its own source and binary hashes; the final checkpoint reruns the common tests and refreshes admissions for the final code.

Goldens compare arrays, weights, labels, identities, ordering, costs and rejection behavior against frozen old builders. The corpus includes published and synthetic large graphs. Feature, hypergraph, collection and bipartite cases use the explicit conversions documented in the family notes; these checks compare inputs rather than running every full algorithm on every large dataset.

The approved compatibility policies are opt-in: exact rational arithmetic, record COO, rounded long-double sums, probability union, one self-connection per vertex, and zero-weight removal. Defaults are preserved. Structured values enter the factory without a JSON text round trip. The `drop_zero_weights` profile removes zero support for spectral sparsification; other profiles retain their original policies.

## Files and tests

Runtime changes are in `library/runtime/families/`, layout helpers in `library/runtime/*_input.hpp`, shared declarations in `view_profiles.*`, and approved factory extensions in `views.cpp` / `include/graphmine/views.hpp`. Frozen reference builders and input/declaration tests are in `runtime/tests/legacy_normalizers.hpp` and `cpu_views_golden.cpp`. Factory unit/property tests cover the new policies. Execution evidence is refreshed in `catalog/native_execution_evidence.json`.

[Changed source files](../../validation/graph_views/step3/completion/changed-source-files.txt), [complete implementation-checkpoint file list](../../validation/graph_views/step3/completion/changed-files.txt), [generated CPU declarations](../../validation/graph_views/step3/completion/cpu-view-declarations.json), [per-dataset results](../../validation/graph_views/step3/completion/per-dataset.jsonl.gz), and [machine-readable completion report](../../validation/graph_views/step3/completion/summary.json) are retained. The audit verified every recorded artifact hash in the family checkpoints.

## Family goldens

| Checkpoint | Datasets | Cases | Mismatches |
|---|---:|---:|---:|
| [01-traversal](../../validation/graph_views/step3/01-traversal/summary.json) | 6,571 | 6,571 | 0 |
| [02-weighted-paths](../../validation/graph_views/step3/02-weighted-paths/summary.json) | 6,571 | 32,855 | 0 |
| [03-connectivity](../../validation/graph_views/step3/03-connectivity/summary.json) | 6,571 | 19,713 | 0 |
| [04-cliques](../../validation/graph_views/step3/04-cliques/summary.json) | 6,571 | 39,426 | 0 |
| [05-reachability](../../validation/graph_views/step3/05-reachability/summary.json) | 6,571 | 13,142 | 0 |
| [06-density](../../validation/graph_views/step3/06-density/summary.json) | 6,571 | 39,426 | 0 |
| [07-centrality](../../validation/graph_views/step3/07-centrality/summary.json) | 6,571 | 91,994 | 0 |
| [08-coloring](../../validation/graph_views/step3/08-coloring/summary.json) | 6,571 | 13,142 | 0 |
| [09-similarity](../../validation/graph_views/step3/09-similarity/summary.json) | 6,571 | 19,713 | 0 |
| [10-patterns](../../validation/graph_views/step3/10-patterns/summary.json) | 6,571 | 26,284 | 0 |
| [11-partitioning](../../validation/graph_views/step3/11-partitioning/summary.json) | 6,571 | 26,284 | 0 |
| [12-spectral](../../validation/graph_views/step3/12-spectral/summary.json) | 6,571 | 13,142 | 0 |
| [13-alignment](../../validation/graph_views/step3/13-alignment/summary.json) | 6,571 | 13,142 | 0 |
| [14-local-community](../../validation/graph_views/step3/14-local-community/summary.json) | 6,571 | 6,571 | 0 |
| [15-geolocation](../../validation/graph_views/step3/15-geolocation/summary.json) | 6,571 | 6,571 | 0 |
| [16-condensation](../../validation/graph_views/step3/16-condensation/summary.json) | 6,571 | 6,571 | 0 |
| [17-record-queries](../../validation/graph_views/step3/17-record-queries/summary.json) | 6,571 | 45,997 | 0 |
| [18-layout](../../validation/graph_views/step3/18-layout/summary.json) | 6,571 | 26,284 | 0 |
| [19-subgraph-matching](../../validation/graph_views/step3/19-subgraph-matching/summary.json) | 6,571 | 6,571 | 0 |
| [20-structure](../../validation/graph_views/step3/20-structure/summary.json) | 6,571 | 13,142 | 0 |
| [21-influence](../../validation/graph_views/step3/21-influence/summary.json) | 6,571 | 13,142 | 0 |
| [22-steiner](../../validation/graph_views/step3/22-steiner/summary.json) | 6,571 | 6,571 | 0 |
| [23-coarsening](../../validation/graph_views/step3/23-coarsening/summary.json) | 6,571 | 13,142 | 0 |
| [24-walks](../../validation/graph_views/step3/24-walks/summary.json) | 6,571 | 13,142 | 0 |
| [25-null-models](../../validation/graph_views/step3/25-null-models/summary.json) | 6,571 | 6,571 | 0 |
| [26-topology](../../validation/graph_views/step3/26-topology/summary.json) | 6,571 | 6,571 | 0 |
| [27-signed-balance](../../validation/graph_views/step3/27-signed-balance/summary.json) | 6,571 | 13,142 | 0 |
| [28-general-matching](../../validation/graph_views/step3/28-general-matching/summary.json) | 6,571 | 6,571 | 0 |
| [29-entity-resolution](../../validation/graph_views/step3/29-entity-resolution/summary.json) | 6,571 | 6,571 | 0 |
| [30-path-profiles](../../validation/graph_views/step3/30-path-profiles/summary.json) | 6,571 | 13,142 | 0 |
| [31-induced-subgraph](../../validation/graph_views/step3/31-induced-subgraph/summary.json) | 6,571 | 39,426 | 0 |
| [32-enumeration](../../validation/graph_views/step3/32-enumeration/summary.json) | 6,571 | 26,284 | 0 |
| [33-node-learning](../../validation/graph_views/step3/33-node-learning/summary.json) | 6,571 | 19,713 | 0 |
| [34-graph-learning](../../validation/graph_views/step3/34-graph-learning/summary.json) | 6,571 | 26,284 | 0 |
| [35-knn](../../validation/graph_views/step3/35-knn/summary.json) | 6,571 | 6,571 | 0 |
| [36-hypergraphs](../../validation/graph_views/step3/36-hypergraphs/summary.json) | 6,571 | 13,142 | 0 |
| [37-dynamic-triangles](../../validation/graph_views/step3/37-dynamic-triangles/summary.json) | 6,571 | 6,571 | 0 |
| [38-embeddings](../../validation/graph_views/step3/38-embeddings/summary.json) | 6,571 | 52,568 | 0 |
| [39-sparsification](../../validation/graph_views/step3/39-sparsification/summary.json) | 6,571 | 13,142 | 0 |
| [40-flow](../../validation/graph_views/step3/40-flow/summary.json) | 6,571 | 13,142 | 0 |
| [41-anomalies](../../validation/graph_views/step3/41-anomalies/summary.json) | 6,571 | 19,713 | 0 |
| [42-sampling](../../validation/graph_views/step3/42-sampling/summary.json) | 6,571 | 59,139 | 0 |
| [43-temporal-paths](../../validation/graph_views/step3/43-temporal-paths/summary.json) | 6,571 | 26,284 | 0 |
| [44-temporal-motifs](../../validation/graph_views/step3/44-temporal-motifs/summary.json) | 6,571 | 26,284 | 0 |
| [45-comparison](../../validation/graph_views/step3/45-comparison/summary.json) | 6,571 | 52,568 | 0 |
| [46-frequent](../../validation/graph_views/step3/46-frequent/summary.json) | 6,571 | 45,997 | 0 |
| [47-bipartite](../../validation/graph_views/step3/47-bipartite/summary.json) | 6,571 | 78,852 | 0 |

Each linked checkpoint includes compressed per-dataset/profile results, logs, tests, evidence and matching rejection counts. Initial failures and their corrections remain in the checkpoint diagnostics and detailed [family notes](graph_views_step3.md).

## CPU evidence by operation

| Operation | Declared profiles | Evidence | Checkpoint |
|---|---:|---|---|
| `balanced-partitioning` | 2 | Admitted | 11-partitioning |
| `betweenness-centrality` | 2 | Admitted | 07-centrality |
| `biconnected-components` | 2 | Admitted | 20-structure |
| `bipartite-matching` | 3 | Admitted | 47-bipartite |
| `bounded-paths-cycles` | 3 | Admitted | 32-enumeration |
| `breadth-first-search` | 1 | Admitted | 01-traversal |
| `butterfly-counting` | 1 | Admitted | 47-bipartite |
| `common-neighbors` | 1 | Admitted | 17-record-queries |
| `community-detection` | 2 | Admitted | 11-partitioning |
| `connected-components` | 2 | Admitted | 03-connectivity |
| `degree-centrality` | 4 | Admitted | 07-centrality |
| `densest-k-subgraph` | 2 | Admitted | 06-density |
| `densest-subgraph` | 3 | Admitted | 06-density |
| `dynamic-triangle-counting` | 1 | Admitted | 37-dynamic-triangles |
| `edge-filter` | 1 | Admitted | 17-record-queries |
| `entity-resolution` | 1 | Admitted | 29-entity-resolution |
| `force-directed-layout` | 2 | Admitted | 18-layout |
| `frequent-subgraphs` | 1 | Admitted | 46-frequent |
| `graph-aggregate` | 1 | Admitted | 17-record-queries |
| `graph-anomalies` | 4 | Admitted | 41-anomalies |
| `graph-coarsening` | 2 | Admitted | 23-coarsening |
| `graph-condensation` | 1 | Admitted | 16-condensation |
| `graph-edit-distance` | 2 | Admitted | 45-comparison |
| `graph-geolocation` | 1 | Admitted | 15-geolocation |
| `graph-learning` | 4 | Admitted | 34-graph-learning |
| `graph-signal-denoising` | 1 | Admitted | 12-spectral |
| `graphlet-counting` | 1 | Admitted | 10-patterns |
| `group-steiner-tree` | 1 | Admitted | 22-steiner |
| `hypergraph-node-learning` | 1 | Admitted | 36-hypergraphs |
| `hypergraph-partitioning` | 1 | Admitted | 36-hypergraphs |
| `induced-subgraph` | 4 | Admitted | 31-induced-subgraph |
| `influence-maximization` | 2 | Admitted | 21-influence |
| `k-cliques` | 1 | Admitted | 04-cliques |
| `k-core` | 1 | Admitted | 04-cliques |
| `k-truss` | 2 | Admitted | 20-structure |
| `knn-graph` | 1 | Admitted | 35-knn |
| `knowledge-graph-embedding` | 1 | Admitted | 38-embeddings |
| `laplacian-eigenpairs` | 1 | Admitted | 12-spectral |
| `link-prediction` | 1 | Admitted | 09-similarity |
| `many-source-shortest-paths` | 2 | Admitted | 02-weighted-paths |
| `max-flow-min-cut` | 4 | Admitted | 40-flow |
| `maximal-biclique-counting` | 1 | Admitted | 47-bipartite |
| `maximal-bicliques` | 1 | Admitted | 47-bipartite |
| `maximal-cliques` | 1 | Admitted | 04-cliques |
| `maximal-independent-set` | 1 | Admitted | 08-coloring |
| `maximum-clique` | 1 | Admitted | 04-cliques |
| `maximum-common-subgraph` | 2 | Admitted | 45-comparison |
| `maximum-independent-set` | 1 | Admitted | 04-cliques |
| `minimum-vertex-cover` | 1 | Admitted | 04-cliques |
| `motif-counting` | 2 | Admitted | 10-patterns |
| `neighborhood-sampling` | 4 | Admitted | 42-sampling |
| `neighbors` | 1 | Admitted | 17-record-queries |
| `network-alignment` | 2 | Admitted | 13-alignment |
| `node-embedding` | 6 | Admitted | 38-embeddings |
| `node-learning` | 3 | Admitted | 33-node-learning |
| `node-lookup` | 1 | Admitted | 17-record-queries |
| `null-model-significance` | 1 | Admitted | 25-null-models |
| `overlapping-communities` | 1 | Admitted | 05-reachability |
| `pagerank` | 2 | Admitted | 07-centrality |
| `persistent-homology` | 1 | Admitted | 26-topology |
| `personalized-pagerank` | 6 | Admitted | 07-centrality |
| `quasi-cliques` | 1 | Admitted | 06-density |
| `query-paths` | 1 | Admitted | 17-record-queries |
| `query-subgraph` | 1 | Admitted | 17-record-queries |
| `random-walks` | 2 | Admitted | 24-walks |
| `seeded-local-community` | 1 | Admitted | 14-local-community |
| `signed-balance` | 2 | Admitted | 27-signed-balance |
| `simrank` | 2 | Admitted | 09-similarity |
| `single-graph-frequent-subgraphs` | 2 | Admitted | 46-frequent |
| `single-source-shortest-paths` | 1 | Admitted | 02-weighted-paths |
| `spanning-tree-forest` | 2 | Admitted | 02-weighted-paths |
| `spectral-sparsification` | 1 | Admitted | 39-sparsification |
| `subgraph-isomorphism` | 1 | Admitted | 19-subgraph-matching |
| `temporal-motifs` | 3 | Admitted | 44-temporal-motifs |
| `temporal-paths` | 1 | Admitted | 43-temporal-paths |
| `top-k-critical-paths` | 1 | Admitted | 30-path-profiles |
| `topological-sort` | 1 | Admitted | 03-connectivity |
| `transitive-closure` | 1 | Admitted | 05-reachability |
| `triangle-counting` | 1 | Admitted | 10-patterns |
| `vertex-coloring` | 1 | Admitted | 08-coloring |
| `weighted-matching` | 1 | Admitted | 28-general-matching |
| `widest-paths` | 1 | Admitted | 30-path-profiles |

## Remaining steps

Stopped after Step 3 as requested. Steps 4–6 cover cuGraph, in-process CUDA and worker exporters; Step 7 adds optional attribute-based sides to maximal bicliques; Step 8 generates backend registry requirements; Step 9 completes evidence and documentation across all backends. GPU builds and GPU admission were not claimed by this CPU checkpoint.

C ABI, CLI operation names and request parameters remain unchanged. Existing algorithm result fields are preserved, with the approved view/normalization provenance under `representations`. Maximal bicliques still requires explicit partition parameters until Step 7. All commits are local; no deployment, service restart or push was performed for this step.
