# SuperFuser: GPU influence-maximization repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The repaired GPU implementation is pinned to upstream commit
`1506d275671a456e41bbc7bcb294876615353b2d`. Root and canonical artifact copies
contain identical sources and native executables. The CPU InFuseR/HyperFuser
sources are unchanged; application selection remains quarantined.

## Original failures

The historical audit passed 17 of 18 probability-one quality checks. One
64-vertex chain run selected vertex 25, reaching 39 of 64 vertices and missing
the original 0.63 quality threshold. Its three chain runs returned different
seeds despite the fixed random seed.

A fresh build of the pinned original passes those 18 quality screens on this
run, but six chain outputs report incorrect spread. On the eight-vertex chain
it reports 5 for a seed whose actual spread is 8. On the 64-vertex chain it
reports 4, 4, and 5 for actual spreads of 59, 59, and 60. This fresh result is
recorded separately from the historical quality failure. The old audit checked
seed quality, not the printed spread column.

Both original binaries, the fresh build command, and per-case outputs are
preserved. The attempted baseline memcheck ended before the first instrumented
API call; that log does not establish a baseline sanitizer error or leak count.

## Changes

- Complete and validated CSR offsets handle isolates and arbitrary edge order.
  Probability 1 no longer overflows a signed threshold. Parallel arcs combine
  as independent attempts, self loops are removed, and endpoints/counts/
  probabilities are checked before kernel execution.
- Sample frontiers track each vertex/sample separately. Atomic first activation
  prevents duplicate writes, capacity overflow, and lost updates from the
  original shared per-vertex queue. Cascades run to convergence instead of
  stopping after 20 rounds.
- Sketch propagation uses two buffers until convergence instead of racing
  in place or truncating after 10 rounds. Rank initialization handles zero
  leading-bit counts without division by zero. Score reductions synchronize
  shared storage before another vertex reuses it.
- Random draws are indexed by edge, sample, and seed. This removes the original
  shared-XOR edge correlation. Separate keys distinguish ranks, selection
  samples, and the independent evaluation ensemble. Global sample IDs make
  draws independent of partition count.
- Selected vertices cannot repeat when the residual graph is exhausted.
  Cross-partition aggregation handles non-power-of-two shard counts. Sample
  counts larger than one block are tiled instead of silently truncated.
- Reported spread counts actual activations in a separate evaluation ensemble,
  avoiding reuse of the adaptively selected training ensemble. Training spread
  remains available in JSON. Unknown/ignored options now fail explicitly.
- CUDA launches and allocations are checked, memory requirements are bounded,
  and device-owned buffers clean up on normal and exceptional exits. Native
  Makefile builds use the repaired production source.

The implementation retains GPU sketch-based Monte Carlo greedy selection and
GPU forward cascades. CPU code aggregates scores and selects their maximum;
independent CPU graph oracles exist only in the validation harness. Selection
remains approximate. JSON explicitly reports `guarantee_met: false`.

## Validation

**28,522 numerical/stress/configuration checks, 92 CUDA sanitizer cases, and
162 rejection checks passed.** These include 62,843 selected-prefix spread
checks and 1,136,512 full GPU sketch/activation-state comparisons; CUDA
sanitizer runs add 1,104,128 state comparisons. Only final clean builds and
the native production build contribute to these totals.

| Final suite | Coverage | Result |
|---|---|---|
| Numerical | 13,874 solver cases, 31,153 seed prefixes | All passed |
| Core state | 259 cases, 568,256 vertex/sample/prefix states | All passed |
| Repeated stress | 38 cases repeated five times, 435 prefixes | All passed; 152 repeat equalities verified |
| Host ASan/UBSan | Complete numerical and core-state suites, with leak checking | All passed; results identical to normal builds |
| CUDA sanitizers | 23 cases each under memcheck, initcheck, racecheck, and synccheck | No errors or warnings; zero leaked bytes |
| CLI | Normal and host-sanitized builds: 16 positive / 54 rejection checks each | All passed |
| Native Makefile binary | 16 CLI positives, 54 rejections, all 18 historical fixtures | All passed; every historical fixture reaches the optimum |

