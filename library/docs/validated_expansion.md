# Validated additions, 2026-10-04

The library exposes five additional operations after independent CPU-oracle
testing on NVIDIA RTX 6000 Ada (SM89), CUDA 12.8 and GCC 13.3. These are bounded
profiles of the research problems, not claims that every mode in a paper or
`problem.json` is implemented.

| Operation / C++ class | Backend | Supported profile |
|---|---|---|
| `connected-components` / `ConnectedComponents` | ECL-SCC | Exact weak or strong components. Includes isolated vertices; removes loops and collapses duplicate arcs. Components are numbered by their smallest external vertex ID. |
| `max-flow-min-cut` / `MaxFlowMinCut` | ECL-MaxFlow | Directed graphs, integer nonnegative edge capacities or unit capacities. Sum of non-loop capacities must be at most 1,000,000,000. Returns original edge flows and a checked minimum-cut certificate. No vertex capacities or fractional capacities. |
| `linear-assignment` / `LinearAssignment` | HungarianCUDA | Minimum-cost perfect assignment on a complete square bipartite graph with at most 64 vertices per side. Integer costs in `[0,999]`. Duplicate pairs retain the lowest cost. Other matching objectives, incomplete/rectangular graphs, and negative costs are rejected. |
| `transitive-closure` / `TransitiveClosure` | GDlog | Full exact reflexive closure of a directed graph with at most 1,024 vertices. Materializes all reachable pairs; no reusable index or separate pair-query mode. |
| `butterfly-counting` / `ButterflyCounting` | Existing GraphMiner/G2Miner kernel | Exact global count of distinct K2,2 subgraphs. Undirected bipartite input only; no participation, listing or alpha/beta-core mode. |

Assignment and butterfly input vertices require
`"attributes": {"side": "left"}` or `"attributes": {"side": "right"}`.
Every edge must cross the declared sides. Weights are ignored for components,
closure and butterfly counting. Mixed integer/string external IDs are retained;
integer IDs sort before string IDs when canonical component numbering needs a
total order.

## Build and run

```bash
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build --parallel 4 --target graphmine_cli
library/build/graphmine list --pretty
library/build/graphmine run connected-components --graph directed.json \
  --connectivity-mode strongly_connected --backend ecl-scc
library/build/graphmine run max-flow-min-cut --graph capacities.json \
  --source 0 --sink 5 --backend ecl-maxflow
library/build/graphmine run linear-assignment --graph costs.json
library/build/graphmine run transitive-closure --graph directed.json
library/build/graphmine run butterfly-counting --graph bipartite.json
```

`--source` and `--sink` accept integer IDs or string IDs. Quote a JSON string
inside the shell argument to distinguish a numeric string ID from an integer:
`--source '"123"'`. Unquoted non-JSON text is also treated as a string ID.

All five APIs are declared in
[`validated_expansion.hpp`](../include/graphmine/problems/validated_expansion.hpp).
Link `GraphMine::validated_expansion`. Installed consumers can request
`find_package(GraphMine REQUIRED COMPONENTS validated_expansion)`.

## Isolation, limits and installation

Four newly imported artifacts run in separately compiled CUDA worker processes.
The butterfly operation reuses the existing in-process GraphMiner integration.
Worker crashes, nonzero exits, missing binaries, malformed output and timeouts
return an `ExecutionResult` error. No failed GPU execution is silently replaced
by a CPU solver. Empty components/closure/assignment and zero-capacity flow
have exact host-side boundary handling.

The worker APIs accept one CUDA device, a timeout (default 60 seconds), and an
optional worker directory. The device index is interpreted relative to inherited
`CUDA_VISIBLE_DEVICES`. Worker output is capped at 64 MiB. The common input cap
is 1,000,000 vertices and 10,000,000 edges; assignment/closure impose the smaller
limits above. Those caps bound representation and output sizes; they are not
performance or memory-availability guarantees. Allocation failures remain errors.
Only end-to-end timing is currently collected for the new facade; the other
timing fields remain zero.

The build pins `GRAPHMINE_EXPANSION_CUDA_ARCHITECTURES=89-real;89-virtual`, matching
the tested Ada GPU. Other targets require a separate correctness run. Disable
the imported workers with `GRAPHMINE_ENABLE_VALIDATED_EXPANSION=OFF`, or all CUDA
backends with `GRAPHMINE_ENABLE_CUDA_BACKENDS=OFF`. The APIs still build and
report `backend_unavailable` when their workers were not compiled.

`cmake --install library/build --prefix PREFIX` installs workers in
`PREFIX/libexec/graphmine` and their licenses under `PREFIX/share/doc/graphmine/expansion`.
The CLI discovers workers beside its installation; applications can set
`GRAPHMINE_WORKER_DIR` or `IsolatedBackendOptions::worker_directory`, especially
when relocating a static-library application. Explicit paths never silently
fall back to another worker directory.

## Evidence and fixes

The independent [public CLI suite](../../validation/gpu_correctness_expansion/validate_library.py)
covers partitions, flow conservation/capacity/cut equality, optimal assignment
costs, complete closure pairs and butterfly counts, plus invalid inputs and
worker failures. Run it from the project root:

```bash
python3 validation/gpu_correctness_expansion/validate_library.py
cmake --build library/build --target graphmine_validated_expansion_test
ctest --test-dir library/build -R graphmine_validated_expansion_test --output-on-failure
```

The Python suite needs NumPy, SciPy and NetworkX. The C++ regression remains
active in a CUDA-disabled build to check unavailable-backend behavior.

ECL-MaxFlow needed guards around two empty-worklist launches and a fix to an
integer-truncated average-degree calculation. Kernel logic is unchanged. Flow
results are independently certified at runtime before returning `optimal=true`.
The initial native GDlog build inherited SM52 from the old library cache and
failed closure tests; the explicitly pinned SM89 build passes. These failures
are retained in the validation evidence.

The [source manifest](../src/backends/expansion/upstream/PROVENANCE.json) records
commits, licenses and SHA-256 hashes. The build verifies those hashes and emits
reviewable host-adapter patches in `library/build/expansion-generated/`.
Original sources under `problems/` are unchanged.

See the [complete screening report](../../validation/gpu_correctness_expansion/VALIDATION_REPORT.md)
for non-promoted candidates and limits. These results do not establish production
scale, performance rankings or portability to other GPU architectures.

## LLM integration

The packaged agent now catalogs all 37 definitions and exposes these five bounded
profiles. Its allowlist, input validation, selector fallback and result rendering
are integrated. See [agent integration and evaluation](../../docs/ALGORITHM_EXPANSION.md).
The expanded catalog uses base-model context without changing the frozen routing
adapter or training any weights. Live language routing remains unmeasured while
the local model endpoint is offline.
