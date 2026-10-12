DGL-KE RotatE
=============

PyTorch CUDA score functions and embedding training in DGL-KE.

Original model paper plus DGL-KE system paper. Select the named model and GPU option; entity and relation encodings and negative sampling must be recorded.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://arxiv.org/abs/1902.10197) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/awslabs/dgl-ke) · [Local source snapshot](code/)

Snapshot: `e00bccfc4638db8b1f703ecedbf8db81faedb2bb`. Full provenance: [source manifest](../../../_sources/dgl_ke.json).

Implementation entry points:

- [python/dglke/models/pytorch/score_fun.py](code/python/dglke/models/pytorch/score_fun.py)
- [python/dglke/models/general_models.py](code/python/dglke/models/general_models.py)
- [python/dglke/train.py](code/python/dglke/train.py)

[Supporting framework paper](https://arxiv.org/abs/2004.08532) · [Local PDF](dgl_ke_paper.pdf)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
