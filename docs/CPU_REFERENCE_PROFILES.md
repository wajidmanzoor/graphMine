# CPU reference profiles

These executable profiles are part of `python/graphmine`. They are not yet
connected to the browser agent. Device selection and capabilities in the
existing native application remain separate until the integration step in
`VERIFIED_ANALYTICS_IMPLEMENTATION.md` is complete.

## Objectives and implementations

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `densest-subgraph` | Maximize induced k-clique count divided by selected vertex count. Weighted k=2 uses induced weight instead. Maximum-weight closure reduces the unconstrained problem to NetworkX minimum cut with exact integer capacities. | No fixed maximum clique order. Higher-order weighted density is undefined and rejected. `minimum_vertices > 1` uses separate HiGHS models by result cardinality and returns a numerical optimality certificate. |
| `densest-k-subgraph` | Select exactly k vertices maximizing induced edge count or nonnegative edge weight using binary vertex/edge variables in SciPy/HiGHS. | k must be between 1 and the vertex count. This is an NP-hard optimization, so the work/time budget can prevent completion. |
| `quasi-cliques` | Enumerate all vertex sets meeting `ceil(gamma * (size-1))` internal degree. HiGHS enumerates fixed-size feasible sets with exclusion constraints. | The threshold uses the decimal representation of gamma, avoiding binary multiplication/ceiling artifacts. Maximality is within the declared size bounds and tests all larger qualifying sets, not only one-vertex extensions. |
| `maximal-bicliques` | Complete each declared bipartition internally, enumerate NetworkX maximal cliques, then retain the pairs with both sides nonempty. | Partitions must be disjoint and cover all vertices, including isolates. A result limit caps listing and changes the membership port's completeness. |
| `butterfly-counting` | Exact common-neighbor enumeration of 2-by-2 bicliques; global, per-vertex and per-edge participation; threshold peeling for the explicitly selected core measure. | `core_measure=degree` is conventional (alpha,beta)-core peeling. `butterfly_participation` is the collection's original variant. They are different objectives. |
| `bipartite-matching` | NetworkX maximum-weight matching, with negated scores for minimum cost and an explicit cardinality requirement when full smaller-side coverage is requested. | Without required coverage, minimum cost is permitted to select the empty matching. An infeasible coverage request returns `feasible=false` and an infeasibility certificate, not a partial matching presented as a solution. |
| `subgraph-isomorphism` | NetworkX VF2 induced isomorphisms or non-induced monomorphisms. Attribute-constrained parallel edges use an injective bipartite matching inside the VF2 predicate. | Preserves loops, direction and parallel-edge identity. Distinct query-to-data mappings remain distinct. Result limits mark incomplete enumeration. |
| `motif-counting` | VF2 embeddings, optionally divided into automorphism classes using the mapped vertices and mapped motif edges. | A three-vertex path has three non-induced occurrence classes in a triangle, or six embeddings. A vertex-set-only deduplication would be wrong. Counts remain exhaustive when instance lists are capped. |
| `graphlet-counting` | Classify connected induced vertex subsets against the NetworkX atlas. Compute exact vertex orbits from pattern automorphisms. | Supports sizes 2 through 7 because that is the atlas's complete range. Larger sizes require another class dictionary/generator. Orbit identifiers include their structural definitions. |
| `community-detection` | NetworkX Louvain for heuristic modularity; binary same-community variables with transitivity constraints for globally optimized modularity or CPM. | CPM here is the sum of internal edge weights minus resolution times the number of internal unordered vertex pairs. A heuristic request may receive a stronger, completed exact-method result. Louvain does not claim global optimality. Edgeless modularity is defined as zero. |
| `balanced-partitioning` | HiGHS assignment model for edge cut; set-partitioning model for size-normalized cut. Enforces nonempty parts plus both lower and upper balance limits. | Normalized cut means the sum of each part's boundary cost divided by its declared balance size. It does not silently switch to degree-volume normalization. Zero-sized weighted parts are inadmissible for that objective. Infeasible balance is reported explicitly. |
| `signed-balance` | Exact parity propagation decides structural balance. Binary XOR constraints minimize weighted frustration when requested. | Structural balance depends on signs even when costs are zero. `optimal=true` for `balance_check` certifies the decision; `frustration_optimal` separately indicates whether the returned assignment minimizes frustration. |

