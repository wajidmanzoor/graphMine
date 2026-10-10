# GraphMine Python analytics

The public library separates graph input, mathematical algorithm families,
backend selection, and result provenance. It uses NetworkX/SciPy on CPU and
cuGraph on GPU. Native GraphMine and agent integration are tracked in
[`docs/VERIFIED_ANALYTICS_IMPLEMENTATION.md`](../../docs/VERIFIED_ANALYTICS_IMPLEMENTATION.md).

```sh
python -m pip install -e 'python/graphmine[test]'
# Optional NVIDIA CUDA 12 backend:
python -m pip install -e 'python/graphmine[gpu]' --extra-index-url https://pypi.nvidia.com
```

```python
from graphmine import Graph, list_algorithms, run

graph = Graph.from_edges(
    [("Alice", "Bob"), ("Bob", "Carol"), ("Carol", "Alice")],
    vertices=["Alice", "Bob", "Carol", "Isolated"],
)
result = run("k-cliques", graph, parameters={"k": 3}, device="cpu")
assert result["result"]["count"] == 1
print(result["backend"])
print(list_algorithms())  # Includes accepted parameters and result quality.
```

`device="cpu"` forces CPU computation, including when NetworkX's environment
configuration normally selects a GPU. `device="gpu"` rejects unsupported GPU
profiles. `device="auto"` selects a compatible available GPU profile or reports
why it selected CPU. Numerical or correctness failures are not hidden by
silently returning a different algorithm's answer.

Original string and integer IDs are preserved. The distinct IDs `0` and `"0"`
remain distinct, as do integers beyond JavaScript's exact numeric range. The
browser must use typed keys rather than coercing these IDs to numbers.

Every result includes its input hash, implementation hash, library version,
device, parameters, numerical diagnostics where applicable, and typed output
ports. A complete count does not imply that a materialized instance list is
complete. A budget failure does not return an apparently exhaustive answer.

The runtime currently invokes algorithms synchronously; the agent integration
must use cancellable subprocesses for hard time and memory limits. Cooperative
enumeration counters do not interrupt a running native library call.

## Verification

```sh
CUDA_VISIBLE_DEVICES='' python -m pytest python/graphmine/tests -q
CUDA_VISIBLE_DEVICES=0 GRAPHMINE_TEST_DEVICE=gpu GRAPHMINE_CASE_SHARD=0/2 \
  python -m pytest python/graphmine/tests/test_small_graph_oracles.py \
  python/graphmine/tests/test_weighted_directed.py -q
CUDA_VISIBLE_DEVICES=1 GRAPHMINE_TEST_DEVICE=gpu GRAPHMINE_CASE_SHARD=1/2 \
  python -m pytest python/graphmine/tests/test_small_graph_oracles.py \
  python/graphmine/tests/test_weighted_directed.py -q
```

The atlas suite uses all 208 nonempty unlabeled undirected graphs through six
vertices. Independent subset enumeration, Floyd–Warshall, cut enumeration,
path enumeration, and linear systems supply expected results. Additional tests
cover weighted/directed graphs, large and mixed IDs, empty outputs, exactness
limits, and forbidden device dispatch. These are correctness fixtures, not
performance benchmarks or a proof that every problem/parameter is covered.
