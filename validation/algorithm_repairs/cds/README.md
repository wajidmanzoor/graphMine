# CDS: exact densest k-clique subgraph repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The original small `k=2` case returned **1.73333** although its optimum and
its own densest-core lower bound were **2**. The repaired CUDA executable
returns **2**, with the five original vertices `[0, 1, 2, 3, 4]` and their
10 induced edges. Two smaller regressions are retained: a K4 joined by one
edge to a triangle or a four-cycle. Both have optimum **1.5**; the original
executable returned **1.46429** and **1.41477**, respectively.

All **8,650 numerical/stress runs, 72 CUDA sanitizer runs,
and 25 rejection checks pass** on the final clean builds.

This is a standalone repair of the upstream CUDA CLI. It has not been
integrated into the GraphMine library or agent. Historical validation
classifications still describe the original executable. The six excluded
build-blocked implementations were not modified.

## What changed

- Removed an invalid entropy upper bound. On the original regression it was
  1.8, below an already feasible density of 2. Component pruning now uses the
  valid integer bound `component_clique_count / k`.
- Replaced tolerance-based density bisection and incomplete preflow termination
  with exact rational improvement steps. The GPU retains CDS's clique-incidence
  network, using unsigned 64-bit capacities and a complete push–relabel solve.
  Separate CUDA phases initialize memory, push flow, and update heights.
  Residual distances accelerate both delivery to the sink and return of excess
  to the source. No cooperative-grid occupancy assumption or fixed launch
  stride remains in this flow stage.
- Added original vertex IDs, the induced clique count, and a full-precision
  density in a `CDS_RESULT` JSON line. Each improving residual cut is checked
  against its integer cut gain before its density is accepted. Host code
  evaluates the GPU witness and orchestrates ratio updates; it does not solve
  the optimization problem on the CPU.
- Initialized clique-degree counters. Clique-core peeling now retires each
  clique once, uses atomic bounded degree decrements, and processes all queue
  batches instead of skipping entries after the first 32. Queue and clique
  partition overflows stop execution.
- Counted cliques in 64 bits before checking the retained trie index limit;
  corrected candidate-mask clearing sizes, a host copy that read eight bytes
  from a four-byte density variable, an unnecessary argmax readback with
  uninitialized padding, and allocation lifetimes.
- Handled empty graphs, graphs with no requested cliques, and `k > n`.
  Rejected malformed adjacency lists, unsupported heuristic early stopping,
  invalid arguments and checked capacity/index overflow. CUDA assertions stay
  enabled in Release builds, and an explicit CMake architecture is honored.

## Why the density result is exact

Let `C` be the component's number of k-cliques, and let the current feasible
density be `p/q`. CDS's incidence network, scaled by `q`, gives a vertex
subset `S` cut capacity

```text
k*q*C - k*(q*C(S) - p*|S|).
```

Source-to-vertex capacity is `q * clique_degree`; vertex-to-clique capacity
is `q`; clique-to-vertex capacity is greater than the entire source capacity;
vertex-to-sink capacity is `k*p`. A completed maximum flow equal to `k*q*C`
proves that no subset improves the current density. A smaller flow yields a
nonempty residual-cut witness with a strictly greater rational density.
The next solve uses that witness's actual count/size ratio. There is no
floating-point stopping tolerance or early success on an unfinished flow.

The existing clique-core pruning remains: any optimal positive-density subset
has minimum induced clique degree at least the ceiling of a feasible lower
bound, so that core retains an optimum. Removing edges outside retained
k-cliques preserves this objective, and the best density over the resulting
components equals the global optimum.

## Validation

| Suite | Passed |
|---|---:|
| Full exact density and witness sweep | 5,281 |
| Doubled scratch buffers | 1,028 |
| Every allocation poisoned with `0xa5` | 1,028 |
| Integer capacities scaled by `2^40` | 1,028 |
| Repeat sweep 1 | 95 |
| Repeat sweep 2 | 95 |
| Repeat sweep 3 | 95 |
| CUDA memcheck | 18 |
| CUDA initcheck | 18 |
| CUDA synccheck | 18 |
| CUDA racecheck | 18 |
| Invalid input / capacity rejection checks | 25 |

The main sweep contains **5,281 graph/k cases over 1,782 graphs**:

- All **1,253 graph-atlas graphs through seven vertices**, each at `k=2,3,4`:
  3,759 runs.
- 300 seeded random graphs, 100 vertex permutations and 50 additions of
  isolated vertices: 852, 287 and 144 runs, respectively.
- Empty graphs, complete graphs, paths, cycles, stars, bipartite graphs,
  windmills, barbells and the original fixtures. Higher-order checks include
  `k=5,6`.
