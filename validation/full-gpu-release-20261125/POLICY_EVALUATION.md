# Shared backend policy: full GPU release

The parameter-free shared NN was fitted for 2,000 epochs on 348 paired comparisons from 34 graphs. The test split holds out all settings and load regimes for 8 entire graph fingerprints (102 comparisons). Only the NN is published; the shared linear encoder is an offline ablation.

Model `20261125t091238.591482z-db0bc337c9a7` uses 49 varying columns from the 112-column schema, followed by Dense(64, ReLU), Dense(32, ReLU) and one 38-backend preference layer. Parameters do not enter the encoder. [Training normalization](feature-normalization.json) and all dropped feature names are retained alongside [the model metadata](shared-policy-evaluation.json).

The ratio is selected runtime divided by the fastest measured eligible runtime. Metrics integrate the exact masked choice probabilities within the measured size ranges and use greedy selection outside them. A daily exploration ledger is not simulated. Timings include execution overhead, and tail times are observed wall times.

| Policy | Mean ratio | Median | p90 | p99 | Native–oracle gap closed | Tail seconds p90 / p99 | Failure / timeout |
|---|---:|---:|---:|---:|---:|---:|---:|
| Shared NN + bandit | 1.0107 | 1.0000 | 1.0000 | 1.0000 | 99.44% | 0.1783 / 0.2102 | 0.00% / 0.00% |
| Shared linear + bandit | 1.0107 | 1.0000 | 1.0000 | 1.0000 | 99.44% | 0.1783 / 0.2102 | 0.00% / 0.00% |
| Native ordering | 2.9084 | 2.7782 | 4.2705 | 4.9017 | 0.00% | 0.5678 / 0.7378 | 0.00% / 0.00% |
| Measured oracle | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 100.00% | 0.1760 / 0.2041 | 0.00% / 0.00% |
| Removed per-problem regressions | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

The NN and shared linear baseline have practically identical held-out results on this small-graph dataset. This does not establish an advantage from the nonlinear encoder.

## By runnable problem

The following columns are mean selected/oracle runtime ratios; full quantiles, failures and timeouts are in the linked metadata.

| Runnable problem | NN | Shared linear | Native | Oracle |
|---|---:|---:|---:|---:|
| betweenness-centrality | 1.0000 | 1.0000 | 3.0735 | 1.0000 |
| breadth-first-search | 1.0206 | 1.0207 | 3.0558 | 1.0000 |
| butterfly-counting | 1.0000 | 1.0000 | 2.4442 | 1.0000 |
| community-detection | 1.0252 | 1.0252 | 2.5668 | 1.0000 |
| connected-components | 1.0390 | 1.0393 | 3.5209 | 1.0000 |
| densest-subgraph | 1.0000 | 1.0000 | 4.5182 | 1.0000 |
| dynamic-triangle-counting | 1.0000 | 1.0000 | 2.2479 | 1.0000 |
| group-steiner-tree | 1.0355 | 1.0355 | 4.5507 | 1.0000 |
| induced-subgraph | 1.0140 | 1.0141 | 2.4019 | 1.0000 |
| k-cliques | 1.0356 | 1.0356 | 2.4960 | 1.0000 |
| k-core | 1.0156 | 1.0158 | 2.5579 | 1.0000 |
| k-truss | 1.0347 | 1.0348 | 3.0564 | 1.0000 |
| link-prediction | 1.0206 | 1.0208 | 3.0629 | 1.0000 |
| many-source-shortest-paths | 1.0206 | 1.0209 | 3.0582 | 1.0000 |
| max-flow-min-cut | 1.0288 | 1.0289 | 3.8825 | 1.0000 |
| maximal-biclique-counting | 1.0000 | 1.0000 | 4.6111 | 1.0000 |
| maximal-bicliques | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| maximal-cliques | 1.0000 | 1.0000 | 2.3338 | 1.0000 |
| maximal-independent-set | 1.0188 | 1.0189 | 2.8779 | 1.0000 |
| maximum-clique | 1.0000 | 1.0000 | 2.3559 | 1.0000 |
| maximum-independent-set | 1.0000 | 1.0000 | 2.3836 | 1.0000 |
| minimum-vertex-cover | 1.0000 | 1.0000 | 2.6833 | 1.0000 |
| motif-counting | 1.0000 | 1.0000 | 3.1898 | 1.0000 |
| pagerank | 1.0158 | 1.0160 | 2.5816 | 1.0000 |
| personalized-pagerank | 1.0153 | 1.0153 | 2.6006 | 1.0000 |
| quasi-cliques | 1.0000 | 1.0000 | 2.1446 | 1.0000 |
| random-walks | 1.0226 | 1.0227 | 3.2567 | 1.0000 |
| single-source-shortest-paths | 1.0171 | 1.0172 | 2.7099 | 1.0000 |
| spanning-tree-forest | 1.0192 | 1.0195 | 2.9205 | 1.0000 |
| subgraph-isomorphism | 1.0000 | 1.0000 | 2.3338 | 1.0000 |
| transitive-closure | 1.0145 | 1.0145 | 3.7154 | 1.0000 |
| triangle-counting | 1.0190 | 1.0191 | 2.4473 | 1.0000 |
| vertex-coloring | 1.0273 | 1.0275 | 3.7320 | 1.0000 |

