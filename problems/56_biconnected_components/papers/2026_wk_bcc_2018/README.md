Wadwekar-Kothapalli 2018 GPU BCC baseline
=========================================

CUDA sampling/contraction baseline supplied by the Fast-BCC authors.

The attached 2026 paper documents and evaluates this baseline and cites the original 2018 paper, Expediting Parallel Graph Connectivity Algorithms. This is the later authors' distributed baseline, not a claim of original-author code.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `comparative_study`.

[Publication](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local source snapshot](code/)

Snapshot: `147db596535064ee6ea43efbcab315d5b224a1a6`. Full provenance: [source manifest](../../../_sources/fast_bcc.json).

Implementation entry points:

- [baselines/wk-bcc-2018/main.cu](code/baselines/wk-bcc-2018/main.cu)
- [baselines/wk-bcc-2018/src/final_bcc/vertex_merging.cu](code/baselines/wk-bcc-2018/src/final_bcc/vertex_merging.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
