#!/usr/bin/env python3
"""Reviewed contracts for additional research problems; no runtime registration."""
from acquire import ROOT, write_json

_MISSING = object()


def param(name, type_, description, default=_MISSING, values=None):
    result = dict(name=name, type=type_, required=default is _MISSING, description=description)
    if default is not _MISSING:
        result['default'] = default
    if values:
        result['allowed_values'] = values
    return result


def output(name, type_, description):
    return dict(name=name, type=type_, description=description)


def define(number, id_, name, statement, inputs, outputs, rules, cases, *,
           category='community_and_structural_analysis', direction='undirected',
           weights='ignored', attributes='ignored', schema='graph_input',
           normalization=None, exactness='Exact mathematical objective; implementations must declare approximation and termination status.',
           semantics=None, intents=None):
    folder = ROOT / f'{number:02d}_{id_}'
    spec = dict(schema_version='1.0.0', problem_id=id_, name=name, category=category,
                problem_statement=statement,
                graph_input=dict(format={'graph_input': 'canonical_graph_v1',
                                         'hypergraph_input': 'canonical_hypergraph_v1',
                                         'feature_vectors_input': 'feature_vectors_v1'}[schema],
                                 schema_ref=f'../{schema}.schema.json', cardinality='single_graph',
                                 requirements=dict(direction=direction, weights=weights, timestamps='ignored',
                                                   vertex_attributes=attributes, edge_attributes='ignored'),
                                 normalization=normalization or ['Preserve external vertex identities and isolated vertices.',
                                                                 'Reject self-loops and collapse parallel edges only under the declared aggregation rule.']),
                problem_inputs=inputs, required_outputs=outputs, optional_outputs=[],
                solution_semantics=dict(objective=statement, exactness=exactness,
                                        duplicate_policy='Each external vertex ID occurs once; output multiplicities follow the declared task.',
                                        ordering='No ordering among equally valid solutions is required.', **(semantics or {})),
                validation_rules=rules, edge_cases=cases,
                evaluation_metrics=dict(correctness=rules, performance=['end-to-end time', 'compute time',
                                                                        'peak host memory', 'peak device memory']),
                intent_signals=intents or [name.lower(), id_.replace('_', ' ')],
                research_only=True)
    write_json(folder / 'problem.json', spec)
    (folder / 'papers').mkdir(exist_ok=True)