The numerical suite covers all **4,096 directed four-vertex graphs**, with seed
budgets 1, 2, and 4; all **729 three-vertex probability assignments** from
`{0, 1/2, 1}`, with budgets 1 and 2; 90 random weighted small graphs; and 38
stress configurations. Stress includes empty graphs, isolates, zero
probabilities, parallel arcs, loops, forward/reversed paths through 513
vertices, fans, a dense 65-vertex graph, a 4,097-vertex star, and four
65,536-sample probability-calibration cases. Tests vary sketch type, launch
size, random seed, sample count, and logical partition count.

For every returned seed prefix, an independent Python bitset transitive
closure computes sampled live-graph reachability. Both training and evaluation
spreads match exactly. Core tests compare every GPU sketch cell against the
maximum initial rank over independently reachable residual vertices, including
the active/inactive mask, and check GPU reductions with a float tolerance.

Small-case quality uses exhaustive enumeration of independent live-edge
outcomes and every eligible seed subset to compute the true expected spread
and optimum. All 13,855 numerical quality screens meet the original 0.63
threshold; the minimum ratio is **2/3**. Independent evaluation estimates also
pass a predeclared Hoeffding calibration screen. These checks establish bounded
empirical quality, not a general approximation guarantee or certified failure
probability. Forward path fixtures reach the optimum; reversed paths are
checked for the stated quality threshold because sketch ties can select a
different seed.

Logical partition counts 1, 2, 3, and 5 and block sizes 32, 256, and 1024 produce
identical seeds, training spread, and evaluation spread on the partition
fixture. This exercises uneven sample partitioning and aggregation on one
physical GPU; it does not certify execution across multiple physical GPUs.

## Reproduce and inspect

From this directory, in the validated CUDA 12.8 / SM 89 environment:

```sh
python3 build.py --work /tmp/superfuser-normal
python3 build.py --work /tmp/superfuser-asan --asan
python3 run_all.py --normal-build /tmp/superfuser-normal \
  --asan-build /tmp/superfuser-asan --work /tmp/superfuser-tests
```

Use fresh work directories. `build.py` extracts the pinned upstream files,
applies [repair.patch](repair.patch) using GNU patch, verifies every source
hash, and builds the production CLI and batch driver. `probe.cu` calls the same
production solver; its core mode exposes GPU state for comparison with the
independent oracle. `validate.py --corpus` can replay a saved corpus.
`production_suite.py` separately validates a native Makefile-built executable.

All GPU tests use physical GPU 1 through `CUDA_VISIBLE_DEVICES=1`. Host sanitizer
runs set `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0` for
CUDA virtual-address compatibility. [summary.json](summary.json) records counts;
[provenance.json](provenance.json) records source, patch, harness, binary, and
evidence hashes. Compressed corpora, commands, individual results, build logs,
sanitizer logs, and input-rejection diagnostics are in [evidence](evidence/).

The native executable installed at `bin/superfuser` in both artifacts has
SHA-256 `16068b927f8147edece2292ab2c8fe2660527c804aad796a3de7521660b841b2`.
All nine source hashes agree across the root artifact, canonical artifact,
fresh normal build, and fresh host-sanitized build.

## Contract and limits

The artifact's `REPAIR.md` documents the directed independent-cascade input,
probability normalization/32-bit threshold quantization, CLI limits, and
output fields. Linear-threshold diffusion is unsupported. Selection is
approximate, and enough GPU memory is required for the vertex/sample state.
Physical multi-GPU execution, paper-scale performance, and the separate CPU
algorithms remain outside this validation. The pinned upstream tree has no
explicit license file; that provenance gap is retained. Historical catalog
classifications and application quarantine are unchanged.
