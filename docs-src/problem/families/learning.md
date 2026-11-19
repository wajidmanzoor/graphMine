# Learning & embeddings

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Learn from features and labels, or learn vectors for vertices or triples. Train vertex, graph or hypergraph predictors, condense training data, infer locations under a declared model, or learn node and knowledge-graph embeddings. Hypergraph inputs are an eligibility requirement, not a separate family.

**Start with this question:** Learn from features and labels, or learn vectors for vertices or triples.

[Explore these operations](../explorer.md#family/learning) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Node Classification and Regression](#node_classification_regression)
- [Graph Classification and Regression](#graph_classification_regression)
- [Hypergraph Node Classification and Regression](#hypergraph_node_learning)
- [Learned Graph Condensation](#graph_condensation)
- [Graph-Based Geolocation](#graph_based_geolocation)
- [Node Embedding](#node_embedding)
- [Knowledge-Graph Embedding](#knowledge_graph_embedding)

## Node Classification and Regression {#node_classification_regression}

Train or apply a graph model to predict categorical labels or numerical targets for specified vertices.

$$
\hat y_v=f_\theta(G,X)_v
$$

The declared graph model produces labels or numerical targets; held-out evaluation determines predictive performance.

**Example question:** “Predict labels for these vertices using the supplied model settings.”

**Input assumptions.** direction: directed or undirected; weights: ignored; timestamps: ignored; vertex attributes: required features and split labels; edge attributes: ignored.

**Guarantee.** Learned estimates; no globally optimal model is required.

**Required outputs:** `predictions`, `metrics`, `model_state`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`node-learning`](../explorer.md#problem/node_classification_regression) | `cpp` | — | Learned estimate |

**`node-learning`** — Native simplified graph convolution: declared mean-message layers, then a trained linear softmax or scalar regression readout. Numeric vertex_features and training_labels use objects containing typed {vertex,value} rows. Disjoint train/validation/test IDs; preprocessing and loss use training labels only. Transductive unlabeled features/topology are explicit. Saved coefficients, split metrics, objective and convergence status; one self message, collapsed parallels, weights ignored.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run node-learning INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/node_classification_regression) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/52_node_classification_regression/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Semi-Supervised Classification with Graph Convolutional Networks](https://arxiv.org/abs/1609.02907). ICLR 2017, 2016 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- [Graph Attention Networks](https://arxiv.org/abs/1710.10903). ICLR 2018, 2017 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- [Inductive Representation Learning on Large Graphs](https://arxiv.org/abs/1706.02216). NeurIPS 2017, 2017 · [Author code](https://github.com/pyg-team/pytorch_geometric).

## Graph Classification and Regression {#graph_classification_regression}

Predict one categorical label or numerical target for each graph in a collection.

$$
\hat y_i=f_\theta(G_i,X_i)
$$

Each graph receives a categorical or numerical prediction.

**Example question:** “Predict a label for each graph in this collection.”

**Input assumptions.** direction: directed or undirected; weights: ignored; timestamps: ignored; vertex attributes: optional features; edge attributes: optional features.

**Guarantee.** Approximate learned model.

**Required outputs:** `predictions`, `metrics`, `model_state`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-learning`](../explorer.md#problem/graph_classification_regression) | `cpp` | — | Learned estimate |

**`graph-learning`** — Native independent per-graph mean message passing, sum/mean pooling, and trained linear softmax or scalar regression readout. Structural [one,in-degree,out-degree] or declared attribute features; empty graphs pool to zeros. graph_labels uses typed {graph,value} rows. Train-only fitted preprocessing and supervised loss, disjoint graph splits and saved model state. Weights ignored; no cross-graph edges.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-learning INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_classification_regression) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/53_graph_classification_regression/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Hierarchical Graph Representation Learning with Differentiable Pooling](https://arxiv.org/abs/1806.08804). NeurIPS 2018, 2018 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- [How Powerful are Graph Neural Networks?](https://arxiv.org/abs/1810.00826). ICLR 2019, 2018 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- [Self-Attention Graph Pooling](https://arxiv.org/abs/1904.08082). ICML 2019, 2019 · [Author code](https://github.com/pyg-team/pytorch_geometric).

## Hypergraph Node Classification and Regression {#hypergraph_node_learning}

Train or evaluate a declared hypergraph neural model to predict vertex labels or targets while preserving hyperedge incidence.

$$
\hat y_v=f_\theta(H,X)_v
$$

H preserves hyperedge incidence; predictions follow the declared hypergraph model.

**Example question:** “Predict vertex labels using these multiway relationships.”

**Input assumptions.** direction: undirected hypergraph; weights: optional nonnegative hyperedge weights; timestamps: ignored; vertex attributes: required features and split specific targets; edge attributes: ignored.

**Guarantee.** Statistical learning with declared split, seed and tolerance; no deterministic optimum claim.

**Required outputs:** `predictions`, `model_artifact`, `split_metrics`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`hypergraph-node-learning`](../explorer.md#problem/hypergraph_node_learning) | `cpp` | — | Learned estimate |

**`hypergraph-node-learning`** — Native hgnn-linear-v1: weighted hyperedge feature means followed by normalized vertex incidence means and a trained linear softmax/regression layer. No pairwise projection. Isolates retain features, singleton edges remain. Feature, target and split attributes are explicit; only train labels fit parameters or preprocessing. Record model state, finite predictions and metrics with split denominators. Optional model_parameters declare layers and optimizer settings.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run hypergraph-node-learning INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/hypergraph_node_learning) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/65_hypergraph_node_learning/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Hypergraph Neural Networks](https://arxiv.org/abs/1809.09401). AAAI 2019, 2018 · [Author code](https://github.com/iMoonLab/DeepHypergraph).
- [HNHN: Hypergraph Networks with Hyperedge Neurons](https://arxiv.org/abs/2006.12278). Research preprint, 2020 · [Author code](https://github.com/iMoonLab/DeepHypergraph).
- [HyperGCN: A New Method of Training Graph Convolutional Networks on Hypergraphs](https://papers.nips.cc/paper/2019/hash/1efa39bcaec6f3900149160693694536-Abstract.html). NeurIPS 2019, 2019 · [Author code](https://github.com/iMoonLab/DeepHypergraph).

## Learned Graph Condensation {#graph_condensation}

Learn a smaller synthetic attributed graph whose supervised training utility approximates that of the original training graph.

$$
\widetilde G,\widetilde X,\widetilde Y\ \approx_{\mathrm{utility}}\ G,X,Y
$$

The smaller synthetic graph targets supervised utility; it is not an exact topological copy.

**Example question:** “Create a smaller synthetic attributed graph for this prediction task.”

**Input assumptions.** direction: undirected; weights: optional nonnegative adjacency weights; timestamps: ignored; vertex attributes: required features labels and splits; edge attributes: ignored.

**Guarantee.** Learned approximation measured by held-out downstream utility, with no structural equivalence claim.

**Required outputs:** `synthetic_graph`, `training_metadata`, `utility_metrics`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-condensation`](../explorer.md#problem/graph_condensation) | `cpp` | — | Learned estimate |

**`graph-condensation`** — Native gradient_matching_linear_sgc_v1 matches training softmax gradients at zero readout parameters. Learn synthetic features and fix class-balanced labels on declared edgeless adjacency; this is not graph coarsening. Original weighted SGC features use summed parallel weights plus self messages; reject original loops. Budget must cover training classes and not exceed training vertices. Train labels only, explicit transductive features/topology, new synthetic IDs. Evaluate full versus synthetic training on held-out original labels over declared seeds; report objective and utility variance.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-condensation INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_condensation) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/70_graph_condensation/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Condensing Graphs via One-Step Gradient Matching](https://arxiv.org/abs/2206.07746). ACM KDD 2022, 2022 · [Author code](https://github.com/Emory-Melody/GraphSlim).
- [Graph Condensation via Receptive Field Distribution Matching](https://arxiv.org/abs/2206.13697). Research preprint, 2022 · [Author code](https://github.com/Emory-Melody/GraphSlim).
- [Graph Condensation for Graph Neural Networks](https://arxiv.org/abs/2110.07580). ICLR 2022, 2021 · [Author code](https://github.com/Emory-Melody/GraphSlim).

## Graph-Based Geolocation {#graph_based_geolocation}

Infer geographic coordinates for unlocated vertices using declared graph propagation or supervised graph-learning models.

$$
\hat z_v\in\mathbb R^2
$$

Coordinates are inferred from the declared graph model and known locations; they are estimates.

**Example question:** “Estimate locations for vertices without coordinates.”

**Input assumptions.** direction: method declared; weights: optional nonnegative; timestamps: ignored; vertex attributes: required seed locations and method specific features; edge attributes: optional method specific features.

**Guarantee.** Estimates are model-dependent; graph layout coordinates are not geographic predictions.

**Required outputs:** `locations`, `confidence`, `converged`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-geolocation`](../explorer.md#problem/graph_based_geolocation) | `cpp` | — | Heuristic |

**`graph-geolocation`** — Native spatial propagation by sequential discrete geodesic median coordinate descent. Minimize positive edge weight times spherical distance, restricting coordinates to seed locations in each connected component. Undirected nonnegative input, reject loops, sum parallels. Fixed seeds remain exact; seedless components remain unresolved. Haversine handles the antimeridian; report dispersion, stopping status and optional held-out geodesic errors. No supervised model or calibrated confidence claim.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-geolocation INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_based_geolocation) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/60_graph_based_geolocation/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Sparsity is not an obstacle: An accurate and efficient IP geolocation framework based on Graph Transformer](https://doi.org/10.1016/j.comnet.2026.112287). Computer Networks, 2026 · [Author code](https://github.com/LuckyBoy0517/GT-Geo).
- [HB-Geo: a street-level IP geolocation method based on hop-constrained subgraphs and binary gates](https://doi.org/10.1186/s42400-026-00644-w). Cybersecurity, 2026 · [Author code](https://github.com/LuckyBoy0517/HB-Geo).

## Node Embedding {#node_embedding}

Learn a vector for every vertex under a declared graph representation-learning objective.

$$
Z\in\mathbb R^{|V|\times d}
$$

Each row is a learned vertex representation under the declared embedding objective.

**Example question:** “Represent each vertex with a vector.”

**Input assumptions.** direction: directed or undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Numerical stochastic optimization; no unique embedding or global optimum is implied.

**Required outputs:** `embeddings`, `training_summary`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`node-embedding`](../explorer.md#problem/node_embedding) | `cpp` | — | Learned estimate |

**`node-embedding`** — Native second-order LINE or DeepWalk/node2vec fixed-window contexts, optimized with full-softmax cross entropy and declared L2 regularization. Weighted outgoing transitions preserve direction unless projection is requested. Explicit loop handling and summed parallel weights; every vertex receives source and context vectors. Report actual context masses, objective, gradient norm, seed and stopping reason; no global optimum or unique embedding claim.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run node-embedding INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/node_embedding) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/50_node_embedding/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [DeepWalk: Online Learning of Social Representations](https://arxiv.org/abs/1403.6652). KDD 2014, 2014 · [Author code](https://github.com/DeepGraphLearning/graphvite).
- [LINE: Large-scale Information Network Embedding](https://arxiv.org/abs/1503.03578). WWW 2015, 2015 · [Author code](https://github.com/DeepGraphLearning/graphvite).
- [node2vec: Scalable Feature Learning for Networks](https://arxiv.org/abs/1607.00653). KDD 2016, 2016 · [Author code](https://github.com/DeepGraphLearning/graphvite).

## Knowledge-Graph Embedding {#knowledge_graph_embedding}

Learn entity and relation representations from typed directed triples for relational link prediction.

$$
s(h,r,t)=f(z_h,z_r,z_t)
$$

The declared embedding model scores typed directed triples; a score is not a verified relationship.

**Example question:** “Score candidate relationships in this knowledge graph.”

**Input assumptions.** direction: directed; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: required edge type.

**Guarantee.** Approximate learned model; held-out ranking quality is evaluated separately from training loss.

**Required outputs:** `entity_embeddings`, `relation_embeddings`, `training_summary`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`knowledge-graph-embedding`](../explorer.md#problem/knowledge_graph_embedding) | `cpp` | — | Learned estimate |

**`knowledge-graph-embedding`** — Native DistMult with mean logistic loss over declared training positives and fixed sampled corruptions, plus L2 regularization. Relations come only from the training split; duplicate triples collapse, distinct relation identities and self triples remain. Validation never affects fitting. Report entity/relation parameters, training examples and filtered head/tail ranking metrics with average ties; no unseen-relation inference.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run knowledge-graph-embedding INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/knowledge_graph_embedding) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/51_knowledge_graph_embedding/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Embedding Entities and Relations for Learning and Inference in Knowledge Bases](https://arxiv.org/abs/1412.6575). ICLR 2015, 2014 · [Author code](https://github.com/awslabs/dgl-ke).
- [Complex Embeddings for Simple Link Prediction](https://arxiv.org/abs/1606.06357). ICML 2016, 2016 · [Author code](https://github.com/awslabs/dgl-ke).
- [RotatE: Knowledge Graph Embedding by Relational Rotation in Complex Space](https://arxiv.org/abs/1902.10197). ICLR 2019, 2019 · [Author code](https://github.com/awslabs/dgl-ke).