def main():
    write_json(ROOT / 'feature_vectors_input.schema.json', {
        '$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'feature_vectors_input.schema.json',
        'title': 'Feature Vectors for Graph Construction v1', 'type': 'object', 'additionalProperties': False,
        'required': ['dataset_id', 'dimension', 'vectors'],
        'properties': {'dataset_id': {'type': 'string', 'minLength': 1},
                       'dimension': {'type': 'integer', 'minimum': 1},
                       'vectors': {'type': 'array', 'items': {
                           'type': 'object', 'additionalProperties': False, 'required': ['id', 'values'],
                           'properties': {'id': {'oneOf': [{'type': 'string', 'minLength': 1}, {'type': 'integer'}]},
                                          'values': {'type': 'array', 'minItems': 1, 'items': {'type': 'number'}}}}}},
        'semantic_constraints': ['IDs are unique, preserving type (integer 1 differs from string "1").',
                                 'Every values array has exactly dimension finite entries.']})

    define(61, 'widest_paths', 'Single-Source Widest Paths',
           'For each vertex v, maximize the minimum edge capacity along a directed path from a designated source to v.',
           [param('source_vertex', 'vertex_id', 'Source vertex, which must exist.')],
           [output('bottleneck_capacity', 'map<vertex_id,number|null>', 'Best capacity, null for unreachable vertices; the source uses null with reachable=true and is_source=true to represent +infinity.'),
            output('reachable', 'map<vertex_id,boolean>', 'Reachability, distinguishing source infinity from unreachable null.'),
            output('is_source', 'map<vertex_id,boolean>', 'Exactly the designated source is true.'),
            output('predecessor', 'map<vertex_id,vertex_id|null>', 'A witness path tree; null at the source and unreachable vertices.')],
           ['For reachable non-source vertices, a predecessor path realizes the reported bottleneck.',
            'Compare bottleneck values with a max-min semiring reference, not sum-of-weights shortest paths.',
            'Unreachable vertices remain unreachable even when all reachable capacities are zero.'],
           ['The source has an empty path with infinite bottleneck.', 'Zero capacities are legal.', 'Disconnected graphs and isolated sources are legal.'],
           direction='directed_or_undirected', weights='required_finite_nonnegative_capacities',
           normalization=['Retain directed arcs; undirected edges become symmetric arcs.',
                          'Parallel arcs can be collapsed using maximum capacity.', 'Self-loops do not improve widest paths.'],
           intents=['widest path', 'maximum bottleneck path', 'maximum capacity path'])

    define(62, 'graph_coarsening', 'Graph Coarsening and Quotient Construction',
           'Map every vertex to a nonempty coarse cluster and construct the weighted quotient graph with declared edge and feature aggregation.',
           [param('cluster_assignment', 'map<vertex_id,integer>|null', 'Optional fixed assignment; null requests a declared clustering method.', None),
            param('method', 'string', 'Clustering method when an assignment is not supplied.', 'greedy_matching'),
            param('self_loop_policy', 'enum', 'Whether intra-cluster edges survive as quotient self-loops.', 'keep', ['keep', 'drop']),
            param('feature_reduction', 'enum', 'Reduction for numeric vertex features.', 'sum', ['sum', 'mean']),
            param('seed', 'integer', 'Random seed for a randomized clustering method.', 0)],
           [output('fine_to_coarse', 'map<vertex_id,integer>', 'Total surjective mapping to the coarse vertex IDs.'),
            output('coarse_graph', 'canonical_graph_v1', 'Quotient graph; parallel fine edges aggregate by sum.'),
            output('cluster_sizes', 'map<integer,integer>', 'Number of original vertices in each cluster.')],
           ['Every fine vertex occurs in exactly one nonempty cluster, including isolated vertices.',
            'For each coarse edge, recompute the sum of corresponding original edge weights.',
            'Undirected input edges are counted once, even if a GPU adapter stores symmetric arcs.',
            'Recompute cluster sizes and requested feature reductions from the assignment.'],
           ['Identity coarsening is valid.', 'A one-cluster quotient can contain a self-loop.', 'Greedy matching may leave singleton clusters.'],
           weights='optional_finite_nonnegative_weights_default_one', attributes='optional_numeric_feature_vectors',
           exactness='Clustering may be heuristic; quotient aggregation must be exact within numeric tolerance.',
           intents=['coarsen graph', 'quotient graph', 'contract vertices', 'graph contraction'])

    define(63, 'graph_laplacian_eigenpairs', 'Graph Laplacian Eigenpairs',
           'Compute selected eigenpairs of the combinatorial or symmetric normalized Laplacian of a nonnegative undirected graph.',
           [param('num_eigenpairs', 'integer', 'k with 1 <= k <= |V|; sparse implementations may require k < |V|.'),
            param('laplacian', 'enum', 'L = D-A, or L = I_active-D^(-1/2) A D^(-1/2); isolated rows and columns are zero.', 'combinatorial', ['combinatorial', 'symmetric_normalized']),
            param('selection', 'enum', 'Select the k smallest or largest algebraic eigenvalues, including multiplicities.', 'smallest', ['smallest', 'largest']),
            param('tolerance', 'number', 'Positive residual and orthogonality tolerance.', 1e-6),
            param('max_iterations', 'integer', 'Positive iteration limit for iterative solvers.', 1000)],
           [output('eigenvalues', 'array<number>', 'Selected real eigenvalues in ascending order.'),
            output('eigenvectors', 'matrix<number>', 'Columns correspond to eigenvalues; rows follow a reported vertex order.'),
            output('vertex_order', 'array<vertex_id>', 'Row-to-external-ID mapping.'),
            output('residual_norms', 'array<number>', 'Euclidean norms of Lq-lambda*q.'),
            output('converged', 'boolean', 'Whether residual and orthogonality requirements were met.')],
           ['Rebuild the requested Laplacian and check residuals and Q^T Q against the declared tolerance.',
            'Compare subspaces, allowing sign flips and rotations within repeated eigenspaces.',
            'Verify selected eigenvalue order and multiplicity with an independent small dense reference.',
            'Do not treat a partially converged iterative result as converged.'],
           ['Each connected component contributes a zero eigenvalue.', 'Isolated vertices contribute zero rows.', 'Reject negative weights and directed inputs.'],
           weights='optional_finite_nonnegative_weights_default_one',
           normalization=['Reject self-loops to avoid ambiguous Laplacian conventions.', 'Sum parallel edge weights; preserve isolates.'],
           exactness='Floating-point eigenpairs with explicit residual and orthogonality tolerances.',
           intents=['laplacian eigenvectors', 'laplacian eigenvalues', 'fiedler vector', 'spectral graph embedding'])

    define(64, 'knn_graph_construction', 'k-Nearest-Neighbor Graph Construction',
           'Construct a graph connecting each feature vector to its k nearest distinct input vectors under a declared distance metric.',
           [param('k', 'integer', '0 <= k < number of vectors.'),
            param('distance', 'enum', 'Metric used for search and returned edge weights.', 'squared_euclidean', ['squared_euclidean', 'euclidean', 'cosine']),
            param('search_mode', 'enum', 'Exact or approximate neighbor selection.', 'exact', ['exact', 'approximate']),
            param('symmetrization', 'enum', 'Directed k-out graph, undirected union, or mutual-neighbor graph.', 'directed', ['directed', 'union', 'mutual']),
            param('seed', 'integer', 'Seed for approximate index construction.', 0)],
           [output('neighbor_lists', 'map<vertex_id,array<vertex_id>>', 'Exactly k unique non-self neighbors before symmetrization.'),
            output('graph', 'canonical_graph_v1', 'Edges weighted by the declared distances.'),
            output('search_metadata', 'object', 'Algorithm, exact/approximate mode, metric, seed and relevant index parameters.')],
           ['Each vector has exactly dimension finite values and a unique ID.',
            'No self-neighbors or duplicate neighbors; recompute distances independently.',
            'Exact search must select k nearest neighbors; ties at the boundary can select any tied subset.',
            'Approximate search reports recall@k against exact neighbors on a declared evaluation subset.',
            'Symmetrization is applied after checking the directed neighbor lists.'],
           ['Duplicate vectors with distinct IDs are valid zero-distance neighbors.', 'Reject zero-norm vectors for cosine distance.', 'k=0 produces an edgeless graph.', 'An ANN navigation graph is not automatically a kNN result graph.'],
           schema='feature_vectors_input', direction='not_applicable_feature_vectors', attributes='required_finite_equal_length_vectors',
           normalization=['Preserve IDs and vector order.', 'Do not silently normalize vectors or change the requested distance.'],
           exactness='Exact and approximate modes are separate and must be reported.',
           intents=['knn graph', 'nearest neighbor graph', 'build graph from vectors'])

    define(65, 'hypergraph_node_learning', 'Hypergraph Node Classification and Regression',
           'Train or evaluate a declared hypergraph neural model to predict vertex labels or targets while preserving hyperedge incidence.',
           [param('task', 'enum', 'Prediction objective.', 'classification', ['classification', 'regression']),
            param('feature_key', 'string', 'Numeric feature-vector vertex attribute.', 'features'),
            param('target_key', 'string', 'Ground-truth vertex attribute available only in permitted splits.', 'target'),
            param('split_key', 'string', 'Attribute assigning train, validation, test, or inference vertices.', 'split'),
            param('model', 'string', 'Declared architecture, hyperparameters, preprocessing and checkpoint.'),
            param('seed', 'integer', 'Training and inference seed.', 0)],
           [output('predictions', 'map<vertex_id,number|array<number>>', 'Targets or class probabilities for requested vertices.'),
            output('model_artifact', 'object', 'Model parameters/checkpoint reference and reproducible hyperparameters.'),
            output('split_metrics', 'object', 'Metrics with denominators and explicit split membership.')],
           ['Retain hyperedges and incidence IDs; any clique or mediator expansion must be declared as a model transformation.',
            'Only training labels influence fitting; validation selects hyperparameters and test labels are held out.',
            'Verify prediction dimensions, finite outputs and classification probability normalization.',
            'Reproduce inference on a small hypergraph using the same parameters; do not require trained models to have identical accuracy.'],
           ['Singleton hyperedges and isolated vertices are legal with a declared model convention.', 'Variable-size hyperedges cannot be silently replaced by ordinary pairwise edges.'],
           schema='hypergraph_input', direction='undirected_hypergraph', weights='optional_nonnegative_hyperedge_weights',
           attributes='required_features_and_split_specific_targets', category='graph_machine_learning',
           normalization=['Preserve every hyperedge incidence set and vertex ID.', 'Reject repeated vertices inside one hyperedge.'],
           exactness='Statistical learning with declared split, seed and tolerance; no deterministic optimum claim.',
           intents=['hypergraph node classification', 'hypergraph neural network', 'learn hypergraph labels'])

    define(66, 'maximum_independent_set', 'Maximum Independent Set',
           'Find an independent vertex set of maximum cardinality in a simple undirected graph.',
           [param('mode', 'enum', 'Exact optimization or an explicitly heuristic feasible solution.', 'heuristic', ['exact', 'heuristic']),
            param('time_limit_seconds', 'number', 'Positive runtime budget; expiry must report incomplete optimization.', 60),
            param('seed', 'integer', 'Random seed for heuristic methods.', 0)],
           [output('independent_set', 'array<vertex_id>', 'Distinct pairwise nonadjacent vertices.'),
            output('cardinality', 'integer', 'Size of the returned set.'),
            output('optimality_proven', 'boolean', 'True only if a valid exact proof or exhausted search establishes optimality.'),
            output('termination_reason', 'string', 'Convergence, exhausted search, timeout, or other explicit reason.')],
           ['Check every returned ID and every edge for independent-set feasibility.',
            'On small graphs compare cardinality with exhaustive search.',
            'A maximal independent set is not necessarily maximum; local maximality does not prove optimality.',
            'Heuristic and learned methods must set optimality_proven=false absent a separate proof.'],
           ['The empty graph has the empty optimum.', 'All isolated vertices belong to every maximum-cardinality solution.', 'Disconnected components can be solved independently.'],
           intents=['maximum independent set', 'largest independent set', 'optimize independent set'])

    define(67, 'persistent_homology', 'Flag-Complex Persistent Homology',
           'Compute persistence intervals over a declared prime field for the flag-complex filtration induced by nonnegative undirected edge filtration values.',
           [param('max_homology_dimension', 'integer', 'Nonnegative largest homology dimension to report.', 1),
            param('max_filtration', 'number|null', 'Nonnegative finite cutoff; null means no cutoff.', None),
            param('field_prime', 'integer', 'Prime coefficient modulus supported by the selected implementation.', 2)],
           [output('intervals', 'array<object>', 'Each interval specifies dimension, birth, and death; null death denotes survival beyond the cutoff.'),
            output('essential_interval_convention', 'string', 'Explain whether null means essential in the complete filtration or right-censored at the cutoff.'),
            output('coefficient_field', 'integer', 'Actual prime modulus used.')],
           ['Vertices enter at zero; a clique simplex enters at the maximum filtration value of its edges.',
            'Missing graph edges never enter; do not silently complete a sparse graph or reinterpret weights as similarities.',
            'Compare barcode multisets against an independent small boundary-matrix reduction.',
            'Intervals have birth <= death; specify whether zero-length intervals are omitted.',
            'To compute dimension d, include simplices up to dimension d+1.'],
           ['Disconnected components produce multiple surviving H0 intervals.', 'A 4-cycle has an H1 class until filling diagonals appear.', 'Equal filtration values require a face-compatible ordering.'],
           weights='required_finite_nonnegative_filtration_values',
           normalization=['Reject self-loops; duplicate edges collapse to their minimum filtration value.', 'Preserve isolated vertices.'],
           intents=['persistent homology', 'persistence barcode', 'vietoris rips complex', 'flag complex'])

    define(68, 'single_graph_frequent_subgraph_mining', 'Frequent Subgraphs in One Labeled Graph',
           'Enumerate or count connected labeled patterns meeting a declared minimum-image-support threshold in one labeled host graph.',
           [param('minimum_image_support', 'integer', 'Positive minimum over pattern vertices of the number of distinct host images.'),
            param('max_pattern_edges', 'integer', 'Positive maximum number of pattern edges.'),
            param('match_mode', 'enum', 'Whether embeddings preserve nonedges.', 'non_induced', ['non_induced', 'induced']),
            param('output_mode', 'enum', 'Pattern records or a count of distinct frequent isomorphism classes.', 'count', ['count', 'patterns'])],
           [output('frequent_pattern_count', 'integer', 'Number of distinct frequent labeled connected pattern isomorphism classes.'),
            output('patterns', 'array<object>|null', 'Canonical labeled patterns and MNI support when output_mode=patterns; null in count mode.'),
            output('completed', 'boolean', 'Whether enumeration completed through the requested size bound.')],
           ['For each pattern vertex independently collect distinct host images; support is the smallest image-set size.',
            'Deduplicate label-preserving isomorphic patterns.',
            'Use exhaustive embeddings on tiny labeled graphs as a correctness oracle.',
            'Do not substitute transaction support, number of embeddings, or edge-disjoint support for MNI.',
            'Count-only upstream releases cannot satisfy the patterns output mode without an adapter change.'],
           ['Repeated labels do not identify distinct host vertices.', 'A single host graph differs from a database of graph transactions.', 'A threshold exceeding the host vertex count yields no frequent patterns.'],
           attributes='required_discrete_vertex_labels', category='pattern_mining',
           intents=['single graph frequent subgraphs', 'minimum image support', 'mni frequent patterns'])

    define(69, 'minimum_vertex_cover', 'Minimum Vertex Cover',
           'Find a smallest set of vertices touching every edge, or decide whether a cover of size at most k exists.',
           [param('mode', 'enum', 'Optimization, parameterized decision, or heuristic feasible cover.', 'exact', ['exact', 'decision', 'heuristic']),
            param('k', 'integer|null', 'Nonnegative bound required for decision mode; otherwise ignored.', None),
            param('time_limit_seconds', 'number', 'Positive runtime budget.', 60)],
           [output('cover', 'array<vertex_id>|null', 'Feasible cover witness when available; null if no witness is returned.'),
            output('cover_size', 'integer|null', 'Cardinality of a witness or the optimum size from a size-only solver.'),
            output('decision', 'boolean|null', 'True or false only if the bounded decision is established; otherwise null.'),
            output('optimality_proven', 'boolean', 'Whether minimum size is established.'),
            output('termination_reason', 'string', 'Exhausted search, timeout, heuristic completion, or other reason.')],
           ['For a returned witness, verify that every edge has at least one endpoint in the cover.',
            'Validate optimum sizes and bounded decisions by exhaustive search on small graphs.',
            'Timeout without a witness is unknown, not proof that no cover exists.',
            'A size-only solver must declare that it did not return a witness.',
            'The complement of a cover is independent, but maximality alone does not establish minimum cover size.'],
           ['Edgeless graphs have an empty optimum cover.', 'Disconnected component optima add.', 'k=0 is feasible exactly for an edgeless graph.'],
           intents=['minimum vertex cover', 'smallest vertex cover', 'parameterized vertex cover', 'k vertex cover'])

    define(70, 'graph_condensation', 'Learned Graph Condensation',
           'Learn a smaller synthetic attributed graph whose supervised training utility approximates that of the original training graph.',
           [param('synthetic_vertex_budget', 'integer', 'Positive number of synthetic vertices, at most the number of training vertices.'),
            param('feature_key', 'string', 'Numeric vertex feature attribute.', 'features'),
            param('label_key', 'string', 'Training class-label attribute.', 'label'),
            param('split_key', 'string', 'Train/validation/test attribute.', 'split'),
            param('method', 'string', 'Condensation method, hyperparameters and training model.'),
            param('seed', 'integer', 'Seed for condensation and downstream evaluation.', 0)],
           [output('synthetic_graph', 'canonical_graph_v1', 'Synthetic vertices, learned features/labels and declared weighted adjacency.'),
            output('training_metadata', 'object', 'Method, seed, budgets, splits, preprocessing and model/checkpoint references.'),
            output('utility_metrics', 'object', 'Downstream performance and variance on held-out original data under a fixed evaluation protocol.')],
           ['Honor the synthetic vertex budget and feature/class dimensions.',
            'Synthetic IDs are new identities; do not claim a quotient mapping from original vertices.',
            'Fit on permitted training labels only; record transductive access to unlabeled topology/features.',
            'Report downstream training/evaluation configuration and held-out metrics over declared seeds.',
            'Verify finite features, valid labels, and adjacency under the declared symmetry/weight convention.'],
           ['Condensation need not preserve original edges or graph cuts.', 'Very small budgets may not represent every class.', 'A utility estimate does not prove an exact structural approximation.'],
           weights='optional_nonnegative_adjacency_weights', attributes='required_features_labels_and_splits',
           category='graph_machine_learning', exactness='Learned approximation measured by held-out downstream utility, with no structural equivalence claim.',
           intents=['graph condensation', 'synthetic training graph', 'condense graph dataset'])


if __name__ == '__main__':
    main()
