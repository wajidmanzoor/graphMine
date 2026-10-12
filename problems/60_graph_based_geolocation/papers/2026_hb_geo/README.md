HB-Geo graph-learning geolocation
=================================

DGL/PyTorch CUDA graph model with hop-constrained subgraphs and binary gates.

Specialized to IP-network graphs and traceroute-derived features. Requires supervised splits and preprocessing. The three city configurations are one algorithm, not three.

Collection status: local GPU code and paper; eligible for the collection target.

Paper role: `algorithm`.

[Publication](https://doi.org/10.1186/s42400-026-00644-w) · [Local PDF](paper.pdf)

[Upstream source](https://github.com/LuckyBoy0517/HB-Geo) · [Local source snapshot](code/)

Snapshot: `3c2d65ce19199ed963e16d0617003a478b05fa23`. Full provenance: [source manifest](../../../_sources/hb_geo.json).

Implementation entry points:

- [HB-Geo_Shanghai/main.py](code/HB-Geo_Shanghai/main.py)
- [HB-Geo_Shanghai/lib/model.py](code/HB-Geo_Shanghai/lib/model.py)

Build and GPU execution have not been tested. These are upstream research artifacts, not registered GraphMine backends. Follow the upstream build instructions; submodules and external datasets may need separate retrieval.
