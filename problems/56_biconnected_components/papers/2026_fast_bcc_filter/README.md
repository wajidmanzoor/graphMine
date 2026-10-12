Fast-BCC-Filter
===============

CUDA arbitrary-spanning-tree biconnected-component decomposition.

Actual upstream path is gpu/with_filter although README says in-memory/with_filter. Published experiments connect inputs; verify disconnected components and bridge/block conventions.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs) · [Local source snapshot](code/)

Snapshot: `147db596535064ee6ea43efbcab315d5b224a1a6`. Full provenance: [source manifest](../../../_sources/fast_bcc.json).

Implementation entry points:

- [gpu/with_filter/main.cu](code/gpu/with_filter/main.cu)
- [gpu/with_filter/euler.cu](code/gpu/with_filter/euler.cu)
- [gpu/with_filter/tags.cu](code/gpu/with_filter/tags.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
