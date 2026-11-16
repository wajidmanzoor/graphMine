# GraphMine standard graph views

**Goal:** every CPU and GPU backend reads its input through **one of five standard in-memory views**, built by **one audited function** from a **declared view spec**. Isolated research workers keep their native file formats, written by **thin exporters** from those views.

## Why

Today each backend adapter normalises the graph its own way:

- `Graph::simple_undirected()` builds the `CsrGraph`.
- `weighted_graph()` builds `WeightedGraph` rows.
- `families/bipartite.cpp` reads `attributes.side`, while `maximal-bicliques` takes partition parameters instead.
- About a dozen writers in `validated_expansion.cpp`, `repaired_algorithms.cpp` and `original_optimization.cpp` each project, merge and convert separately.

Every one of those is a place where direction, weights or sides can change silently. Standardising gives one place to audit, cached views across workflow steps, and requirements derived from the specs, not written by hand.

## Common front (unchanged)

Canonical graph JSON → `graphmine::Graph` (validated, dense `u32` vertex indices, reversible ID maps). Results are always mapped back to external IDs.

## The five views

| View | Layout | Used by |
|---|---|---|
| **V1 CSR** | `offsets: u64[n+1]`; `indices: u32[m]`; optional `weights: f64[m]`; optional `edge_ids: u64[m]` (back to the original edge); optional reverse CSR `in_offsets`/`in_indices`. Flags: `directed`, `symmetric`, `simple`, `sorted`. | In-process CUDA backends (ToT, WeTriC, KCoreGPU, RDMCE, MCE-GPU, G2-AIMD, GraphSet, KCGPU, DuMato, G2Miner, gLeiden, TurboBC, the maximum-clique family, gMatch…); cuGraph (CSR input); CPU traversal, centrality, cores and cliques; the ECL, GPU4GST, GAMMA, AccTD and CDS exporters |
| **V2 COO** | `src: u32[m]`, `dst: u32[m]`; optional `weight: f64[m]`, `timestamp: i64[m]`, `edge_id: u64[m]` | Temporal operations, edge streams and dynamic triangles, cuGraph graph creation, the GDlog and kPAR exporters, building V1 |
| **V3 Bipartite** | V1, relabelled so the left side is `0..L-1` and the right side `L..n-1`, plus `L`; optional weights | cuMBE, MBE-GPU, butterflies, bipartite matching |
| **V4 Dense matrix** | Row-major `f64[r×c]` or `i64[r×c]`, plus row and column ID maps | Linear assignment (HungarianGPU), small all-pairs outputs, feature vectors for k-NN |
| **V5 Set-structured** | Hypergraph: incidence CSR both ways (`he_offsets`/`he_vertices`, `v_offsets`/`v_hyperedges`). Collection: an array of V1 plus member indices. | Hypergraph partitioning and learning, graph classification, frequent subgraph mining |

**Side tables** (aligned columns, not separate formats):
- `vertex_label: u32[n]` (category IDs plus a dictionary)
- `edge_label: u32[m]`
- `timestamp: i64[m]`

These are used by pattern matching, labelled frequent-subgraph mining (GAMMA `.vlabel`) and temporal operations.

## The view spec, declared per backend profile

```json
{
  "kind": "csr | coo | bipartite | dense | hypergraph | collection",
  "direction": "keep | symmetrize | reverse | both",
  "self_loops": "keep | drop",
  "parallel_edges": "keep | collapse:sum | collapse:min | collapse:max | collapse:first",
  "weights": "none | f64 | int64_exact",
  "weight_source": "edge.weight | attribute:<path> | unit",
  "edge_ids": false,
  "labels": ["vertex_label", "edge_label", "timestamp"],
  "bipartite_sides": "attribute:side | parameters | none",
  "sorted_neighbors": true,
  "index_width": "u32 | i32",
  "limits": {"max_vertices": 1000000, "max_edges": 10000000}
}
```

Rules:
- `int64_exact` fails if any weight isn't an exact integer in range. Use it for capacities and costs.
- `i32` fails if the count exceeds `INT32_MAX`. Use it for ECL-style workers.
- `bipartite_sides: attribute:side` reads `attributes.side ∈ {left, right}`; `parameters` reads `left_partition` / `right_partition`. Both produce the same V3.

## `make_view(graph, spec) -> View + NormalizationSummary`

- **The only code allowed to change meaning:** projection, loop removal, merging parallel edges, weight casting, relabelling.
- **The summary records:** `projection_applied`, `self_loops_removed`, `parallel_edges_collapsed`, `weights_cast`, `vertices`, `edges`. It's attached to the result provenance.
- **Cache key:** (snapshot hash, canonical spec JSON). Reused across workflow steps and backends.
- **Deterministic:** the same input and spec give byte-identical arrays.

## Exporters for isolated workers (layout only, no meaning changes)

| Exporter | From view | Writes | Workers |
|---|---|---|---|
| `ecl_egr` | V1, `i32`, optional `int64_exact` weights | `int32[n, m, offsets…, indices…, weights…]` | `ecl-scc`, `ecl-maxflow` |
| `cost_matrix_txt` | V4 (`i64`) | `n` then `n×n` rows | `hungarian-cuda` |
| `edge_tsv` | V2 | `src\tdst` lines | `gdlog` |
| `gamma_bin` | V1 + `vertex_label` | `.col`, `.dst`, `.vlabel` | `gamma-butterfly` |
| `csr_bin_weighted` | V1 + weights | `*_beg_pos.bin`, `*_csr.bin`, `*_weight.bin` | `gpu4gst` |
| `kpar_txt` | V2 | `attribute.txt`, `graph.txt`, `queries.txt` | `kpar` |
| `adjacency_txt` / `degree_adj_bin` | V1 | as each upstream program reads it | `acctd`, `cds`, `mbe-gpu`, `superfuser` |

