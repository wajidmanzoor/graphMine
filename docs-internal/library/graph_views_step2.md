# Standard graph views: Step 2 report

Completed in `devlopment` on 2026-11-16. The isolated CPU runtime is
`build/native-views-step2`, with implementation hash
`fe4df04a110ebb5ed9f9c06cb9245ad61f432a53cda93247013644e7a8aed848`.

## Changes

| Files | Change |
| --- | --- |
| `src/core/graph.cpp`, `runtime/families/common.cpp` | Both legacy normalizers delegate to `make_view`; adapters only repack the resulting CSR |
| `runtime/views.cpp`, `views_input.cpp`, `views_internal.hpp` | Keep the normalization engine in the standalone core; separate runtime JSON/structured-input support |
| `src/core/graph_fingerprint.cpp`, `view_cache.cpp`, `representation_store.*` | Typed native snapshot hashing and one bounded, shared in-memory store; remove the separate weighted-adjacency cache |
| `include/graphmine/views.hpp` | Optional budget/observation callbacks, cached build cost, and explicit nonnegative-weight validation |
| `src/core/view_json.*`, `runtime/json_input.cpp` | Share strict lexical JSON validation without a dependency from the core to the runtime |
| `cmake/GraphViews.cmake`, both CMakeLists, package config | Build/export the independent core factory, declare OpenSSL dependency, hash all compiled core sources |
| `runtime/tests/legacy_normalizers.hpp`, `normalizer_golden.cpp`, `normalizer_audit.cpp`, `core_view_test.cpp` | Frozen old implementations, raw-array goldens, live oracle interposition, budget/rejection checks, independent-core consumer |
| `tools/graph_view_golden_corpus.py`, `tests/conftest.py`, `tests/test_native_application_contracts.py` | Reproducible fixture inventory, complete evidence source snapshots, result-provenance regression |
| `catalog/native_execution_evidence.json`, `validation/graph_views/step2/` | Fresh execution evidence, per-dataset comparisons and per-backend admission |

The user approved summaries inside the existing `representations` metadata.
Weighted records now contain the resolved view spec and six normalization fields.
Algorithm result fields, C ABI, CLI, problem IDs and parameters are unchanged.
Directed projection permission, canonical summation order, sign validation before
loop removal, overflow rejection and candidate budgets are preserved.

## Golden results

The frozen reference is from commit `a38d1dcb`. Before replacing the helpers, the
existing functions and new factory were compared on the main saved corpus. The
same baseline executable was retained for the supplemental and scale checks.
After migration, the new helpers were compared with those frozen references.
Every graph checks simple-undirected CSR and 24 weighted profiles (unit/weighted,
four collapse policies and three directions). Comparisons use scalar array
bytes, without C++ structure padding, and check direction and normalization counts.

| Dataset group | Distinct graph documents | Profile comparisons | Result |
| --- | ---: | ---: | --- |
| Saved canonical/manifest graphs and CDS adjacency fixtures | 6,528 | 163,200 | Identical before and after; 113,849 source aliases |
| MBE adjacency fixtures | 7 | 175 | Identical |
| ECL SCC and flow fixtures | 26 | 650 | Identical |
| Published Graphalytics fixtures | 8 | 200 | Identical |
| SNAP ca-CondMat: 23,133 vertices / 93,497 edges | 1 | 25 | Identical |
| Seeded synthetic: 100,000 vertices / 500,000 edges | 1 | 25 | Identical |
| **Total** | **6,571** | **164,275** | **No differences** |

The corpus directories contain compressed input documents, source hashes/aliases,
and one before/after result per dataset. They are `step2/`, `step2/supplementary/`
and `step2/published/` under `validation/graph_views/`. The source archives for
Graphalytics and SNAP were fetched with the existing tool and checked against
their pinned SHA-256 hashes. The synthetic graph uses the original scale runner's
seed and generator. Original research sources and worker patches were untouched.

A test-only preload auditor also compares the actual weighted arrays produced
during existing C++ oracle and Python suites against frozen legacy code. It checked
32,205 calls, covering 4,964 native snapshots and 11,247 snapshot/profile pairs,
with zero differences. This includes procedurally generated inputs that are not
stored as dataset files. The auditor is not installed or linked into production.

No worker exporter or GPU adapter is declared migrated by this step. Their own
byte-level integration checks and fresh GPU execution evidence remain in the
corresponding later steps.

## Tests and evidence

| Check | Result |
| --- | --- |
| Runtime CTest | 51 passed, zero skipped |
| Additional full C++ library CTest with CUDA disabled | 3 passed; 16 CUDA tests disabled |
| New cold/warm budget and rejection checks | 9,600 comparisons; plus overflow, ignored weight and projection checks |
| Existing C++ oracle replay | 129,073 requests passed |
| Native extended/learning/record/application/table tests | 127 passed |
| Original-profile tests in CPU mode | 34 passed |
| CPU Python binding/CLI parity | 43 passed; 97 GPU/cuDF cases deselected |
| Evidence gate | 31 passed |
| Actual agent capability/admission tests | 3 passed |
| Installed native C and C++ consumers | Passed |
| Full installed C++ library consumers | Passed |
| Installed `GraphMine::core`-only view consumer | Passed, including JSON ViewSpec parsing; no runtime linkage |

All **82 CPU `cpp` profiles remain admitted**, with no verification issues.
`validation/graph_views/step2/backend-admission.csv` lists every problem/backend;
`admission.json` retains the full verification result. No GPU profiles are admitted
by this CPU-only build. Production remains on its existing pinned build.

There were no input-equivalence failures or algorithm-result discrepancies.
Production services and the production/shared native checkout were not modified.
Step 3, direct CPU-family migration, is next.