All profiles reject unknown parameters. Directed projections are explicit where
an undirected objective is required. For ordinary unweighted structure, parallel
edges collapse; weighted density and partitioning sum parallel weights. Matching
retains the original ID of the edge with the best applicable objective value.

## Numerical and resource limits

The mathematical models implement the stated objectives. SciPy's `milp` wraps
HiGHS and converts coefficients to double precision. The wrapper requests zero
relative MIP gap, requires an optimal solver status, validates rounded binary
variables and constraints, and compares the recomputed objective with the dual
bound. It rejects unrepresentable integer coefficients and total objective
magnitude beyond the supported float64 integer range. A numerical certificate
is labeled `numerical_optimum`; it is not a formal rational proof.

For unconstrained clique density, floating edge values are converted to their
exact rational representation, integer capacity units preserve ordering, and
the final density fraction is retained. The displayed numeric density is the
rounded JSON number; the fraction and original induced edge value retain the
exact result.

Candidate, output and elapsed-time budgets bound work. HiGHS also receives the
remaining solver time. General synchronous library calls still require the
planned subprocess worker for hard cancellation and memory limits. There is
no claim that NP-hard or enumerative operations will finish on arbitrary large
graphs. Budget exhaustion raises a resource error and never produces a result
marked exhaustive or optimal.

## Data and predicate conventions

JSON map keys cannot distinguish the original vertex IDs `0` and `"0"`.
Per-vertex inputs and outputs therefore use arrays of records. For example:

```json
{
  "vertex_weights": [
    {"vertex": 0, "value": 2},
    {"vertex": "0", "value": 3}
  ]
}
```

Mappings contain `{query_vertex, data_vertex}` rows. Bipartite algorithms that
do not take explicit partition parameters read each vertex's
`attributes.side`, whose value must be `left` or `right`.

Pattern predicates are data objects, not executable expressions. Every
predicate names a `field` and an `operator`. Supported operators are `eq`,
`ne`, `lt`, `le`, `gt`, `ge`, `in`, `exists`, and `eq_query`.

```json
{
  "vertex_predicates": [
    {"field": "type", "operator": "eq_query"},
    {"query_vertex": "person", "field": "attributes.age", "operator": "ge", "value": 18}
  ],
  "edge_predicates": [
    {"field": "type", "operator": "eq_query"}
  ]
}
```

Vertex fields are `label`, `type`, or an `attributes` path. Edge fields are
`type`, `weight`, `timestamp`, or an `attributes` path. `eq_query` compares
the corresponding query field, optionally named by `query_field`. A
`query_vertex` or `query_edge` restricts the predicate to that query record.
Missing fields fail comparison predicates; `exists` checks presence explicitly.
Equality uses typed JSON values. Ordering applies to numbers or strings;
timestamp strings are compared lexically and must already use a comparable
canonical representation if temporal ordering is intended.

## Independent evidence

The new oracle suite uses subsets, permutations and set partitions to check
the production flow, VF2, matching and HiGHS implementations. It includes all
208 nonempty unlabeled undirected graphs through six vertices, all 512 simple
3-by-3 bipartite graphs, all 729 signed four-vertex graphs, all 64 loop-free
three-vertex digraphs, weighted fixtures, mixed IDs, large integers, loops,
parallel edges, infeasible constraints, truncated listings and resource failure.

This is evidence for the tested profiles. It does not establish full parameter
coverage, scale suitability or completion of the entire 70-problem collection.
The authoritative inventory is generated by
`tools/audit_python_analytics.py --write` in the analytics environment.

## Primary references

- [SciPy MILP and HiGHS interface](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html): solver statuses, floating-point conversion and gap controls.
- [NetworkX VF2](https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html): induced matching, monomorphisms and attribute semantics.
- [NetworkX graph atlas](https://networkx.org/documentation/stable/reference/generated/networkx.generators.atlas.graph_atlas_g.html): complete unlabeled graph dictionary through seven vertices.
- [NetworkX Louvain](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html): modularity optimization and resolution.
- [VLDB 2025 bipartite community paper, Definition 2.1](https://www.vldb.org/2025/Workshops/VLDB-Workshops-2025/LSGDA/LSGDA25_02.pdf): degree-based (alpha,beta)-core definition.
