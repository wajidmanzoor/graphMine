# Standard graph views: Step 1 report

Completed in `devlopment` on 2026-11-16. The isolated CPU build is
`build/native-views-step1`; its implementation hash is
`1b047e2e3e1d7c7007ec756547d1e9c2bf518e245d24ee09cd0d65473aabc7a7`.

## Scope and files

| Files | Change |
| --- | --- |
| `library/include/graphmine/views.hpp`, `library/runtime/views.cpp` | V1–V5 owned views, side tables, typed ID maps, strict JSON specs, centralized normalization, summaries and immutable factory results |
| `library/include/graphmine/graph.hpp` | Extend the existing normalization summary while retaining its legacy fields |
| `library/runtime/representation_cache.{hpp,cpp}` | Share the existing bounded memory cache; include snapshot, resolved spec and implementation in view keys |
| `library/runtime/internal.hpp`, `json_graph.cpp`, `structured_input.hpp` | Explicit exact-weight parsing opt-in for new `int64_exact` views; existing callers retain their validation |
| `library/runtime/CMakeLists.txt` | Build/test/install the new API and hash its public header for evidence |
| `library/runtime/tests/views_test.cpp` | Seven foundation suites, including seeded properties and fresh-build byte comparisons |
| `catalog/native_execution_evidence.json`, `validation/graph_views/step1/` | Fresh isolated CPU execution evidence and admission results |
| `GRAPH_VIEW_FORMATS.md`, `library/docs/graph_views.md`, this report, `.gitignore` | Preserve the specification, document the foundation, exclude its isolated build |

The user approved f64 defaults, in-memory caching, support for existing structured
input formats, and exact integer parsing only for new `int64_exact` views.
No existing algorithm adapter consumes the new views yet. Production services,
the production checkout and the pinned shared native build were not modified.

## Tests

| Check | Result |
| --- | --- |
| Full CPU CTest suite | 49/49 passed, zero skipped |
| New view suites within CTest | 7/7 passed; 2,065 checks |
| Existing C++ oracle replay with evidence snapshots | 129,073 successful requests, zero failures |
| Native extended/learning/record/application/table regressions | 127 passed |
| Original-profile regressions in CPU mode | 34 passed |
| CPU Python bindings and CLI parity | 43 passed; 97 GPU/cuDF-specific cases deselected |
| Evidence-gate unit checks | 31 passed |
| Actual agent capability endpoint, capability caching, workflow admission | 3 passed |
| Installed C and C++ algorithm consumers | Both passed without Python/CUDA on the execution path |
| Installed public `views.hpp` consumer | Passed typed-ID, CSR and summary checks |

The new suite checks every collapse policy, loop/duplicate counts, reverse CSR
alignment, labels/timestamps, original edge identity, integer boundaries and
overflow, i32 limits without huge allocations, both side sources, dense presence
masks, structured input validation and cache concurrency/eviction. Symmetry and
aggregate counts are checked on 75 seeded multigraph fixtures.

An initial combined Python/agent pytest invocation crossed project-specific
fixtures and selected the wrong asyncio configuration. The two projects passed
when run separately with their own configurations. The initial invocation is
retained under `validation/graph_views/step1/diagnostics/`; no application code
change was needed to resolve it.

## Golden and byte comparison status

| Foundation fixture | Byte determinism result |
| --- | --- |
| Directed multigraph with loops, parallel edges, labels and timestamps → CSR | Six fresh uncached rebuilds identical |
| Same multigraph → COO | Six fresh uncached rebuilds identical |
| Same multigraph → dense matrix | Six fresh uncached rebuilds identical |
| Bipartite graph with isolates and mixed ID types | Six fresh rebuilds identical; attribute/parameter V3 arrays also identical |
| Feature-vector matrix with typed row IDs | Six fresh uncached rebuilds identical |
| Weighted hypergraph with an isolated vertex | Six fresh uncached rebuilds identical |
| Graph collection | Six fresh uncached rebuilds identical |

These comparisons include all scalar arrays, optional-column presence, external
ID maps, dictionaries and summaries, without comparing C++ padding or cached
pointer identity. They are foundation tests, **not** old-adapter golden tests.

For every existing backend validation dataset, old/new adapter input equality is
**not yet evaluated**: no backend has migrated. Those mandatory per-dataset tests
start in Step 2, before replacing either existing normalization helper. No worker
writer, upstream source or worker patch was changed.

## Evidence and admission

Fresh evidence was generated with the existing `validate_native_runtime.validate`
CPU runner, native pytest metadata and `tools/build_native_execution_evidence.py`.
The new catalog entry has ten evidence reports. Its header, implementation and
tests are included in the source hashes.

All **82 `cpp` operation profiles are admitted** for this isolated CPU build.
Its GPU backends are uncompiled/unadmitted. No GPU execution or GPU migration
claim is made. Each operation/backend's compiled, verified and evidence state is
recorded in [`admission.json`](../../validation/graph_views/step1/admission.json).

The gate reports zero verification issues. Existing deployed binaries retain
their separate evidence; this report does not promote the development build.

## Remaining work

Step 2 must route `Graph::simple_undirected()` and `weighted_graph()` through the
factory, preserve their work-budget behavior, and prove byte-identical inputs on
every validation dataset. CPU/GPU family migration, worker exporters, optional
maximal-biclique side parameters, generated registry declarations and final
all-backend evidence remain in Steps 3–9.

No result mismatch was observed in the regression checks. Per-backend input
equivalence remains unclaimed until the corresponding migration golden tests
pass. Work stops here at the requested Step 1 checkpoint.
