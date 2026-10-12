PEA-BCC external-memory decomposition
=====================================

CUDA external-memory processing with streams and CPU/GPU transfers.

Distinct external-memory algorithm from the same paper. Host-memory capacity and stream settings are part of the experiment.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local source snapshot](code/)

Snapshot: `147db596535064ee6ea43efbcab315d5b224a1a6`. Full provenance: [source manifest](../../../_sources/fast_bcc.json).

Implementation entry points:

- [external/streams/main.cu](code/external/streams/main.cu)
- [external/streams/ExternalSpanningTree.cu](code/external/streams/ExternalSpanningTree.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
