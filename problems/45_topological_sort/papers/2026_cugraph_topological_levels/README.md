cuGraph frontier-based topological levels
=========================================

CUDA indegree/frontier processing, including single- and multiple-GPU instantiations.

The C++ API returns a level per vertex. A valid ordered vertex list must be constructed from those levels. No associated research paper was verified.

Collection status: shortfall or related artifact; see details below.

Paper role: `none`.

[Upstream source](https://github.com/rapidsai/cugraph) · [Local source snapshot](code/)

Snapshot: `5931900cf6be7063cf855ef230fa14d4216b61de`. Full provenance: [source manifest](../../../_sources/cugraph.json).

Implementation entry points:

- [cpp/src/dag/topological_sort_impl.cuh](code/cpp/src/dag/topological_sort_impl.cuh)

[Supporting documentation](https://docs.nvidia.com/cugraph/latest/)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
