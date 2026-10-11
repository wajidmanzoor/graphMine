# Native selection and sampling checkpoint

The audited combined matrix passed **218,841 native validation requests**:
129,073 on CPU and 44,884 on each GPU, with no failures or skips.

This checkpoint adds native maximal independent sets, vertex coloring,
random walks, neighborhood sampling and induced/ego extraction. The C++/CUDA
runtime exposes 28 operations covering supported profiles for 26 of 70 formal
problems. Python transports the same catalog and requests through the C ABI.
The application's algorithm worker still needs migration to this runtime.

`selection-cpu.json` and `selection-gpu-*.json` record the new independent
oracles. Other JSON reports rerun the existing traversal, centrality, matching,
flow, structure and original mining profiles against the combined build.
Every report has an implementation hash and a sidecar with immutable binary
hashes. CPU processes run with CUDA devices hidden. The two GPU reports repeat
the supported profiles on physical devices 0 and 1; their sum counts executions,
not distinct mathematical fixtures.

The selection suites cover typed IDs, all undirected graphs through five
vertices, small directed graphs, independent-set maximality, proper distance
coloring, subgraph records and lineage, directed walk transitions, seeded
probabilities, edge-instance sampling, exact timestamps and resource limits.
The larger fixture is a 257-vertex path plus an isolate. CUDA memory and
initialization checks exercise that fixture on both devices.

`binding-ingestion.xml` checks native family/CLI/binding parity and CUDA device
restoration. `cudf-construction.xml` covers the shared native reader;
`app-working.xml` and `app-staged.xml` check uploads in the working and committed
application snapshots. Installed C/C++ consumers run with Python absent from
PATH and GPUs hidden. Installed GPU workers are independently observed through
process execution traces.

The new selection suites passed 22,402 requests on CPU and 14,274 requests on
each GPU. Binding/CLI checks passed 139 tests, native cuDF construction passed
64, and working/staged upload acceptance passed 41 and 25 respectively, with
no failures or skips. The upload suites retain the existing Starlette
deprecation warning. Four new selection sanitizer runs and the 32 existing
mining/centrality/optimization sanitizer or admission checks passed. The CPU
C/C++ consumers and four installed GPU worker/device combinations also passed.

After building the standalone CPU runtime and the original-backend GPU build:

```sh
python tools/validate_native_runtime.py \
  --cpu-build build/native-cpu --gpu-build build/native-gpu/runtime \
  --output validation/native_selection
python tools/validate_native_selection_sanitizers.py \
  --gpu-build build/native-gpu/runtime \
  --output validation/native_selection/selection-sanitizers
```

The full evidence audit also requires the earlier mining, centrality and
optimization sanitizer runners, installed-consumer checks, and the binding and
upload XML reports from the same binaries. `tools/audit_native_runtime.py`
verifies source contents, report counts, compiled capabilities, binary hashes
and resolved native dependencies before generating the coverage inventory.
These are migration checks; they do not establish full coverage of every
variant, large-scale performance, or application worker integration.
