# GPU4GST: TrimCDP-WB correctness repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The repaired target is the non-hop-constrained `code/TrimCDP-WB` variant of
GPU4GST, pinned to upstream commit `716a19c240c480cb2d23435bbaca55163a48e174`.
The root artifact and canonical mirror contain identical repaired sources.
The original audit's timeout classification and application quarantine remain
attached to the original implementation; no backend is automatically enabled.

## Failures and changes

The original device-adapted executable hangs on the 8- and 64-vertex path
fixtures. Its hand-written whole-grid barrier assumes simultaneous residency,
while launch sizing uses another kernel's occupancy and rescales the block size.
The repair uses cooperative launches, actual kernel/block-size occupancy, and
CUDA grid synchronization. Queue construction, counter resets, and overflow
branch decisions now synchronize the complete grid.

Once the hangs were repaired, independent weighted tests exposed incorrect
costs. Grow/merge operations were clearing frontier flags while other threads
set them, and grow pruning looked up a lower bound at the source instead of the
destination. Complete-tree bounds also needed to be recorded at their actual
roots, including the case where both complementary masks already exist. A
weighted regression reported 12,884,901,894 instead of 6,442,450,947 before that
completion update was fixed. Tree certificates reject a cost that cannot be
realized by actual input edges.

Additional repairs:

- CUDA lower-bound copies target allocated device buffers, rather than the
  addresses of host pointer variables; counters and empty-mask bounds initialize.
- Work queues cover their actual original/virtual state capacity. Duplicate
  singleton relaxations trigger a synchronized unique-state scan before a
  compacted queue can overflow.
- Virtual rows have explicit end offsets. Appending virtual start offsets no
  longer overwrites the last original vertex's row boundary.
- Costs use signed 64-bit arithmetic and a distinct 2^58 infinity value, with
  representability and memory checks. Large finite costs no longer collide with
  the original 100,000 sentinel or truncate to 32 bits.
- Graph/group/query parsing rejects malformed input before GPU computation;
  undirected weighted reciprocity is validated. Empty graphs/groups, isolated
  vertices, repeated/overlapping groups, zero weights, loops, parallel arcs, and
  arbitrary neighbor order are handled.
- Host/GPU resources have complete cleanup on successful runs. Logical device 0
  respects `CUDA_VISIBLE_DEVICES`; both native builds work offline.

The algorithm retains GPU singleton shortest paths, TrimCDP grow/merge and
pruning, three-way work balancing, and virtual high-degree splitting. Host
certificate decoding follows equalities in GPU cost tables, then checks the
resulting tree. The independent CPU optimizer is confined to the test harness.

## Validation

**93,322 numerical/stress checks, 536 CUDA sanitizer checks, and 228 rejection
checks passed.** Normal and ASan/UBSan runs each independently validated 38,021
feasible tree certificates; repeated boundary and native-CLI checks add further
certificate coverage.

Final counts and source/binary hashes are recorded in [summary.json](summary.json)
and [provenance.json](provenance.json). Only final clean builds contribute to the
reported totals; intermediate failures are preserved separately.

The main numerical suite contains **45,901 queries across 1,207 graph cases**:
all 1,024 simple undirected five-vertex graphs with 40 queries each; 120 random
weighted graphs and 30 vertex relabelings with 32 queries each; and 33 boundary
families with 141 queries. Every small-graph optimum comes from an independent
enumeration of vertex subsets followed by Kruskal MST, not a duplicate of the GPU
recurrence. For larger paths, stars, dense graphs, and pendant-expanded small
cores, costs follow exact family formulas or the small-core oracle.

Every feasible result in this suite has its printed tree independently checked
for original edges/weights, connectedness, acyclicity, group coverage, and exact
cost. Coverage includes costs above 2^31 and 2^53, zero-cost cycles, all queue
classification boundaries, degrees 1,024/1,025/2,049, two split hubs, and graphs
with up to 262,656 directed arcs. The one-group and sixteen-group boundaries are
included. Repeated boundary runs check state reuse and scheduling variation.

The same complete corpus runs under host ASan/UBSan. CUDA memcheck, initcheck,
racecheck, and synccheck each exercise 134 repeated queries across 18 selected
cases; memory checking includes leak detection. CLI suites check malformed
arrays, asymmetric weighted arcs, invalid groups/ranges, output failures,
whitespace, duplicate members, and no visible GPU. Native Makefile and CMake
executables are checked independently of the fresh-build test binaries.

## Reproduce

From this directory on the validated CUDA 12.8 / SM 89 environment:

```sh
python3 build.py --work /tmp/gpu4gst-normal
python3 build.py --work /tmp/gpu4gst-asan --asan
python3 run_all.py --normal-build /tmp/gpu4gst-normal \
  --asan-build /tmp/gpu4gst-asan --work /tmp/gpu4gst-tests
```

Use fresh work directories; existing evidence directories are not overwritten by
`build.py`. It extracts the original files from the pinned Git commit, applies
[repair.patch](repair.patch), checks every source hash, and builds the actual
production entry point plus a batch driver. The batch driver only calls that
entry point repeatedly in one CUDA context; it supplies no substitute solver.
`validate.py` can replay a saved corpus with `--corpus`.

The harness uses physical GPU 1 via `CUDA_VISIBLE_DEVICES=1`. Host sanitizer runs
use `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0` for CUDA
virtual-address compatibility. Compressed logs/corpora under [evidence](evidence/)
retain individual results, certificates, diagnostics, and commands.

## Contract and limits

See the artifact's `REPAIR.md` for input layout and invocation. The repaired CLI
supports nonnegative undirected weighted GST with 1–16 query groups, representable
32-bit vertex-mask/queue indices, and enough GPU memory for its exact state
arrays. `(n-1) * max_edge_weight` must be below 2^58. `--witness` emits JSON tree
certificates; `min cost infeasible` represents an unsatisfiable query.

These tests establish the stated bounded correctness evidence, not paper-scale
performance. The other GPU4GST variants, including diameter-constrained and
no-virtual-split variants, remain outside this repair. The pinned upstream tree
has no explicit license file; that provenance gap is retained.
