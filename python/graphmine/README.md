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
Graph-valued ports carry the derived graph's content hash and the source graph's
hash separately; vertex selections retain the source graph's ID namespace.

CPU provenance identifies the primary library (`networkx` or `scipy`) and
records the installed NetworkX, NumPy and SciPy versions. Some operations use
both libraries; per-result solver diagnostics identify the method actually used.

## Additional CPU profiles

The density, bipartite, pattern and partitioning modules provide quasi-cliques,
clique-density maximization, fixed-cardinality densest subgraphs, maximal
bicliques, butterfly participation and cores, bipartite matching, subgraph
isomorphism, motif and graphlet counting, communities, balanced partitions and
signed-network balance. See
[`CPU_REFERENCE_PROFILES.md`](../../docs/CPU_REFERENCE_PROFILES.md) for objectives,
limits, numerical guarantees and input conventions.

In particular, `densest-subgraph.clique_order` changes the density numerator;
`densest-k-subgraph.k` fixes the size of the selected vertex set. These are
different problems. Graphlet classification uses the complete NetworkX atlas
through seven vertices. Larger clique orders remain available to density and
clique enumeration, subject to work and output budgets.

HiGHS optimization results use `quality="numerical_optimum"`, record the solver's
bound and gap, and check feasibility and objective values after solving. They
are numerical optimality certificates, not exact-arithmetic proofs. Timed-out
incumbents are never labeled optimal. Unconstrained clique-density uses exact
integer-capacity min cuts and records the resulting rational density.

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
The expanded suite also enumerates all 512 bipartite 3-by-3 graphs and all 729
four-vertex signed graphs, and checks pattern embeddings against permutations
and optimization objectives against subsets and set partitions. Reports record
the collected test selection, package versions, implementation/test sources,
formal contracts and package definition. The audit marks evidence stale when
any of those source, contract or dependency snapshots changes.
