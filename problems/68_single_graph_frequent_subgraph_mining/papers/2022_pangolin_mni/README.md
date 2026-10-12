pangolin single-graph MNI mining
================================

Problem: [Frequent Subgraphs in One Labeled Graph](../../problem.json).

Labeled single-host-graph domain/MNI support. The upstream driver reports the number of frequent patterns; pattern listing and unsupported size bounds must not be claimed. This does not implement graph-database transaction support in problem 14.

GPU execution: Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.

Paper relationship: framework.
Paper: https://arxiv.org/abs/1911.06969
Source: https://github.com/chenxuhao/GraphMiner
Pinned commit: `2a76e3f612e40e46a821d603ca11d10fcbc63ddd`.

Implementation paths:

- `code/src/pangolin/fsm/base.cu`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