Each exporter declares its name and source view. Golden-file tests compare its output to the current writer's output on the validation datasets.

## Registry and agent integration

- `catalog/backend_registry.json`: each backend gains `"view": {…spec…}` and, for workers, `"exporter": "<name>"`.
- The agent's eligibility `requirements` come from the specs. For example, `weights: int64_exact` means "needs integer weights", and `bipartite_sides != none` means "needs sides".

---

# Codex prompt

> You are working in the GraphMine checkout's native library (`library/`) and its catalog (`catalog/`). Read `GRAPH_VIEW_FORMATS.md` (this file) fully first. Implement it **without changing any algorithm's results**. Ask me if anything here contradicts the code.
>
> **Read first:**
> - `include/graphmine/graph.hpp`: `Graph`, `CsrGraph`, `simple_undirected()`
> - `runtime/internal.hpp`: `WeightedGraph`, `weighted_graph()`, `adjacency()`
> - `runtime/families/bipartite.cpp`, `families/matching.cpp`, `families/common.cpp`
> - `src/backends/*.cu` and `*_backend.hpp`, `src/backends/maximal_cliques/`
> - `runtime/cugraph*.cpp`
> - `src/problems/validated_expansion.cpp` (`arcs`, `write_ecl`), `src/problems/repaired_algorithms.cpp`, `runtime/original_optimization.cpp`, `runtime/original_extensions.cpp`
> - `src/worker_process.hpp`
> - `catalog/backend_registry.json`, `catalog/native_execution_evidence.json`, `tools/build_native_execution_evidence.py`
>
> **Rules:**
> 1. `make_view()` is the only place allowed to project, drop loops, merge parallel edges, cast weights or relabel. Exporters and adapters only change layout.
> 2. Never change upstream research code or the worker patches in `tools/prepare_*_workers.py`. Workers keep their native files, written by exporters.
> 3. Results must be identical. For every migrated backend, the input it receives (memory arrays or worker file bytes) must equal the old adapter's on all validation datasets. Add a golden test that proves it before removing the old path.
> 4. Execution evidence is tied to the code. After migrating a backend, rebuild its evidence with the existing tooling and confirm it's still admitted. If a backend can't reproduce identical input, stop and report it; don't admit it.
> 5. Keep the C ABI, CLI, operation IDs, parameters and result JSON unchanged.
> 6. Small commits, one backend or family each, each with tests passing (`ctest`, the Python binding tests, and the agent's native capability checks).
>
> **Steps** (stop after each step and report):
> 1. **Views and spec.** Add `include/graphmine/views.hpp` and `runtime/views.cpp` with V1–V5, the side tables, `ViewSpec` (parsed from JSON), `make_view()`, `NormalizationSummary` and a per-snapshot cache keyed by (graph hash, canonical spec).
>    Unit and property tests:
>    - symmetry of `symmetrize`
>    - loop and duplicate counts
>    - every `collapse:*` rule
>    - `int64_exact` and `i32` limit failures
>    - V3 relabelling from both `attribute:side` and `parameters`
>    - determinism (identical bytes on repeat)
> 2. **Equivalence adapters.** Make `Graph::simple_undirected()` and `weighted_graph()` call `make_view()` internally with equivalent specs. Prove identical output with golden tests on every validation dataset.
> 3. **Migrate the CPU operations**, family by family. Each CPU adapter declares its spec and reads a view.
> 4. **Migrate cuGraph.** Build cuGraph graphs from V1 or V2.
> 5. **Migrate the in-process CUDA backends.** Each adapter takes the view its spec declares (V1 or V3); internal repacking stays inside the adapter (for example `CanonicalRdmceGraph`).
> 6. **Exporters.** Replace each worker writer with a named exporter that reads a view (`ecl_egr`, `cost_matrix_txt`, `edge_tsv`, `gamma_bin`, `csr_bin_weighted`, `kpar_txt`, plus exporters for `acctd`, `cds`, `mbe-gpu` and `superfuser`). Add golden-file tests: the new file must be byte-identical to the old one.
> 7. **Unify bipartite sides.** All bipartite operations build V3 through `bipartite_sides`. Make `left_partition`/`right_partition` on `maximal-bicliques` **optional**, falling back to `attributes.side` as the shared helper already does. This is the only allowed behaviour change: it makes a request valid that's rejected today, and it doesn't change any result.
> 8. **Registry.** Add `view` (and `exporter` for workers) to every backend in `catalog/backend_registry.json`, generated from the code, not hand-written. Add a test that each backend's declared spec equals the spec its adapter actually uses.
> 9. **Evidence and docs.** Rebuild execution evidence for every migrated backend and report which ones are admitted. Update `library/docs/` with a "Graph views" page.
>
> **Report after each step:** files changed, tests added, golden-test results per dataset, evidence status per backend, and anything that couldn't be made identical.
>
> **Ask me before starting:**
> (a) Should weights stay `f64` everywhere in V1, with exact `int64` only through `int64_exact`? (Default: yes.)
> (b) Should the view cache be in memory only, or also on disk per snapshot? (Default: in memory only.)