No graph for `bipartite-matching`, `influence-maximization`, `temporal-motifs` landed in the held-out split, so their held-out metrics are unavailable. Their measured timings and integration checks are retained.

## By number of eligible backends

| K | NN | Shared linear | Native | Oracle |
|---|---:|---:|---:|---:|
| 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 2 | 1.0112 | 1.0112 | 3.2596 | 1.0000 |
| 3 | 1.0122 | 1.0122 | 2.7315 | 1.0000 |
| 4 | 1.0071 | 1.0071 | 2.4505 | 1.0000 |
| 5 | 1.0252 | 1.0252 | 2.5668 | 1.0000 |

## Measurement scope and rollout

The retained dataset has 1237 unique attempts spanning 36 problems and 52 graph fingerprints. [All timing rows](paired-timings.csv), including failures and the operator-cancelled attempt, remain available. Reused rows retain their original run IDs. [The data summary](paired-data-summary.json) records the split, load measurements and dropped features.

| Added load | Attempts | Mean free-core fraction | Mean GPU 1 utilization |
|---|---:|---:|---:|
| idle | 625 | 0.2380 | 51.14% |
| busy_cpu | 612 | 0.4542 | 86.29% |

Fitted empirical controls cover 35 problems. `influence-maximization` has no accepted paired comparison in this model, so measured-size exploration is unavailable for that problem; its raw timings and verified executable backends remain available.

Pair exclusions were `{"incomplete_pairs": 7, "inconsistent_pair": 15}`; 6 rows failed current admission checks. The accepted split contains 42 graph fingerprints; the raw archive also retains incomplete and superseded-workload measurements.

These are small generated graphs (up to 512 vertices), with one timing per backend/settings/load combination. The host also ran other workloads. This establishes functional coverage and an initial policy dataset; it does not establish large-graph performance or reliable production tail estimates. CPU exact algorithms use deliberately small cases. cuMBE observations are excluded from fitting after its correctness failure; its original measurements remain in the data.

The evidence-based recommendation remains to collect paired production shadow measurements before claiming the original statistical switch criteria are met. No old-policy or shadow-runtime comparison is fabricated. The operator subsequently requested live NN selection and promotion, so the release uses `GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false` explicitly. Existing production code, runtime, model/log stores and a deployment backup remain available for rollback.

Execution keeps six-hour attempt/job allowances, no fixed input-byte caps, native feasibility and memory admission, explicit backend/device overrides, and one fallback attempt when enough time remains. The shared model is retrained offline from saved eligible benchmark rows and propensity-logged application feedback. Evaluation-only checks never train it.
