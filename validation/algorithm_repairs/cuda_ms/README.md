# CUDA-MS single-clique repair

**Integration update — 2026-10-05:** this repaired profile is now exposed by the
library and agent. See the [integration evidence](../../repaired_library/REPORT.md)
and [current profile limits](../../../library/docs/repaired_algorithms.md).
The rest of this report records the earlier repair phase; statements about
standalone status or agent quarantine describe that phase.

The seeded nine-vertex regression now returns the maximum clique
`[2, 4, 6, 7]`, of size four, with original string IDs and `optimal=true`
through the native API and production CLI. The optimized original CUDA
implementation returned three. The old debug executable happened to return
four on this fixture; both observations are preserved.

This repair changes the single-result CUDA contract: the Motzkin–Straus
relaxation supplies a feasible initializer, followed by completed GPU
branch-and-bound. It does not make local relaxation a global certificate.
No CPU maximum-clique solver is used by the implementation. CPU and
multi-result CUDA entry points retain their heuristic semantics and are
explicitly labeled as such by the standalone CLI.

## Defects and changes

- The local support mask can discard every global optimum. The new
  `exact_cuda.cuh` searches the full original graph, honoring an optional
  allowed-vertex mask. An incumbent is accepted only after checking its
  feasibility. Every clique belongs to the root tree of its largest vertex.
  Greedy independent color classes bound each candidate prefix; only those
  proven bounds and feasible incumbents prune search. Completion is required
  before success. Allocation or CUDA failure returns an error with null masks.
- Search stacks and witnesses belong to individual GPU workers. Only the
  incumbent size is shared atomically. Witness selection occurs after kernel
  completion, preventing a size/witness publication race. Scratch allocation
  uses checked sizes and available device memory.
- Original warp reductions assumed implicit synchronization. Reduction
  stages, shared scratch reuse, prefix scans, full-row detection and result
  remapping now synchronize explicitly. Full-row detection handles partial
  warps; counter updates after remapping execute in one block.
- The relaxation overwrote `max_unsolved` with zero. It now honors the
  requested tolerance and has a strict iteration ceiling. Complete GPU search
  resolves the remaining uncertainty. Empty and restricted searches are
  supported without relying on relaxation convergence.
- Device initialization honors the caller's selected CUDA device. The C++
  adapter no longer references an OpenMP thread-local variable using a
  non-thread-local declaration. Random state belongs to each solver call and
  is released, along with CLI result masks and input matrices.
- Clique extraction continues past incompatible vertices. Its sort uses a
  context-aware comparator instead of a nested executable-stack trampoline,
  which failed under AddressSanitizer. Unused attenuation result storage is
  no longer accessed. Non-finite options, malformed DIMACS ASCII inputs,
  duplicate edges, invalid endpoints and inconsistent edge counts are rejected.
- Native provenance describes the GPU completion stage; the permanent
  maximum-clique test requires the four-clique from CUDA-MS. The common
  coloring bound remains an independent consistency check.

## Independent validation

Final clean builds pass **31,830 numerical/stress checks, 88 instrumented
CUDA graph cases (12 sanitizer processes), and 30 rejection checks**. Both
production maximum-clique CTests and the agent exclusion-policy test pass.
The largest tested graph has 2,049 vertices; the largest edge count is 32,896.

`manifest.json` contains 2,772 cases: the previous maximum-clique graph atlas,
random graphs, structural families, permutations and isolate additions;
the original nine-vertex regression; larger cases at 1,023/1,024/1,025/2,049
vertices; and 540 allowed-vertex cases. Small references enumerate vertex
subsets and independently compare with NetworkX Bron–Kerbosch. Larger
references use Bron–Kerbosch or analytic graph-family answers.

`run_all.py` checks exact sizes, witness edges, unique vertices, restrictions,
completion results and native string IDs. It exercises all six relaxation
modes, repeated in-process calls, every GPU allocation poisoned with `0xa5`,
and a variant that starts the complete search without a relaxation incumbent.
The cold variant ensures an accidentally good initializer cannot hide an
incomplete search. Host AddressSanitizer/UndefinedBehaviorSanitizer and CUDA
memcheck, initcheck, synccheck and racecheck are separate checks.

Final passing totals, binary hashes, inputs, per-case records and compressed
logs are recorded in `evidence/summary.json`. Development failures and the
superseded interrupted sweep are excluded from final totals. The original
optimized failure and racecheck hazards remain under `evidence/baseline-*`.

## Reproduction

From the workspace root, using the local pinned upstream repository:

```bash
python3 graphMine-repo/validation/algorithm_repairs/cuda_ms/run_all.py \
  --source-checkout problems/02_maximum_clique/papers/2019_maximum_clique_cuda/code \
  --output /tmp/cuda-ms-clean-replay --gpu 1
```

The output directory must not exist. Builds are reconstructed using `git
archive` at `a0b6b00a1f67b6fe65380b2efcb242cf40889d83`, then the checked
`repair.patch`. `provenance.json` verifies source and native integration
hashes. `library.patch` records native changes relative to the previous
repair's workspace state. All GPU work uses physical GPU 1, leaving the
model on GPU 0 untouched.

The production CLI target is `graphmine_cli`; building `graphmine` alone can
leave an old binary. The original standalone binary is preserved at
`_work/baseline-find_cliques`, and the optimized pre-repair build is preserved
at `_work/baseline-optimized`.

## Scope

This evidence covers one exact clique on a single SM89 GPU, all six
single-result relaxation initializers, restricted vertex masks, and native
ID restoration. It does not establish performance on large research graphs,
other hardware, concurrent host calls, multi-GPU execution, exact CPU
optimization, or tied-clique enumeration. GPU scratch grows with the square
of the vertex count per worker; this is a correctness repair, not a scaling
claim. The legacy binary-DIMACS and adjacency-matrix parsers are not included
in the malformed-input validation contract.

The Python agent remains quarantined pending a separate application re-audit.
Historical catalog classifications and GPL-3.0-or-later licensing are
unchanged. Changes are local and have not been pushed to GitHub.
