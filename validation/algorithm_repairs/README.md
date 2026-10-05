# Sequential algorithm repairs

This directory records repairs and aggressive correctness retesting of
implementations that failed or had incomplete validation. Each repair retains
the original failure, a patch against the pinned upstream commit, clean-build
instructions, independent oracles, and the final evidence.

| Implementation | Problem | Repair evidence |
|---|---|---|
| AccTD | k-truss decomposition | [Report](acctd/README.md): 2,691 numerical runs and 14 CUDA sanitizer runs passed, including exact per-edge labels |
| MBE-GPU | Maximal biclique enumeration | [Report](mbe_gpu/README.md): 4,419 numerical/stress runs and 112 CUDA sanitizer runs passed for single-GPU counts |
| CDS | Densest k-clique subgraph | [Report](cds/README.md): 8,650 numerical/stress runs, 72 CUDA sanitizer runs and 25 rejection checks passed, including exact densities and vertex witnesses |
| Maximum-Clique-on-GPU | Maximum clique | [Report](maximum_clique_on_gpu/README.md): 10,517 clique-result checks, 4,438 core-vector checks, 51 bound-rejection checks and 132 CUDA sanitizer runs passed; includes the native library and seven standalone configurations |
| CUDA-MS | Maximum clique | [Report](cuda_ms/README.md): 31,830 numerical/stress checks, 88 CUDA sanitizer cases and 30 rejection checks passed; includes exact GPU completion, native integration and standalone CLI |
| kPAR | Top-k personalized PageRank | [Report](kpar/README.md): 44,288 numerical query checks, 96 CUDA sanitizer queries, 116 rejection checks and 16 deterministic index rebuilds passed; approximate GPU scoring plus dangling-vertex residual completion |
| GAMMA butterfly | Butterfly counting via C4 matching | [Report](gamma_butterfly/README.md): 24,932 numerical/stress checks, 224 CUDA sanitizer checks and 80 rejection checks passed; includes all four graph-storage modes and counts above 32-bit range |
| GPU4GST / TrimCDP-WB | Group Steiner tree | [Report](gpu4gst/README.md): 93,322 numerical/stress checks, 536 CUDA sanitizer checks and 228 rejection checks passed; includes exact small-graph optima, tree certificates, 64-bit costs and virtual high-degree splits |
| SuperFuser | Influence maximization | [Report](superfuser/README.md): 28,522 numerical/stress/configuration checks, 92 CUDA sanitizer cases and 162 rejection checks passed; includes exact sampled spread, full GPU state oracles and exhaustive small-graph quality screens |

All nine repaired profiles are now integrated into the library and agent. See
[the public API and agent re-audit](../repaired_library/REPORT.md) and
[the supported profiles/build guide](../../library/docs/repaired_algorithms.md).
The two repaired maximum-clique backends are eligible for explicit agent selection;
pre-repair timing rankings have been retired.
Historical catalog classifications remain attached to the original binaries.
Passing a bounded count or scalar check does not establish an untested output
contract or enable a backend automatically.

The known incorrect-algorithm repair queue is complete within the scopes recorded
above. SuperFuser remains an approximate independent-cascade solver without a
certified quality/failure-probability guarantee. Partial-validation cases remain
separate follow-up work, including TDFS, partitioned dynamic PageRank,
GraphMiner / G2Miner k=3, and implementations missing required output certificates.

The user's six build-blocked exclusions remain excluded: **SIGMo,
MG-alphaGCD, FastGED, cuRipples, HyperBlocker, and GPUGraphLayout**.
