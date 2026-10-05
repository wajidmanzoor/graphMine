# Maximum-Clique-on-GPU repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The 2024 many-core maximum-clique implementation and its GraphMine native
adapter were repaired on 2026-10-04. The original eight-vertex cycle with
chord `0--2` aborted with `SIGABRT` through the library. It now returns the
maximum size **3**, a valid clique in the original vertex IDs, and
`optimal=true`. This remains the artifact's CUDA branch-and-bound search;
the CPU reference solvers are used only for validation.

Upstream: <https://github.com/stefanoquer/Maximum-Clique-on-GPU>, commit
`62708c588219cc4d176ef55bbce9e5a21ad8c6d2`.
[repair.patch](repair.patch) applies to that exact commit and includes the
preexisting compatibility and adapter-support changes. The initial local
delta is retained separately in
[evidence/baseline/preexisting.patch](evidence/baseline/preexisting.patch).
[library.patch](library.patch) records the native adapter, provenance, and
regression-test changes against the library base commit recorded in
[provenance.json](provenance.json).
Upstream copyright notices and `LICENSE` are preserved.

## What changed

| Defect | Correction |
|---|---|
| An owned-copy request returned a borrowed CUDA-managed pointer, which the adapter passed to `free()` | The copy helper now allocates an owned host copy for managed storage too |
| The adapter requested size-only search, then read unwritten clique vertices | It uses the witness-recording search path and validates reduced vertex indices before restoring IDs |
| Sorting already sorted core keys left vertex degrees in their original order | One permutation is applied to names and degrees; CUB sorts use separate input and output buffers |
| Queue creation copied unused host buffers over device counters and membership flags | Device queues initialize their own state on every call; process-wide first-call initialization was removed |
| A packed-Boolean atomic read beyond the end of membership arrays | Queue membership uses aligned 32-bit atomic words |
| Coloring decisions and worker state changed while other threads still read them | Block and warp barriers separate reads from updates; warp termination stays local to the warp |
| Shared work-queue publication relied on ordinary shared-memory accesses | Shared queue tickets and payloads use explicit atomic operations |
| Recolor and warp-reduce could wait forever for blocks that could not become resident | The selected kernel's actual occupancy determines the persistent grid and worker allocations |
| Temporary solver copies destroyed owned streams; evaluation could read an unwritten incumbent | Standalone solvers are constructed in reserved storage, and evaluation skips an unmodified input bound |
| Heuristic scratch allocations leaked and a `new` allocation was freed with `free()` | Scratch ownership, deallocation, and stream synchronization were corrected |

The permanent native test covers the original regression with string IDs,
added isolates, repeated calls, an invalid lower bound, and a triangle in a
lower-core component preceding a higher-core bipartite component. The
production backend identifies itself as the **2026-10-04 repair** in result
provenance. The local CLI must be rebuilt with the CMake target
`graphmine_cli`.

## Independent checks

All final campaigns passed:

| Campaign | Checks passed |
|---|---:|
| Clean native build: exact size, original-ID witness, optimality, and bound | 2,219 |
| Production CMake-linked native backend | 2,219 |
| GPU and host allocations dirtied before initialization | 2,219 |
| Host AddressSanitizer and leak detection, with numerical verification | 2,219 |
| Repeated native execution | 580 |
| Valid caller-supplied lower bounds | 102 |
| Standalone counts: 137 graphs × seven configurations | 959 |
| **Total clique-result checks** | **10,517** |
| Per-vertex core vectors, normal and poisoned builds | 4,438 |
| Invalid lower bounds correctly rejected | 51 |
| Native CUDA sanitizers: 12 fixtures × four tools | 48 |
| Standalone CUDA sanitizers: three fixtures × seven configurations × four tools | 84 |

The production CLI regression, the permanent native API regression test,
and the existing agent exclusion-policy test also passed. CUDA racecheck
reports zero hazards, including warnings. Development runs are excluded
from these totals.

[manifest.json](manifest.json) contains 2,219 deterministic graph fixtures:

