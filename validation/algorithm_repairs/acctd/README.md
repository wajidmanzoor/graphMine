# AccTD k-truss repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The `cuda-pkt-offload-opt` executable has been repaired and revalidated on
NVIDIA RTX 6000 Ada, SM89, CUDA 12.8.93 and GCC 13.3. The original medium
fixture now returns the correct **maximum trussness 8**, with exact labels for
every edge. All **2,691 numerical runs** and **14 CUDA sanitizer runs** pass.
The numerical runs compare **915,102 edge assignments** with independent CPU
references. These counts include repetitions and overlapping test suites.

This is a repair of the standalone AccTD executable. It has not yet been
integrated into the GraphMine library or enabled in the agent. Historical
validation results continue to describe the older, failing executable.

## Cause and changes

The original medium-graph failure reproduced three times with the same
histogram. Initial GPU triangle supports matched an independent reference;
seven final edge labels were too high. The peeling code allocated `processed`,
`inCurr` and `inNext` through `cudaMallocManaged`, without initializing all
membership flags before reading them. Reused allocation contents caused
triangle updates to be skipped. Explicitly clearing those buffers corrects all
seven labels without replacing the GPU algorithm with a CPU solver.

Expanded testing also exposed two boundary defects:

- Empty graphs entered code that assumes a nonempty level-offset array and
  positive CUDA launch dimensions. They now return an empty decomposition and
  maximum trussness zero before entering that path. Reading the zero-length
  degree vector and adjacency file is also handled explicitly.
- Bitmap initialization and recount kernels read an adjacency element for
  isolated vertices. A trailing isolated row points beyond the allocation.
  All four bitmap kernels now guard empty rows. The failing memory-check log
  is preserved in [the evidence](evidence/isolated-vertex-before-memcheck.log).

`ACCTD_EDGE_OUTPUT=/path/to/result.txt` exports `u v trussness` for every edge,
using the k-minus-two support convention. The tests use ordering `org`, so
these are the input CSR vertex IDs. This output permits checking the complete
decomposition instead of just its maximum or histogram. The optional diagnostic
`ACCTD_SUPPORT_OUTPUT` records support values at the CPU/GPU handoff.

## Validation

| Suite | Passed | Coverage |
|---|---:|---|
| Full differential sweep | 1,831/1,831 | All 1,253 graph-atlas graphs through seven vertices; 400 seeded random graphs; 80 vertex relabelings; original fixtures; structured, sparse, dense, disconnected and larger graphs |
| Poisoned-allocation stress | 708/708 | Clean upstream rebuild; fill every managed allocation with `0xa5`; repeat 236 cases with 1, 4 and 16 OpenMP threads |
| Forced triangle recount | 152/152 | Clean poisoned build forces the adaptive recount branch, including support recomputation and graph compaction |
| CUDA memory checks | 8/8 | Four isolated-vertex fixtures; both original fixtures; both original fixtures under forced recount |
| CUDA initialization, race and synchronization checks | 6/6 | Both original fixtures under each tool |

Every numerical case checks exact edge-set coverage, duplicate output edges
and every truss label. Expected labels come from a serial triangle-hypergraph
peeling oracle, independently cross-checked against NetworkX `k_truss` for
every threshold through one above the maximum. No GPU failure or missing
output is accepted as a pass or replaced with a CPU answer.

The largest graph has 1,120 vertices and 7,791 edges; the densest tested random
graph has 7,918 edges. This establishes the recorded bounded checks, not
large-graph performance, every upstream build variant, arbitrary input parsing,
the CPU-first path above the default 200-million-edge handoff threshold, or
portability to other GPU architectures. CUDA initcheck reported no issue on
the original managed-memory reproducer; the poisoned-allocation test is an
additional explicit check against dependence on allocator contents.

See [results.json](results.json) for binary and script hashes, suite totals and
environment; [evidence/](evidence/) contains per-case results and sanitizer logs.
The original failed histogram remains in
[original-baseline.json](evidence/original-baseline.json).

## Reproduce

Run from the GraphMine repository root with Python 3.12, the listed NetworkX
version, CMake, GCC/OpenMP, CUDA and Compute Sanitizer installed. Set `ACCTD_SOURCE`
to a local checkout containing upstream commit
`a8faa445ccb45c18383087db488eff9d1836d8d1`. `build.py` archives that commit,
applies the checked patch in a separate scratch checkout, verifies source
hashes and builds only the target under test. It does not modify the supplied
checkout. Each output directory must be new.

```bash
python3 -m pip install -r validation/algorithm_repairs/acctd/requirements.txt
ACCTD_SOURCE=/path/to/AccTrussDecomposition
ACCTD_REPAIR=validation/algorithm_repairs/acctd

python3 "$ACCTD_REPAIR/build.py" --source-checkout "$ACCTD_SOURCE" \
  --output "$ACCTD_REPAIR/_work/replay"
python3 "$ACCTD_REPAIR/validate.py" \
  --binary "$ACCTD_REPAIR/_work/replay/build/cuda-pkt-offload-opt" \
  --output "$ACCTD_REPAIR/_work/replay-tests" \
  --suite full --random-cases 400 --threads 4 --workers 4 --gpu 1

python3 "$ACCTD_REPAIR/build.py" --source-checkout "$ACCTD_SOURCE" \
  --output "$ACCTD_REPAIR/_work/replay-poison" --poison-allocations
python3 "$ACCTD_REPAIR/validate.py" \
  --binary "$ACCTD_REPAIR/_work/replay-poison/build/cuda-pkt-offload-opt" \
  --output "$ACCTD_REPAIR/_work/replay-poison-tests" \
  --random-cases 140 --repeats 3 --threads 1 4 16 --workers 4 --gpu 1

python3 "$ACCTD_REPAIR/build.py" --source-checkout "$ACCTD_SOURCE" \
  --output "$ACCTD_REPAIR/_work/replay-recount" \
  --poison-allocations --force-recount
python3 "$ACCTD_REPAIR/validate.py" \
  --binary "$ACCTD_REPAIR/_work/replay-recount/build/cuda-pkt-offload-opt" \
  --output "$ACCTD_REPAIR/_work/replay-recount-tests" \
  --random-cases 70 --threads 4 --workers 4 --gpu 1
```

Choose an available physical GPU with `--gpu`; the recorded runs used GPU 1.
For sanitizer runs, add `--sanitizer memcheck`, `initcheck`, `racecheck` or
`synccheck`, use `--only original --random-cases 0 --workers 1`, and select a
new output directory. The isolated-vertex memory suite uses `--only isolates`.

[repair.patch](repair.patch) includes the previously required CUDA-12/TBB
compatibility adaptations plus this repair, relative to the pinned upstream
commit. [fix-only.patch](fix-only.patch) isolates this session's changes against
the pre-repair adapted source. Source hashes and the upstream URL are recorded
in [provenance.json](provenance.json). Upstream's MIT license remains applicable.
