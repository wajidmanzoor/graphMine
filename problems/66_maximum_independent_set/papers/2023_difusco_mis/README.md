DIFUSCO independent set
=======================

Problem: [Maximum Independent Set](../../problem.json).

CUDA diffusion model followed by CPU/NumPy feasibility decoding. Report heuristic quality and checkpoint identity; feasibility does not certify optimality.

GPU execution: GPU neural diffusion; CPU final decoding.

Paper relationship: algorithm.
Paper: https://papers.nips.cc/paper_files/paper/2023/hash/0ba520d93c3df592c83a611961314c98-Abstract-Conference.html
Source: https://github.com/Edward-Sun/DIFUSCO
Pinned commit: `65eb3b7bde76097c0d3438ce743fa6769baf9ce5`.

Implementation paths:

- `code/difusco/pl_mis_model.py`
- `code/difusco/utils/mis_utils.py`

Artifact state: paper=downloaded; code=downloaded_archive.
Counts toward three local pairs: true.

Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.
Source availability is separate from license compatibility and runtime validation.
