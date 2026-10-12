g2miner_formula induced graphlets
=================================

Problem: [Graphlet Counting](../../problem.json).

Connected vertex-induced graphlet class counts for supported sizes (3 and 4). No per-vertex orbit counts are supplied; request include_orbit_counts=false.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://www.usenix.org/conference/osdi22/presentation/chen
Source: https://github.com/chenxuhao/GraphMiner
Pinned commit: `2a76e3f612e40e46a821d603ca11d10fcbc63ddd`.

Implementation paths:

- `code/src/motif/gpu_formula.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
