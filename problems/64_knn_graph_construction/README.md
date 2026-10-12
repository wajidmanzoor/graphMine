k-Nearest-Neighbor Graph Construction
=====================================

Construct a graph connecting each feature vector to its k nearest distinct input vectors under a declared distance metric.

[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · [Full sweep](../_collection/README.md)

Collected 3 records; 3 eligible local GPU implementation/research-paper pairs (target: 3).

| Algorithm / record | Paper | GPU source | Eligible pair |
|---|---|---|---|
| [2017_faiss_flat_knn](papers/2017_faiss_flat_knn/README.md) | local | local | yes |
| [2019_torch_cluster_knn](papers/2019_torch_cluster_knn/README.md) | local | local | yes |
| [2021_cuvs_nn_descent](papers/2021_cuvs_nn_descent/README.md) | local | local | yes |

The collection target is met for the documented variants.

Framework papers and distinct implementation variants may share a publication. These are collection counts, not validation of builds, GPU correctness or runtime backends. See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.