- All 1,253 graph-atlas graphs through seven vertices.
- 400 seeded random graphs on 8–12 vertices and 100 on 13–90 vertices.
- 124 structural and boundary cases, including complete, bipartite,
  multipartite, regular, disconnected, empty, and word-boundary graphs.
- 240 vertex permutations, 100 isolate extensions, and two direct regressions.

Every vertex subset is checked on 1,931 fixtures, independently cross-checked
against NetworkX's Bron–Kerbosch clique enumerator. Another 116 use the
clique enumerator directly; 172 have an analytic or invariant-derived
reference. The largest graph has 513 vertices; the densest has 32,896 edges.

Native checks compare the exact maximum size, uniqueness and range of every
returned vertex, every pairwise edge in the original graph, `optimal`, and
the returned upper bound. A separate CUDA driver checks every vertex's
core number against NetworkX. Calls are batched within one process to expose
stale state and lifetime defects. Empty and edgeless inputs exercise the
native facade's explicit trivial-result paths.

Additional campaigns check repeated execution, valid and invalid supplied
bounds, poisoned GPU allocations plus host `MALLOC_PERTURB_=165`, the
production CMake-linked backend, and host AddressSanitizer with leak
detection. All four Compute Sanitizer tools run on native search fixtures
and all seven standalone configurations: block `psanse`, `number`,
`recolor`, `renumber`, `reduce`, plus warp `psanse` and `reduce`.

Final counts and per-case results are recorded in
[evidence/summary.json](evidence/summary.json). Development probes and failed
intermediate builds are excluded from passing totals. The original abort,
the out-of-bounds atomic, synchronization hazards, and occupancy deadlocks
remain documented in [evidence/baseline](evidence/baseline).

## Reproduce

From the workspace root, with CUDA 12.8, a C++20 compiler, Python, and
NetworkX 2.8.8 installed:

```bash
repair=graphMine-repo/validation/algorithm_repairs/maximum_clique_on_gpu
upstream=problems/02_maximum_clique/papers/2024_maximum_clique_many_core_gpu/code
python "$repair/build.py" --source-checkout "$upstream" --output /tmp/mcp-release
python "$repair/build.py" --source-checkout "$upstream" --output /tmp/mcp-dirty \
  --poison-allocations --targets probe core_probe
python "$repair/build.py" --source-checkout "$upstream" --output /tmp/mcp-asan \
  --host-asan --targets probe
python "$repair/run_all.py" --build /tmp/mcp-release --poison-build /tmp/mcp-dirty \
  --asan-build /tmp/mcp-asan --output /tmp/mcp-results --gpu 1
```

Builds extract the pinned local Git commit without fetching, apply the
checked patch, verify source hashes, and compile with `-O3 -lineinfo` for
SM 89 by default. Every output directory must be new. To replay integration
checks as well, pass `--native-cli`, `--native-test`, and `--native-probe`
to `run_all.py`. The recorded native backend targets SM 86 plus PTX and was
also exercised on the Ada GPU. Build commands and binary hashes are under
[evidence/builds](evidence/builds).

AddressSanitizer requires
`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0` in this
CUDA environment; `run_all.py` sets it for that campaign. Without the
CUDA-compatible memory-layout setting, even an independent
`cudaGetDeviceCount()` probe reports an allocation failure before any
algorithm runs. Address and leak checking remain enabled.

The full campaign uses physical GPU 1 through `CUDA_VISIBLE_DEVICES=1`;
GPU 0 hosts the user's model. Detailed versions are recorded in
[evidence/environment.json](evidence/environment.json).

## Scope

Validated behavior is exact maximum-clique size and one original-ID witness
through the single-GPU native `psanse` path. The standalone configurations
were checked for maximum size; the other coloring modes do not implement
the native witness contract. These are bounded tests on simple undirected
graphs, not a universal correctness proof. Multi-GPU execution, exhaustive
tied-clique output, and other hardware remain unvalidated. BEL input does
not preserve an explicit count of isolated vertices; the native graph API
does.

The agent's automatic selection policy remains quarantined pending its
separate application re-audit. Historical catalog classifications and the
six build-blocked exclusions were not changed. Changes and evidence are
local; no GitHub push was performed for this repair.
