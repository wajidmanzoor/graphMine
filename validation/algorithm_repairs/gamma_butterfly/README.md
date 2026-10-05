# GAMMA butterfly-counting repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The GAMMA `sm` executable now reports exact injective matching counts for the
validated butterfly/C4 workload. On a bipartite graph with all-zero vertex
labels and the supplied unconstrained all-zero C4 query, divide
`matching_embeddings` by eight to obtain the butterfly count. Colored queries
have different automorphisms; their output is the raw matching count.

Final clean-build results: **24,932 numerical/stress checks, 224 CUDA sanitizer
checks, and 80 rejection checks passed**. `summary.json`, `provenance.json`, and
compressed `evidence/` record the actual commands, outputs, source hashes, and
binary hashes. Failed/development runs are excluded from these totals.

## Failure and repair

The original executable returned 16 embeddings for a single K2,2, where eight
are required, crashed on isolated vertices, and returned 1,435 rather than
1,680 embeddings on the original complete-bipartite fixture. Fresh baseline
outputs are preserved in `evidence/baseline.json`.

The optimized expansion checked only part of each embedding for duplicate
vertices and reused an intersection whose relevant vertices could change.
The repaired matcher uses GAMMA's existing GPU count/scan/insert primitives and
full injectivity, label, degree, and adjacency validator. Candidate expansion
starts from an actual required query neighbor. A disconnected query prefix
enumerates all data vertices. Query leaves and isolated query vertices are
matched, packed constraints use their actual slot count, and wildcard labels
work at the first vertex as well as later vertices.

Counts, scan offsets, and insert positions are 64-bit. Prefix sums detect
overflow. Intermediate embeddings are allocated to their measured size;
the final level is counted without materialization. This avoids the old fixed
600-million-entry output cache and six-billion-entry managed pool for this
path. Padding never follows an uninitialized predecessor, warp insertion offsets
are synchronized, and all successful/rejected-call resources are released.
Empty inputs and empty candidate sets return zero. Public result output works
without debug logging; the old debug-count line is retained.

The `sm` entry point validates binary CSR and label sizes, monotone offsets,
sorted unique loop-free adjacency, symmetry, vertex bounds, query constraints,
and CLI arguments before GPU loading. Data graphs are simple and undirected;
patterns have 1–7 vertices and use non-induced matching. These requirements are
explicitly rejected when violated instead of being silently misinterpreted.

## Verification

The primary corpus contains 2,065 cases: every bipartite graph on fixed
2-by-3, 2-by-4, and 3-by-3 partitions; all 1,024 simple graphs on five vertices;
seeded random graphs and relabelings; empty graphs, cycles, paths, disconnected
components, complete bipartite graphs, and warp boundaries. It also exercises
all 24 query permutations, colored/wildcard queries, ordering constraints,
leaves, disconnected query prefixes, and path queries through seven vertices.

All four graph-storage modes pass the primary corpus normally, after GPU
allocations are filled with `0xa5`, and under ASan/UBSan with leak checking.
Independent references use common-neighbor pair counts plus explicit
four-vertex cycle enumeration; colored/general queries use injective
permutation enumeration. Neither reference supplies answers to GAMMA.

Two complete-bipartite stress cases exercise wide counts in every storage mode.
K364,364 produces **34,917,730,848 embeddings**, or **4,364,716,356 butterflies**,
so even the butterfly count exceeds 32-bit range. CUDA memcheck (including GPU
leaks), initcheck, synccheck, and racecheck pass 56 cases each. Separate normal
and ASan CLI suites cover debug/quiet output, paths containing spaces, and 40
rejection cases each. The production Makefile-built binary passes all 12 original
fixtures in all four storage modes.

## Reproduce and limits

The patch is pinned to upstream commit
`3e01be68ededb8dcc4fa44bdb069a945a822232c`; `manifest.json` records the remote,
patch SHA-256, and all 16 source hashes. From this directory:

```sh
python3 build.py --work _work/replay-build
python3 build.py --work _work/replay-asan --asan
python3 run_all.py --build _work/replay-build --asan-build _work/replay-asan --work _work/replay-tests
```

`--upstream PATH` selects another clone containing that commit. `--arch` selects
the build architecture. Replay uses physical GPU 1. Host sanitizers keep leak
and UB checking enabled and use `protect_shadow_gap=0` for CUDA compatibility.

Validation used one RTX 6000 Ada GPU (SM 89), C++17, and the installed CUDA
toolkit. The largest tested graph has 1,003 vertices; the largest directed CSR
has 264,992 arcs. This repaired path stores intermediate embeddings on the GPU;
it does not establish GAMMA's original out-of-core or adaptive-cache performance
claims. Intermediate frontiers above the kernel's 32-bit input limit fail
explicitly, and GPU capacity still limits materialized frontiers. The legacy
`kcl`, `fsm`, optimized dynamic expansion, and adaptive memory controller are
outside this validation. Agent integration and historical catalog classifications
are unchanged. No explicit upstream license was detected; this repair does not
resolve that existing licensing gap.
