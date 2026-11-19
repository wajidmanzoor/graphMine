# Similarity & comparison

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

How alike are two vertices or two graphs, or which link is missing? Compare network neighborhoods, score possible missing links, or compare and align graphs through edit distance, common subgraphs or vertex correspondences.

**Start with this question:** How alike are two vertices or two graphs, or which link is missing?

[Explore these operations](../explorer.md#family/similarity) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [SimRank and General Vertex-to-Vertex Structural Similarity](#simrank_vertex_similarity)
- [Link Prediction](#link_prediction)
- [Graph Edit Distance and Maximum Common Subgraph](#graph_edit_distance_mcs)
- [Pairwise Network Alignment](#network_alignment)

## SimRank and General Vertex-to-Vertex Structural Similarity {#simrank_vertex_similarity}

Compute a pairwise structural similarity score between vertices based on the recursive principle that two vertices are similar to the extent their in-neighbors (or neighbors) are similar, for a single source vertex, a query pair, or top-k over all vertices.

$$
s(u,v)=\frac{C}{|N(u)||N(v)|}\sum_{a\in N(u)}\sum_{b\in N(v)}s(a,b)
$$

Distinct vertices use the recursive neighbor similarity; self-similarity and empty-neighbor cases follow the contract.

**Example question:** “Which vertices have similar relationship patterns?”

**Input assumptions.** direction: directed or undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mode requires every reported score within convergence_tolerance of the fixed point; approximate mode must disclose error_bound.

**Required outputs:** `similarity_scores`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`simrank`](../explorer.md#problem/simrank_vertex_similarity) | `cpp` | — | Numerical |

**`simrank`** — Native float64 SimRank fixed-point iteration with a recomputed contraction error bound. Incoming or undirected-projection neighborhoods; drop loops and duplicates, ignore weights. Single-source output excludes itself. Top-k ports explicitly disclose omitted pairs.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run simrank INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/simrank_vertex_similarity) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/29_simrank_vertex_similarity/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [ClipSim: A GPU-friendly Parallel Framework for Single-Source SimRank with Accuracy Guarantee](https://dl.acm.org/doi/10.1145/3588707). ACM Transactions on Database Systems, 2023.

## Link Prediction {#link_prediction}

Score and rank currently unconnected vertex pairs according to a declared structural link-prediction measure.

$$
\operatorname{rank}\{(u,v)\notin E\}\text{ by }s(u,v)
$$

s is the declared structural score, such as common-neighbor count or Jaccard similarity.

**Example question:** “Which currently missing connections score highest?”

**Input assumptions.** direction: directed or undirected measure dependent; weights: ignored in version 1; timestamps: optional for time filtering; vertex attributes: optional for candidate filters; edge attributes: optional for candidate filters.

**Guarantee.** complete=true means all eligible candidates were scored before top-k selection.

**Required outputs:** `ranked_predictions`, `evaluated_candidate_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`link-prediction`](../explorer.md#problem/link_prediction) | `cpp` | `libcugraph` | Numerical |

**`link-prediction`** — Undirected simple neighborhoods; loops and weights ignored. CPU supports eight local measures; GPU supports Jaccard. Candidate limits apply before top_k; capped output is explicitly incomplete.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run link-prediction INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/link_prediction) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/19_link_prediction/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- cuGraph Cosine neighborhood link scores — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Jaccard link scores — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Overlap-coefficient link scores — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Sorensen-Dice link scores — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Graph Edit Distance and Maximum Common Subgraph {#graph_edit_distance_mcs}

Given two graphs, compute either the minimum total cost of vertex/edge insertions, deletions, and substitutions transforming one graph into the other (graph edit distance), or a largest common induced or non-induced subgraph shared by both (maximum common subgraph).

$$
\operatorname{GED}(G,H)=\min_{\tau:G\to H}\sum_{e\in\tau}c(e)
$$

tau is a sequence of edits. Maximum-common-subgraph mode instead maximizes the size of a common subgraph under the declared matching rules.

**Example question:** “How many edits separate these two graphs?”

**Input assumptions.** direction: directed or undirected matched across pair; weights: ignored unless cost definition uses them; timestamps: ignored; vertex attributes: optional as labels; edge attributes: optional as labels.

**Guarantee.** Exact mode requires optimal=true; approximate/time-budgeted mode must disclose lower_bound or approximation_bound.

**Required outputs:** `task_result`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-edit-distance`](../explorer.md#problem/graph_edit_distance_mcs) | `cpp` | — | Exact |
| [`maximum-common-subgraph`](../explorer.md#problem/graph_edit_distance_mcs) | `cpp` | — | Exact |

**`graph-edit-distance`** — Exact bounded native partial correspondences over simple normalized directed or undirected graphs. Selected categorical vertex/edge labels; decimal rational costs. Vertex label replacement costs insertion plus deletion, edge substitution competes with deletion plus insertion. Returns normalized graphs and an ordered stable-handle script whose total is checked against the optimum. Weights and timestamps are ignored.

**`maximum-common-subgraph`** — Exact bounded native induced matching, or label-compatible maximum vertex matching for non-induced output where isolated vertices are allowed. Preserve direction and selected categorical labels, ignore weights/timestamps. Returns a checked common graph and injective correspondence. No secondary maximum-edge objective. Explicit loop/parallel normalization.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-edit-distance INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_edit_distance_mcs) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/24_graph_edit_distance_mcs/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [A GPU Based Maximum Common Subgraph Algorithm for Drug Discovery Applications](https://people.cse.nitc.ac.in/jayaraj/files/ipdps_online_paper.pdf). IEEE (Chicago), 2016. Author-hosted proceedings version; replaces an unavailable older PDF link. Checked November 19, 2026.
- [Efficient Accelerated Graph Edit Distance Computation on GPU](https://arxiv.org/abs/2605.00830). ICCS 2026, 2026 · [Author code](https://gitlab.jsc.fz-juelich.de/dabah2/fast-ged.git).

## Pairwise Network Alignment {#network_alignment}

Given two graphs and optional vertex-similarity priors, find a vertex mapping between them that maximizes conserved topology (and prior similarity, when supplied), either as a global one-to-one mapping or a local many-to-one set of high-scoring alignments.

$$
\max_M\bigl(\operatorname{topology}(M)+\operatorname{prior}(M)\bigr)
$$

M is an admissible vertex mapping; its cardinality, injectivity, weights, and objective are specified by the contract.

**Example question:** “Which vertices correspond between these networks?”

**Input assumptions.** direction: undirected or directed matched across pair; weights: optional; timestamps: ignored; vertex attributes: optional as similarity prior; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true and is only expected to terminate on small graph pairs; approximate mode must disclose objective_value and, when known, approximation_bound.

**Required outputs:** `vertex_mapping`, `objective_value`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`network-alignment`](../explorer.md#problem/network_alignment) | `cpp` | — | Exact |

**`network-alignment`** — Exact bounded global injective assignment covering every vertex of the smaller graph. Maximize topology_weight times conserved edge value plus pair priors. Direction must match. Drop loops and collapse unweighted or sum nonnegative weighted parallel edges. Weighted conservation is the minimum of paired normalized edge weights.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run network-alignment INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/network_alignment) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/25_network_alignment/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Graphics processing unit-based alignment of protein interaction networks](https://pmc.ncbi.nlm.nih.gov/articles/PMC8687428/). IET Systems Biology, 2015. The originally recorded author code site is unavailable. The paper remains available. Checked November 19, 2026.
- [cuAlign: Scalable Network Alignment on GPU Accelerators](https://www.pnnl.gov/publications/cualign-scalable-network-alignment-gpu-accelerators). IA^3 2023 (SC23 workshop), 2023.
- [A GPU-based method for network alignment](https://ieeexplore.ieee.org/document/10822748/). IEEE, 2024.
- [Pygmtools: A Python Graph Matching Toolkit](https://jmlr.org/papers/v25/23-0572.html). Journal of Machine Learning Research 25(33), 2024 · [Author code](https://github.com/Thinklab-SJTU/pygmtools).
- [Pygmtools: A Python Graph Matching Toolkit](https://jmlr.org/papers/v25/23-0572.html). Journal of Machine Learning Research 25(33), 2024 · [Author code](https://github.com/Thinklab-SJTU/pygmtools).
- [Pygmtools: A Python Graph Matching Toolkit](https://jmlr.org/papers/v25/23-0572.html). Journal of Machine Learning Research 25(33), 2024 · [Author code](https://github.com/Thinklab-SJTU/pygmtools).
