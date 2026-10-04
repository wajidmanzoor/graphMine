# GraphMine benchmarks

Benchmark manifests are executable correctness contracts. Every case names an
operation, canonical graph, compiled backends, exact CLI arguments, and result
paths that must equal trusted values. A timing sample is retained for policy
training only when the native result is successful and every expected value
matches.

The committed `v1-smoke.json` suite is intentionally tiny. It validates the
pipeline and provides a conservative initial policy; it is not evidence that a
backend is fastest on large or structurally different graphs.

The V1 release run exercised all 23 backends compiled by the default build,
with one warmup and three measured repetitions per backend. All 69 measured
records passed their exact-result gates. A compact, hash-linked hardware report
is checked in at
[`reports/v1-smoke-rtx6000-ada.json`](reports/v1-smoke-rtx6000-ada.json); the
full raw report remains an ignored local artifact because it contains
machine-specific absolute paths and verbose process output.

```bash
GRAPHMINE_GRAPH_GPU_UUID=GPU-... \
  .venv/bin/graphmine-agent benchmark benchmarks/v1-smoke.json \
  --output benchmark-results/v1-smoke.json

.venv/bin/graphmine-agent train-selector benchmark-results/v1-smoke.json \
  --output agent/backend_policy.json

.venv/bin/graphmine-agent evaluate-selector benchmark-results/v1-smoke.json \
  --policy agent/backend_policy.json \
  --output benchmark-results/v1-smoke-policy-evaluation.json
```

For research-quality selection, add manifests spanning graph sizes, density,
degree distributions, domains, parameters, and optional-output modes. Split
policy training and evaluation by graph family so near-duplicate graphs never
appear on both sides.
