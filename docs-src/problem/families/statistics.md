# Statistics & anomalies

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Is this unusual compared with a baseline or a random graph? Detect graph anomalies under an explicit baseline or assess significance against a declared null-model ensemble.

**Start with this question:** Is this unusual compared with a baseline or a random graph?

[Explore these operations](../explorer.md#family/statistics) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Graph Anomaly Detection](#graph_anomaly_detection)
- [Null-Model Significance Testing via Degree-Preserving Graph Randomization](#null_model_significance_testing)

## Graph Anomaly Detection {#graph_anomaly_detection}

Rank graph entities by how strongly their declared structural or temporal features deviate from a specified normality reference.

$$
a(v)=\operatorname{deviation}(\phi(v),\mathcal R)
$$

phi is the declared feature vector and R the reference for normal behavior; a score is not proof of wrongdoing.

**Example question:** “Which vertices are structurally unusual?”

**Input assumptions.** direction: definition dependent; weights: optional; timestamps: optional or required by features; vertex attributes: optional; edge attributes: optional.

**Guarantee.** Exactness means faithful feature and score computation; an anomaly score is relative to normality_reference, not universal ground truth.

**Required outputs:** `ranked_anomalies`, `scored_entity_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-anomalies`](../explorer.md#problem/graph_anomaly_detection) | `cpp` | — | Numerical |

**`graph-anomalies`** — Native structural and numeric features for vertices, original edge instances or supplied induced subgraphs. Population or explicit location/scale reference; weighted standardized L1, L2 or maximum deviation with declared minimum scale. Recompute scores, preserve zero-variance failures and disclose top-k truncation. Numerical deviation scores are not learned ground truth.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-anomalies INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_anomaly_detection) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/20_graph_anomaly_detection/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [PyGOD: A Python Library for Graph Outlier Detection](https://jmlr.org/papers/v25/23-0963.html). Journal of Machine Learning Research 25(141), 2024 · [Author code](https://github.com/pygod-team/pygod).
- [PyGOD: A Python Library for Graph Outlier Detection](https://jmlr.org/papers/v25/23-0963.html). Journal of Machine Learning Research 25(141), 2024 · [Author code](https://github.com/pygod-team/pygod).
- [PyGOD: A Python Library for Graph Outlier Detection](https://jmlr.org/papers/v25/23-0963.html). Journal of Machine Learning Research 25(141), 2024 · [Author code](https://github.com/pygod-team/pygod).

## Null-Model Significance Testing via Degree-Preserving Graph Randomization {#null_model_significance_testing}

Given an observed graph and a declared structural statistic, determine how unusual the statistic's observed value is by comparing it against its distribution over an ensemble of randomized graphs sampled from a declared null model, typically one preserving the degree sequence.

$$
\hat p=\frac{1+\sum_{i=1}^{m}\mathbf1[T(G_i)\ge T(G)]}{m+1}
$$

This illustrates an upper-tail empirical test; the declared null model, tail, and correction define the reported statistic.

**Example question:** “Is this graph statistic unusual under a degree-preserving null model?”

**Input assumptions.** direction: directed or undirected; weights: ignored unless null model preserves them; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Every randomized sample must exactly satisfy null_model's invariant; the null_distribution_summary, z_score, and empirical_p_value are statistical estimates whose precision improves with sample_count, not exact quantities.

**Required outputs:** `observed_value`, `null_distribution_summary`, `z_score`, `empirical_p_value`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`null-model-significance`](../explorer.md#problem/null_model_significance_testing) | `cpp` | — | Statistical estimate |

**`null-model-significance`** — Uniform G(n,m), or uniform stub pairing conditioned on simplicity and exact degree invariants. Dense fixed-degree graphs use complement sampling. Preserve direction, discard loops and collapse duplicates. Statistics: triangles, directed triangles, k-cliques, density or a supplied-partition modularity. Report every sample, population standard deviation and declared empirical tail; no hidden pseudocount.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run null-model-significance INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/null_model_significance_testing) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/37_null_model_significance_testing/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

This utility group has no separate research-paper entry in the catalog.
