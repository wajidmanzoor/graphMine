HGNN-Part learned hypergraph partitioning
=========================================

PyTorch CUDA hypergraph generative model training/inference.

Hybrid method with CPU spectral initialization and traditional partitioner refinement. External partitioners/checkpoints are not all included in the upstream tree.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://doi.org/10.23919/DATE69613.2026.11539511) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/THU-numbda/HGNN-Part) · [Local source snapshot](code/)

Snapshot: `0a70e44f3bccbb06c386edaf84927433c9441cb7`. Full provenance: [source manifest](../../../_sources/hgnn_part.json).

Implementation entry points:

- [models.py](code/models.py)
- [train.py](code/train.py)
- [test.py](code/test.py)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