- Larger sparse graphs, long paths/barbells, 2,800 disjoint triangles plus a
  K4, and a 2,048-triangle windmill. These cover queue batches over 32 entries,
  bitmap boundaries, thousands of components and shared-clique contention.

Each result is compared with an independent integer maximum-closure oracle
using NetworkX's CPU max-flow implementation and a different network reduction.
The reference is cross-checked by enumerating every vertex subset on
**4,092 cases** with at most ten vertices. Validation checks total GPU clique
enumeration, unique/in-range output vertices, actual induced clique count,
exact count/size optimum, and result metadata. Optimal vertex sets need not
be unique. Sanitizer selections contain positive-clique cases that execute
CUDA work; empty and other host-only early exits are covered numerically.

The largest tested graph has **8,404 vertices and 8,406 edges**. The largest
enumerated clique family has **10,057 cliques**. The poisoned build fills every
project-owned GPU allocation with `0xa5` before normal initialization. The
wide-capacity build multiplies both sides of every rational threshold by
`2^40`, preserving the problem while testing large integer flows.

The largest tested source capacity is **1,459,628,074,151,706,624**, on
`random_007_k3`. This exceeds both 32-bit range and the consecutive-integer
precision of a double; the implementation uses unsigned 64-bit integers.

The original-binary comparison allows its six-significant-digit formatting;
it records **3 genuine density failures among 26 cases**, rather than treating
rounding alone as an algorithm failure. Development probes are excluded from
the final pass totals.

## Evidence and replay

- [Pinned source and hashes](provenance.json), [complete repair patch](repair.patch)
- [Graph/k manifest and exact reference fractions](manifest.json)
- [Final summary](evidence/summary.json) and [main per-case results](evidence/full/results.json)
- [Original failures](evidence/baseline/sweep/results.json)
- [Clean-build records](evidence/builds/normal.json), [poisoned build](evidence/builds/poison.json),
  [wide-capacity build](evidence/builds/wide.json)
- [Additional suite summary](evidence/extra/suite-summary.json), including
  separate numerical, sanitizer and rejection results

Numerical and sanitizer stdout is retained in each suite's `logs.tar.gz`.
Rejection logs remain plain text. The original small failure also has a
[plain-text log](evidence/baseline/original-small-k2.log).
Build products and development logs are ignored under `_work/`.

From this directory, with CUDA 12.8, CMake, a C++17 compiler, Python 3.12,
and NetworkX 2.8.8 available:

```bash
python3 build.py --source-checkout /path/to/pinned/CDS --output _work/replay-normal
python3 build.py --source-checkout /path/to/pinned/CDS --output _work/replay-poison --poison-allocations
python3 build.py --source-checkout /path/to/pinned/CDS --output _work/replay-wide --capacity-scale 1099511627776

python3 validate.py --binary _work/replay-normal/build/main --output _work/replay-full
python3 run_extra_suites.py --normal _work/replay-normal/build/main --poison _work/replay-poison/build/main --wide _work/replay-wide/build/main --output _work/replay-extra
```

The scripts default to GPU 1; use `--gpu` to select another device. Builds use
SM89 by default and accept `--arch`. They archive upstream commit
`3e704f98cf873336e2cf789570774039c8d6f092` from local Git objects, verify and
apply the repair patch, and verify the resulting source hashes. No network
download or working-tree source dependency is needed. `validate.py --generate
full` regenerates fixtures and reference fractions.

The CLI still takes `graph k pSize cpSize glBufferSize partitionSize earlyStop`.
Exact execution requires `earlyStop=-1`. The format is an unweighted simple
undirected graph: header `n m`, followed by rows `vertex sorted_neighbors...`
in vertex order, with symmetric adjacency and no loops or duplicate neighbors.

## Scope

Tests ran on GPU 1, an NVIDIA RTX 6000 Ada (SM89), with driver 570.211.01,
CUDA 12.8.93, Compute Sanitizer 2025.1.0.0, GCC 13.3 and CMake 3.28.3.
GPU 0 was reserved for the user's existing workload.

The repaired CLI solves unweighted k-clique density. The zero-vertex graph
uses the standalone convention `density=0, vertices=[]`; a nonempty graph
without requested cliques returns a singleton of density zero. Weighted
objectives, minimum-size constraints, other GPUs, multi-GPU execution and
GraphMine API/agent integration are outside this validation. Input storage
and trie/network indices retain checked 32-bit limits, scratch capacity is
explicit, and no performance claim is made for larger published workloads.

The pinned upstream checkout has no explicit license. This package retains
that provenance status and does not enable a library backend automatically.
The repair remains local and has not been pushed to GitHub.
