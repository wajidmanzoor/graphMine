# MBE-GPU maximal biclique count repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The standalone `MBE_GPU` executable is repaired for nonempty maximal biclique
counting on one NVIDIA RTX 6000 Ada GPU, with CUDA 12.8.93 / SM89. The original
medium graph now produces **15**, matching the independent reference, in each
of the three single-GPU variants (`-s 0`, `-s 1`, `-s 2`).
All **4,419 numerical/stress runs** and **112 CUDA sanitizer runs** pass on the
final builds. Totals include repeated cases and overlapping suites.

The 2023 and 2025 paper entries both reference upstream commit
`4ef91a0c8fd9f756d5bb086fd11ce3e4bfff9942` of
[fhxu00/MBE-GPU](https://github.com/fhxu00/MBE-GPU). This report covers the
`MBE_GPU` target and its `MBE_GPU_NOPRUNE` comparison build. It does not establish
correctness of the distinct `GMBEv2` bitmap target or the multi-GPU variants.
The repair has not been integrated into the GraphMine library or agent.
Historical validation results still describe the original failing executable.

## Failures and repair

The original failure reduces to a single edge plus an isolated right vertex.
The scheduled GPU variant returned two maximal bicliques instead of one. A
graph with two isolated vertices and no edges returned one instead of zero.
Removing isolated rows from the original medium graph changed its incorrect
count of 16 to the expected 15.

The patch repairs the following paths without replacing GPU computation with
a CPU solver:

- Skip roots with empty neighborhoods. The scheduled intersection helper no
  longer reads `vertices[-1]`, and the other variants skip empty-root closure.
- Restore descendant traversal in the warp variant, which previously had an
  unconditional debugging `continue`. The two-row overlap fixture returned
  two bicliques instead of three before this change.
- Calculate warp buffer offsets with `size_t`. The block variant overflowed
  signed 32-bit multiplication on this 142-SM GPU. The original memory checker
  reports writes before the allocated buffer. Uninitialized, unused timing
  pointer reads are also removed from that variant.
- Synchronize the shared-memory windows used by neighborhood union, including
  window replacement. Synchronize block state before reusing it for a new root,
  including roots with no candidates.
- Transfer queued task payloads atomically and publish/release queue slots with
  acquire/release ordering. Forced task splitting exposed this path in race
  checks even when the final count was correct.
- Keep local counts and device-to-host count transfers at 64 bits. A separate
  diagnostic build starts the device count at `2^32` to check that the high
  word survives kernel accumulation and result readback.

`repair.patch` includes the earlier input-path buffer enlargement.
`fix-only.patch` contains this repair's changes to the GPU implementation and
helpers, excluding that earlier adaptation.

## Validation method

| Final suite | Passed | Coverage |
|---|---:|---|
| Full differential sweep | 3,075/3,075 | 1,025 graph cases through all three single-GPU variants |
| Input options and slower input path | 324/324 | Orders 0/1/2 and transpose options 0/1/2 on six fixtures |
| Poisoned scratch and 64-bit counter | 612/612 | 68 cases, three variants, three repetitions; scratch filled with `0xa5`, device counter starts at `2^32` |
| Forced task splitting | 204/204 | 68 cases repeated three times with height 2 and size 4 thresholds |
| Disabled pruning | 204/204 | 68 cases through all three variants of `MBE_GPU_NOPRUNE` |
| CUDA sanitizer checks | 112/112 | 28 checks each with memcheck, initcheck, synccheck, and racecheck, including forced queue handoffs |

[results.json](results.json) records the final suite totals, environment and
artifact hashes. [evidence/](evidence/) contains individual case results, build
provenance, and failing and passing sanitizer logs. Exploratory intermediate
builds and raw run directories remain under ignored `_work/`.

The independent oracle enumerates distinct, nonempty intersections of right
vertex neighborhoods. Each intersection is one closed left side, paired with
all right vertices containing it. A second oracle completes each partition
into a clique and uses NetworkX maximal-clique enumeration, excluding cliques
contained entirely in one partition. The two oracles are cross-checked on
graphs with at most 42 total vertices. Structured cases also have analytical
expected counts.

The full sweep contains all 512 labeled 3-by-3 bipartite graphs, 300 seeded
random graphs, 60 transposes, 60 relabelings with extra isolates, 25 larger
sparse graphs, and 68 original or structured cases. Each is run through all
three single-GPU variants. Other suites exercise input reordering and
transposition, the slower input path, disabled pruning, repeated forced task
splitting, and poisoned scratch memory. The largest structured count is
65,534 bicliques on the 16-by-16 crown graph.
The largest edge count tested is 17,947.

The harness requires successful process completion and the exact expected
count. Timeouts terminate the process group with `SIGKILL`: upstream's
`SIGTERM` handler can print a partial count and exit successfully. Sanitizer
runs must also have a zero-error/zero-hazard summary; a correct count alone
does not make a sanitizer run pass. No failing GPU result is replaced by the
CPU reference.

These are bounded **count** checks. The executable does not export complete
biclique memberships, so this report does not claim a validated membership
output contract. Inputs use sorted, unique, nonnegative left IDs in one row
per right vertex; blank rows represent isolates. The tests do not establish
arbitrary-input parsing, performance, the upstream degree/capacity limits,
leak freedom in a long-lived process, or portability beyond the recorded GPU
and toolchain. The count-offset diagnostic is not a claim to have enumerated
more than four billion bicliques.

For the roles of the different CUDA tools, see NVIDIA's
[Compute Sanitizer documentation](https://docs.nvidia.com/compute-sanitizer/ComputeSanitizer/index.html).
In particular, a racecheck result covers shared-memory hazards rather than all
possible global-memory races.

## Reproduce

Run from the GraphMine repository root. Set `MBE_SOURCE` to an existing local
checkout containing the pinned MBE-GPU commit and its CUB submodule commit
`ec07c16deb3ed8d21c7eefb4c40a89ad16ddb749`. The build script archives Git objects
from these checkouts, applies the checked patch in a new directory, verifies
source hashes, and builds optimized code with line information. It performs
no download and does not modify the supplied checkout.

```bash
python3 -m pip install -r validation/algorithm_repairs/mbe_gpu/requirements.txt
MBE_SOURCE=/path/to/MBE-GPU
MBE_REPAIR=validation/algorithm_repairs/mbe_gpu

python3 "$MBE_REPAIR/build.py" --source-checkout "$MBE_SOURCE" \
  --output "$MBE_REPAIR/_work/replay" --gpu 1
python3 "$MBE_REPAIR/validate.py" \
  --binary "$MBE_REPAIR/_work/replay/build/MBE_GPU" \
  --output "$MBE_REPAIR/_work/replay-full.json" --gpu 1 --workers 2

python3 "$MBE_REPAIR/build.py" --source-checkout "$MBE_SOURCE" \
  --output "$MBE_REPAIR/_work/replay-poison" --targets MBE_GPU \
  --poison-scratch --counter-seed 4294967296
python3 "$MBE_REPAIR/run_extra_suites.py" \
  --build "$MBE_REPAIR/_work/replay" \
  --poison-build "$MBE_REPAIR/_work/replay-poison" \
  --output "$MBE_REPAIR/_work/replay-extra" --gpu 1
```

`run_extra_suites.py` runs the option, slower-input, poisoned-memory/counter,
forced-splitting, unpruned, and sanitizer suites sequentially, and retains the
exact commands. It stops if any suite fails.

For sanitizer runs, add `--sanitizer memcheck`, `initcheck`, `synccheck`, or
`racecheck`, set `--workers 1`, and select cases with `--only`. The selector is
a regular expression. Use `--modes 2 --bound-height 2 --bound-size 4` to force
queue handoffs. Use a new output path for every run. The recorded tests use
GPU 1 to avoid the model process on GPU 0. Default upstream buffers need
roughly 19 GiB per block/scheduled process, so keep concurrency within GPU
memory capacity.

Upstream's recorded artifact has no explicit license file. The repair folder
contains patches and validation assets; it does not vendor another copy of
the upstream source or establish permission to redistribute that source.
