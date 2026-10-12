Tensorized Floyd-Warshall
=========================

PyTorch CUDA dense min-plus tensor operations.

Entry function FW_GPU. Dense O(n^2) storage; inspect infinity and zero-weight conventions when importing arbitrary graphs.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/2310.03983) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/tanjary21/APSP_GPU) · [Local source snapshot](code/)

Snapshot: `92935ab3a16c59dccb948da8f198381881793e19`. Full provenance: [source manifest](../../../_sources/apsp_tensor.json).

Implementation entry points:

- [apsp.py](code/apsp.py)
- [main.py](code/main.py)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
