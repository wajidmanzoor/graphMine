TopoGPU parallel topological sorting
====================================

CUDA topoSort_kernel2D and topoSort_kernel3D inside a persistent-homology pipeline.

Specialized to Morse/cubical-complex DAGs derived from image data; not a general edge-list DAG sorter. Retained as related GPU code, excluded from the general-problem target.

Collection status: shortfall or related artifact; see details below.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2610.10959) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data) · [Local source snapshot](code/)

Snapshot: `0f39a80e874dda736e90432ef1b4879f728b89d3`. Full provenance: [source manifest](../../../_sources/topogpu.json).

Implementation entry points:

- [src/morse_boundary.cu](code/src/morse_boundary.cu)
- [src/topo.cu](code/src/topo.cu)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
