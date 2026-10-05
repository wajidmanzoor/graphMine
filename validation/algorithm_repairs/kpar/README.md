# kPAR repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

kPAR now returns `min(k,n)` distinct vertices, including isolated query seeds,
and rejects incompatible or malformed offline indexes. It remains an approximate
GPU top-k personalized PageRank implementation. The graph is an unweighted
directed multigraph with consecutive IDs `0..n-1`, restart probability `0.2`, and
dangling transitions back to the query seed. Self loops and parallel edges are
retained because they affect transition probabilities.

## Original failure and repairs

The preserved original binary wrote five rows for `k=4` on a 16-cycle. Its old
64-cycle audit omitted the seed; a fresh reproduction returned an empty result.
Both fresh outputs are in `evidence/baseline.json`. The high-frequency cutoff
indexed element 10,000 of vectors containing only 16 or 64 elements, so the old
behavior was undefined rather than a stable numerical discrepancy.

The patch fixes that cutoff, the output off-by-one, skipped candidate sets of
size at most k, insufficient-candidate stopping, zero-size kernel launches,
isolated seeds, full candidate allocation, and a missing shared-memory barrier
in the high-degree push kernel. When threshold selection cannot certify enough
candidates, it scores the complete candidate complement on the GPU. Equal
computed scores use vertex ID as a secondary output sort key.

The original `16/n` sampling threshold was too coarse for small graphs and large
k. The repair uses `1/n`. Offline random walks are reproducible via `--seed`.
Their dangling restart is at the local walk origin, whereas the online push
restarts at the query seed; these are different transition operators. Graphs
with dangling vertices therefore finish the existing GPU forward propagation
until the total residual bound is at most `1e-13`, without using those biased
sampled contributions. CPU linear algebra is used only by the independent tests.

Input repairs validate graph counts, endpoints, queries, numeric CLI options,
index offsets/frequencies/sample conservation, and index capacity. An optional
missing PR/outdegree ranking no longer reads an uninitialized vertex. New
`KPAR2` indexes bind samples to graph structure, epsilon, alpha, and threshold
scale. Legacy indexes must be rebuilt. Resource ownership also covers rejected
indexes and write failures. Directory creation no longer invokes a shell.

## Verification

Final clean-build results: **44,288 numerical query checks, 96 CUDA sanitizer
query checks, and 116 rejection checks passed**. Sixteen repeated offline index
builds were byte-identical. Counts and compressed per-query evidence are in
`summary.json` and `evidence/`. Development failures and the initial ASan startup
failure are excluded from successful check totals.

The 166-graph corpus includes all 64 directed simple graphs on three vertices,
60 seeded random graphs, cycles, chains, stars, disconnected components,
isolates, self loops, duplicate edges, and warp/block boundary sizes. The largest
case is a bidirectional 550-by-550 biclique: 1,100 vertices and 605,000 directed
edges. It exercises the large-frontier block push. Tests force high-frequency
partitions of 0, 1, and 10,000, shard size 2, k of 1/4/above n, epsilon 0.5/0.1,
and three independent sampling seeds. A further sweep uses epsilon 0.01.

The reference uses sparse Markov power iteration to L1 change below `2e-14` and
independently checks a dense linear solve for n at most 65. Checks require exact
result cardinality, unique IDs, finite nonnegative scores, descending output,
approximate rank separation, and full-vector mass within `1e-8`. Score tolerance
is `epsilon * max(reference_score, 1/n) + 1e-10`; dangling-graph completion must
match within `2e-10`. This is empirical validation of an approximate algorithm,
not a proof that stochastic top-k membership is exact.

CUDA memcheck, initcheck, synccheck, and racecheck cover all execution paths and
the high-degree case. Host ASan/UBSan retains leak checking. On this machine,
ASan's default shadow-gap protection prevents CUDA initialization; the replay
uses `protect_shadow_gap=0`. The unmodified setting's startup failure is retained
separately. Production execution does not need ASan settings.

## Reproduce

The source comes from the official v1.0 release archive, SHA-256
`791987a738faf84d0fcab882b2f74cbb2efd4451ac9888b80e0d120ea6421916`.
`manifest.json` records its URL, the patch hash, and all 16 repaired source hashes.
The release's obsolete bundled CUB is replaced by toolkit CUB; the build uses
C++17 and SM 89 without fast-math or unused GSL dependencies. GPL licensing is
unchanged.

From this directory, using fresh work directories:

```sh
python3 build.py --work _work/replay-build
python3 build.py --work _work/replay-asan --asan
python3 run_all.py --build _work/replay-build --asan-build _work/replay-asan --work _work/replay-tests
```

Pass `--archive PATH` when the release ZIP is elsewhere and `--arch` when building
for another CUDA architecture. Tests deliberately isolate physical GPU 1. This
repair was validated on a single RTX 6000 Ada GPU; other architectures,
large production data, performance, and application integration remain untested.
Historical catalog failures and agent quarantine are preserved.
