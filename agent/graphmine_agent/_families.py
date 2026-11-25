"""Generated runnable problems and documentation topics; do not edit."""

SOURCE_SHA256 = "e1c7f2054b4cc21e627a8fa35298a163ed91cb775c45b1f339e9f7a98f2a60d3"
FAMILIES = [{'id': 'records',
  'title': 'Look up records',
  'description': 'Which stored records or connections match my request? Look up, filter and summarize stored '
                 'vertex and edge records, including bounded connection queries and extraction by record '
                 'selectors. Path queries overlap with paths, and graph extraction overlaps with '
                 'preparation; choose this family when the goal is retrieving records satisfying a request.',
  'deciding_question': 'Which stored records or connections match my request?',
  'problems': ['node-lookup',
               'neighbors',
               'common-neighbors',
               'edge-filter',
               'graph-aggregate',
               'query-paths',
               'query-subgraph']},
 {'id': 'paths',
  'title': 'Paths & reachability',
  'description': 'How do I get from A to B, what can reach what, or in what order? Search, optimize or '
                 'enumerate routes, compute reachability, or order dependencies. Bounded path queries also '
                 'exist in records; choose this family when the goal is route analysis or dependency order.',
  'deciding_question': 'How do I get from A to B, what can reach what, or in what order?',
  'problems': ['breadth-first-search',
               'single-source-shortest-paths',
               'many-source-shortest-paths',
               'widest-paths',
               'temporal-paths',
               'top-k-critical-paths',
               'bounded-paths-cycles',
               'transitive-closure',
               'topological-sort']},
 {'id': 'connectivity',
  'title': 'Connectivity, cuts & trees',
  'description': 'Is it connected, where does it break, or what is the cheapest way to connect it? Find '
                 'components and biconnected blocks, identify capacity bottlenecks with flow and cuts, or '
                 'connect vertices and required groups with trees.',
  'deciding_question': 'Is it connected, where does it break, or what is the cheapest way to connect it?',
  'problems': ['connected-components',
               'biconnected-components',
               'max-flow-min-cut',
               'spanning-tree-forest',
               'group-steiner-tree']},
 {'id': 'dense',
  'title': 'Cliques & dense subgraphs',
  'description': 'Which tightly connected groups exist? Clique: every pair connected. Biclique: every cross '
                 'pair connected. k-core: at least k neighbours each. k-truss: each edge in at least k−2 '
                 'triangles. Densest: most edges per vertex, or the declared weighted or higher-order clique '
                 'density. Quasi-clique: a minimum internal-degree fraction. These problems select subgraphs '
                 'satisfying a structural definition; they do not require a partition of all vertices.',
  'deciding_question': 'Which tightly connected groups exist?',
  'problems': ['maximal-cliques',
               'maximum-clique',
               'k-cliques',
               'maximal-bicliques',
               'maximal-biclique-counting',
               'quasi-cliques',
               'densest-subgraph',
               'densest-k-subgraph',
               'k-core',
               'k-truss']},
 {'id': 'communities',
  'title': 'Communities & partitions',
  'description': 'How should vertices be grouped or partitioned? Find communities, balanced partitions or '
                 'signed-network group structure. Full partitions assign vertices to groups; local and '
                 'overlapping communities may cover only part of the graph. Unlike dense, the organizing '
                 'question is group membership or partition structure, rather than selecting a subgraph by a '
                 'clique, core, truss or density definition.',
  'deciding_question': 'How should vertices be grouped or partitioned?',
  'problems': ['community-detection',
               'seeded-local-community',
               'overlapping-communities',
               'balanced-partitioning',
               'hypergraph-partitioning',
               'signed-balance']},
 {'id': 'importance',
  'title': 'Importance & influence',
  'description': 'Which vertices matter most, or which seeds spread furthest? Measure vertex centrality, '
                 'rank vertices globally or relative to chosen seeds, or select seeds for an explicitly '
                 'defined spreading process.',
  'deciding_question': 'Which vertices matter most, or which seeds spread furthest?',
  'problems': ['degree-centrality',
               'betweenness-centrality',
               'pagerank',
               'personalized-pagerank',
               'influence-maximization']},
 {'id': 'similarity',
  'title': 'Similarity & comparison',
  'description': 'How alike are two vertices or two graphs, or which link is missing? Compare network '
                 'neighborhoods, score possible missing links, or compare and align graphs through edit '
                 'distance, common subgraphs or vertex correspondences.',
  'deciding_question': 'How alike are two vertices or two graphs, or which link is missing?',
  'problems': ['simrank',
               'link-prediction',
               'graph-edit-distance',
               'maximum-common-subgraph',
               'network-alignment']},
 {'id': 'motifs',
  'title': 'Counting motifs',
  'description': 'How many small shapes (triangles, butterflies, graphlets, motifs, timed motifs) are there? '
                 'Count or list the supported shapes, including updates to triangle counts and ordered '
                 'temporal events. Bipartite and temporal input requirements determine eligibility, not '
                 'separate families.',
  'deciding_question': 'How many small shapes (triangles, butterflies, graphlets, motifs, timed motifs) are '
                       'there?',
  'problems': ['triangle-counting',
               'dynamic-triangle-counting',
               'butterfly-counting',
               'graphlet-counting',
               'motif-counting',
               'temporal-motifs']},
 {'id': 'patterns',
  'title': 'Pattern matching & mining',
  'description': 'Where does a given pattern occur, or which patterns are frequent? Match a supplied pattern '
                 "or mine frequent subgraphs in one graph or a graph collection, using the problem's "
                 'declared matching and support semantics.',
  'deciding_question': 'Where does a given pattern occur, or which patterns are frequent?',
  'problems': ['subgraph-isomorphism', 'frequent-subgraphs', 'single-graph-frequent-subgraphs']},
 {'id': 'selection',
  'title': 'Assignment & selection',
  'description': 'Pick non-conflicting pairs or items, cover every edge, or colour without conflicts. Match '
                 'pairs or assign workers to tasks, select independent vertices, cover connections with '
                 'vertices, or assign colours under the declared conflict rules.',
  'deciding_question': 'Pick non-conflicting pairs or items, cover every edge, or colour without conflicts.',
  'problems': ['bipartite-matching',
               'weighted-matching',
               'maximal-independent-set',
               'maximum-independent-set',
               'minimum-vertex-cover',
               'vertex-coloring']},
 {'id': 'preparation',
  'title': 'Prepare, sample & draw',
  'description': 'Build, clean, shrink, sample, extract or draw a graph before analysis. Resolve entities, '
                 'construct or reduce graphs, sample neighborhoods or walks, and compute layouts. Graph '
                 'extraction overlaps with records; choose this family when the goal is preparing a graph '
                 'for subsequent analysis.',
  'deciding_question': 'Build, clean, shrink, sample, extract or draw a graph before analysis.',
  'problems': ['entity-resolution',
               'graph-coarsening',
               'induced-subgraph',
               'knn-graph',
               'spectral-sparsification',
               'neighborhood-sampling',
               'random-walks',
               'force-directed-layout']},
 {'id': 'spectral',
  'title': 'Spectral & topology',
  'description': 'Eigenvectors, smoothing signals over the graph, or shape across thresholds. Compute '
                 'Laplacian eigenpairs, denoise graph signals, or track topological features through a '
                 'filtration.',
  'deciding_question': 'Eigenvectors, smoothing signals over the graph, or shape across thresholds.',
  'problems': ['laplacian-eigenpairs', 'graph-signal-denoising', 'persistent-homology']},
 {'id': 'statistics',
  'title': 'Statistics & anomalies',
  'description': 'Is this unusual compared with a baseline or a random graph? Detect graph anomalies under '
                 'an explicit baseline or assess significance against a declared null-model ensemble.',
  'deciding_question': 'Is this unusual compared with a baseline or a random graph?',
  'problems': ['graph-anomalies', 'null-model-significance']},
 {'id': 'learning',
  'title': 'Learning & embeddings',
  'description': 'Learn from features and labels, or learn vectors for vertices or triples. Train vertex, '
                 'graph or hypergraph predictors, condense training data, infer locations under a declared '
                 'model, or learn node and knowledge-graph embeddings. Hypergraph inputs are an eligibility '
                 'requirement, not a separate family.',
  'deciding_question': 'Learn from features and labels, or learn vectors for vertices or triples.',
  'problems': ['node-learning',
               'graph-learning',
               'hypergraph-node-learning',
               'graph-condensation',
               'graph-geolocation',
               'node-embedding',
               'knowledge-graph-embedding']}]

PROBLEM_FAMILY = {p: f["id"] for f in FAMILIES for p in f["problems"]}

PROBLEMS = {'records': {'node-lookup': {'title': 'Look up entity records',
                             'description': 'Native deterministic selection of original vertex records by '
                                            'typed IDs and AND field predicates. Explicit empty vertex lists '
                                            'select nothing. Missing fields match only exists=false; unknown '
                                            'field paths fail. Counts remain complete when row collections '
                                            'are capped.',
                             'topic': 'graph_record_queries'},
             'neighbors': {'title': 'Find nearby entities over selected relationships',
                           'description': 'Native filtered hop reachability with exact distances. Directed '
                                          'out/in/both traversal; undirected edges traverse both ways. '
                                          'Parallel records do not duplicate vertices; include_seed controls '
                                          'the root. Original input vertex ordering and explicit collection '
                                          'completeness.',
                           'topic': 'graph_record_queries'},
             'common-neighbors': {'title': 'Find the direct neighbors two entities share',
                                  'description': 'Native intersection of direct filtered neighbor sets, '
                                                 'preserving the declared direction and self-loop adjacency '
                                                 'meaning. Typed entity IDs; stable original vertex order. '
                                                 'Complete count with explicitly capped collections.',
                                  'topic': 'graph_record_queries'},
             'edge-filter': {'title': 'Filter relationship records and join endpoint attributes',
                             'description': 'Native deterministic original-edge selection without collapsing '
                                            'loops or parallel events. Edge and source/target predicates use '
                                            'stored endpoints even for undirected input. Typed IDs, exact '
                                            'decimal scalar comparisons and explicit incomplete capped '
                                            'ports.',
                             'topic': 'graph_record_queries'},
             'graph-aggregate': {'title': 'Summarize recorded numeric values',
                                 'description': 'Native count, sum, average, minimum or maximum of an '
                                                'explicit field, grouped by a scalar field or vertex. Exact '
                                                'decimal rational arithmetic is authoritative; display '
                                                'values disclose rounding. Per-vertex edge groups include '
                                                'isolates and count loops once. Missing numeric/group fields '
                                                'fail. Stable exact-value sorting and completeness-aware '
                                                'result limits.',
                                 'topic': 'graph_record_queries'},
             'query-paths': {'title': 'Find bounded connections between two entities',
                             'description': 'Native iterative enumeration of all hop-shortest or all '
                                            'vertex-simple paths within max_hops. Filtered directed '
                                            'out/in/both traversal with parallel edge identities preserved. '
                                            'Source equal to target has one zero-edge path. Counts are '
                                            'exhaustive; capped path and membership ports are incomplete.',
                             'topic': 'graph_record_queries'},
             'query-subgraph': {'title': 'Extract selected records as a graph',
                                'description': 'Native vertex-induced, edge-induced or filtered-neighborhood '
                                               'extraction. Preserve typed IDs, original attributes, '
                                               'direction, weights, loop and parallel records. Edge mode '
                                               'retains endpoints; vertex mode retains selected isolates. '
                                               'Derived graph identity carries source content lineage.',
                                'topic': 'graph_record_queries'}},
 'paths': {'breadth-first-search': {'title': 'Connections within a number of steps',
                                    'description': 'Minimum hop distances with explicit independent or '
                                                   'nearest-source searches. Preserve direction; discard '
                                                   'loops and collapse duplicate arcs; weights are ignored. '
                                                   'IDs are signed int64 or strings.',
                                    'topic': 'breadth_first_search'},
           'single-source-shortest-paths': {'title': 'Shortest weighted paths from one vertex',
                                            'description': 'Nonnegative lengths; preserve direction, drop '
                                                           'loops and keep minimum parallel length. CPU '
                                                           'returns exact rational costs over admitted '
                                                           'binary64 weights; GPU returns float64 costs. '
                                                           'Cutoff is inclusive.',
                                            'topic': 'single_source_shortest_paths'},
           'many-source-shortest-paths': {'title': 'Shortest paths between selected vertex sets',
                                          'description': 'Selected origins and destinations, or all vertices '
                                                         'for null. Nonnegative lengths, minimum parallel '
                                                         'length and preserved direction; CPU exact costs '
                                                         'and GPU float64 costs.',
                                          'topic': 'many_source_shortest_paths'},
           'widest-paths': {'title': 'Find the greatest bottleneck capacity from a source',
                            'description': 'Exact max-min capacities with a predecessor witness, preserving '
                                           'direction. Every edge needs nonnegative capacity; loops '
                                           'discarded and largest parallel capacity wins. Zero is reachable. '
                                           'Source infinity and unreachable nulls have distinct flags.',
                            'topic': 'widest_paths'},
           'temporal-paths': {'title': 'Find earliest arrivals or fastest journeys through timed events',
                              'description': 'Exact rational time-expanded shortest paths. Directed event '
                                             'input; every edge needs a timestamp and nonnegative duration '
                                             'attribute. Waiting is allowed. Fastest duration excludes '
                                             'waiting before initial departure. Inclusive ready time and '
                                             'deadline preserve distinct parallel events.',
                              'topic': 'temporal_fastest_paths'},
           'top-k-critical-paths': {'title': 'Find the highest-cost paths through a DAG',
                                    'description': 'Exact rational k-best DAG paths, retaining parallel edge '
                                                   'identities and negative weights. Omitted sources and '
                                                   'sinks select zero-in/out-degree vertices. A zero-edge '
                                                   'path is included when a source is also a sink. Finishing '
                                                   'top-k does not imply the path collection is exhaustive.',
                                    'topic': 'top_k_critical_paths_dag'},
           'bounded-paths-cycles': {'title': 'Enumerate bounded simple paths or cycles',
                                    'description': 'Exact directed simple edge paths and cycles up to '
                                                   'max_hops. Drop loops; collapse to first parallel edge or '
                                                   'retain identities. Optional strict chronological order '
                                                   'applies after canonical cycle rotation. A result cap '
                                                   'retains the shortest sequences while the total count '
                                                   'remains exhaustive.',
                                    'topic': 'hop_constrained_cycle_path_enumeration'},
           'transitive-closure': {'title': 'Find which places can reach each other',
                                  'description': 'Exact reflexive reachability: every vertex reaches itself '
                                                 'by a zero-length path. Preserve graph direction, ignore '
                                                 'weights, loops and duplicates. Count-only closure has a '
                                                 'complete scalar and incomplete pair-list port.',
                                  'topic': 'transitive_closure_reachability'},
           'topological-sort': {'title': 'Order a directed acyclic graph',
                                'description': 'Return a deterministic topological order. Reject directed '
                                               'cycles, including self-loops. Duplicate arcs collapse; '
                                               'weights are ignored.',
                                'topic': 'topological_sort'}},
 'connectivity': {'connected-components': {'title': 'Connected vertex groups',
                                           'description': 'Weak or strong connectivity. Weak mode uses an '
                                                          'undirected projection; strong mode preserves '
                                                          'direction. Loops, duplicate edges and weights do '
                                                          'not affect membership.',
                                           'topic': 'connected_components'},
                  'biconnected-components': {'title': 'Find fragile connections and cut vertices',
                                             'description': 'Exact vertex-biconnected edge blocks, bridges '
                                                            'and articulation vertices. Undirected input; '
                                                            'loops discarded and parallel edges collapsed. '
                                                            'Every normalized edge keeps its first original '
                                                            'ID and all source edge IDs.',
                                             'topic': 'biconnected_components'},
                  'max-flow-min-cut': {'title': 'Find capacity and bottlenecks between two places',
                                       'description': 'Exact rational flow and cut certificate. Sum parallel '
                                                      'capacities, discard loops and treat undirected edges '
                                                      'as two directed arcs. Optional vertex capacities use '
                                                      'typed {vertex,capacity} records and include '
                                                      'explicitly limited terminals. Mixed cuts return '
                                                      'original edge IDs plus cut vertices.',
                                       'topic': 'max_flow_min_cut'},
                  'spanning-tree-forest': {'title': 'Minimum or maximum spanning forest',
                                           'description': 'Undirected weighted forests with isolates '
                                                          'retained. Negative lengths are allowed. Keep '
                                                          'minimum or maximum parallel weights according to '
                                                          'the objective; discard loops.',
                                           'topic': 'spanning_tree_forest'},
                  'group-steiner-tree': {'title': 'Connect representatives of every required group',
                                         'description': 'Exact bounded vertex-subset optimization with a '
                                                        'minimum spanning tree for each feasible induced '
                                                        'subgraph. Covers every group and required vertex, '
                                                        'allowing overlapping representatives. Undirected '
                                                        'nonnegative weighted input, loops removed, cheapest '
                                                        'original parallel edge retained. Reports exact '
                                                        'rational cost or certified infeasibility.',
                                         'topic': 'group_steiner_tree'}},
 'dense': {'maximal-cliques': {'title': 'Find complete groups that cannot be extended',
                               'description': 'Exact maximal cliques in an undirected simple projection. '
                                              'Drop loops and duplicate edges; ignore weights. Original GPU '
                                              'kernels supply a count, with bounded C++ materialization and '
                                              'explicit list completeness.',
                               'topic': 'maximal_clique_enumeration'},
           'maximum-clique': {'title': 'Find the largest fully connected group',
                              'description': 'Exact maximum clique, optionally all tied optima. Undirected '
                                             'simple projection; loops, duplicate edges and weights ignored. '
                                             'Original GPU witnesses are checked by native coloring or exact '
                                             'search; ties use native materialization.',
                              'topic': 'maximum_clique'},
           'k-cliques': {'title': 'Count or list complete groups of a chosen size',
                         'description': 'Exact count for k>=2 with no upper k bound on CPU. Undirected '
                                        'simple projection; loops, duplicate edges and weights ignored. GPU '
                                        'counts require supported k and a uint64 count bound. Counts remain '
                                        'complete when memberships are capped.',
                         'topic': 'k_clique_counting_enumeration'},
           'maximal-bicliques': {'title': 'Find completely connected groups across two sides',
                                 'description': 'Exact inclusion-maximal bicliques with nonempty sides. '
                                                'Supply both disjoint partitions covering every vertex, or '
                                                "omit both to use every vertex's attributes.side=left|right. "
                                                'Undirected input; loops discarded and duplicate edges '
                                                'collapsed. Capped memberships are marked incomplete.',
                                 'topic': 'maximal_biclique_enumeration'},
           'maximal-biclique-counting': {'title': 'Count all maximal bicliques',
                                         'description': 'Count nonempty maximal bicliques with '
                                                        'attributes.side=left|right on every vertex. '
                                                        'Undirected simple projection. MBE-GPU count is '
                                                        'checked against bounded native enumeration; no size '
                                                        'filtering.',
                                         'topic': 'maximal_biclique_enumeration'},
           'quasi-cliques': {'title': 'Find groups meeting a minimum internal-degree fraction',
                             'description': 'Exact gamma quasi-cliques on an undirected simple projection. '
                                            'Thresholds use decimal-rational gamma; maximality is relative '
                                            'to all qualifying sets within the size bounds. Search is '
                                            'bounded by work and output budgets.',
                             'topic': 'quasi_clique_mining'},
           'densest-subgraph': {'title': 'Find the region with the most edges or cliques per vertex',
                                'description': 'Exact induced k-clique count divided by vertex count. '
                                               'Weighted density is defined for clique_order=2, summing '
                                               'parallel weights. Undirected input; loops discarded. Native '
                                               'rational maximum-weight closure for minimum_vertices=1; '
                                               'bounded exhaustive cardinality search otherwise.',
                                'topic': 'densest_subgraph'},
           'densest-k-subgraph': {'title': 'Find exactly k vertices with the greatest internal edge value',
                                  'description': 'Exact bounded cardinality search. Sum parallel nonnegative '
                                                 'weights, discard loops, require undirected input. An '
                                                 'approximate request receives the stronger exact result '
                                                 'when search completes.',
                                  'topic': 'densest_k_subgraph'},
           'k-core': {'title': 'Find the well-connected core',
                      'description': 'Exact core numbers and optional selected vertices. Undirected simple '
                                     'projection; loops, duplicate edges and weights ignored. Isolates have '
                                     'core number zero.',
                      'topic': 'k_core_decomposition'},
           'k-truss': {'title': 'Find connections supported by triangles',
                       'description': 'Complete edge truss numbers using the k-2 support convention, plus '
                                      'optional k-truss selection. Undirected simple projection, weights '
                                      'ignored. First original edge IDs represent collapsed edges; source '
                                      'IDs are retained.',
                       'topic': 'k_truss_decomposition'}},
 'communities': {'community-detection': {'title': 'Divide a network into communities',
                                         'description': 'Undirected modularity or constant Potts objective. '
                                                        'Exact mode enumerates partitions with rational '
                                                        'objectives; heuristic mode uses seeded '
                                                        'positive-gain vertex moves and makes no '
                                                        'global-optimum claim. Drop loops and collapse '
                                                        'unweighted or sum weighted parallel edges. CPM is '
                                                        'internal edge weight minus resolution times '
                                                        'within-part vertex pairs.',
                                         'topic': 'community_detection'},
                 'seeded-local-community': {'title': 'Find a community around required seeds',
                                            'description': 'Heuristic personalized-PageRank '
                                                           'degree-normalized sweep with required seeds '
                                                           'first. Returns the lowest defined weighted '
                                                           'conductance among feasible prefixes. Exact '
                                                           'cut/volume recomputation, no global-optimum '
                                                           'claim. Undirected input; reject loops, sum '
                                                           'nonnegative parallel weights. If all conductance '
                                                           'denominators vanish, return the seeds.',
                                            'topic': 'seeded_local_community_detection'},
                 'overlapping-communities': {'title': 'Find overlapping tightly connected groups',
                                             'description': 'Exact k-clique percolation. Undirected simple '
                                                            'projection; discard loops and duplicates. '
                                                            'Communities can overlap. Unassigned vertices '
                                                            'are outside all percolation communities before '
                                                            'minimum-size display filtering.',
                                             'topic': 'overlapping_community_detection'},
                 'balanced-partitioning': {'title': 'Split a graph into balanced groups with few crossing '
                                                    'edges',
                                           'description': 'Exact bounded partition search with nonempty '
                                                          'parts and both lower and upper balance limits. '
                                                          'Undirected input, nonnegative edge weights, loop '
                                                          'removal and duplicate collapse or weighted sum. '
                                                          'Normalized cut sums each part boundary divided by '
                                                          'its declared balance size. Decimal-rational '
                                                          'imbalance tolerance; exact objective and '
                                                          'infeasibility certificates.',
                                           'topic': 'balanced_graph_partitioning'},
                 'hypergraph-partitioning': {'title': 'Partition hyperedges directly with bounded vertex '
                                                      'weights',
                                             'description': 'Exact native enumeration of nonempty parts, '
                                                            'optimizing weighted cut-net or '
                                                            'connectivity-minus-one without graph '
                                                            'projection. Exact rational vertex and hyperedge '
                                                            'weights, decimal imbalance tolerance and upper '
                                                            'part-weight bound. Certified infeasibility when '
                                                            'no partition qualifies; exponential search '
                                                            'obeys work budgets.',
                                             'topic': 'hypergraph_partitioning'},
                 'signed-balance': {'title': 'Check balance or minimize frustrated connections',
                                    'description': 'Exact signed parity balance test and bounded rational '
                                                   'frustration minimization. Every edge type is positive or '
                                                   'negative. Undirected input; drop loops, reject '
                                                   'contradictory parallel signs and collapse unweighted or '
                                                   'sum weighted parallels. Zero-cost violations still make '
                                                   'the network structurally unbalanced.',
                                    'topic': 'signed_network_structural_balance'}},
 'importance': {'degree-centrality': {'title': 'Rank vertices by their number of connections',
                                      'description': 'Exact degree scores with outgoing, incoming, both or '
                                                     'undirected-projection semantics. Drop loops, collapse '
                                                     'duplicate edges and ignore weights. Optional '
                                                     'normalization divides by n-1; isolates score zero.',
                                      'topic': 'centrality_influential_node_mining'},
                'betweenness-centrality': {'title': 'Rank vertices that connect shortest paths',
                                           'description': 'All-source betweenness excluding endpoints. '
                                                          'Preserve direction, drop loops and keep minimum '
                                                          'parallel length. CPU supports exact rational '
                                                          'scores and strictly positive weighted paths; GPU '
                                                          'profiles use unweighted paths with declared '
                                                          'floating-point arithmetic.',
                                           'topic': 'centrality_influential_node_mining'},
                'pagerank': {'title': 'PageRank influence scores',
                             'description': 'Directed random-walk scores with uniform restart and dangling '
                                            'distribution. Drop loops, sum parallel weights and '
                                            'independently verify the fixed-point residual.',
                             'topic': 'centrality_influential_node_mining'},
                'personalized-pagerank': {'title': 'Restart walks around seed vertices',
                                          'description': 'Seeded PageRank with explicit direction, weight '
                                                         'and dangling policies. Full score port stays '
                                                         'complete when the displayed ranking is filtered or '
                                                         'capped.',
                                          'topic': 'personalized_pagerank_rwr'},
                'influence-maximization': {'title': 'Choose seeds that maximize expected diffusion',
                                           'description': 'Exact native IC/LT optimization, or explicitly '
                                                          'requested SuperFuser independent-cascade '
                                                          'heuristic with holdout spread estimation. The '
                                                          'heuristic does not certify optimality or an '
                                                          'approximation guarantee.',
                                           'topic': 'influence_maximization'}},
 'similarity': {'simrank': {'title': 'Compare vertices by the similarity of their neighbors',
                            'description': 'Native float64 SimRank fixed-point iteration with a recomputed '
                                           'contraction error bound. Incoming or undirected-projection '
                                           'neighborhoods; drop loops and duplicates, ignore weights. '
                                           'Single-source output excludes itself. Top-k ports explicitly '
                                           'disclose omitted pairs.',
                            'topic': 'simrank_vertex_similarity'},
                'link-prediction': {'title': 'Score potential links from local neighborhoods',
                                    'description': 'Undirected simple neighborhoods; loops and weights '
                                                   'ignored. CPU supports eight local measures; GPU supports '
                                                   'Jaccard. Candidate limits apply before top_k; capped '
                                                   'output is explicitly incomplete.',
                                    'topic': 'link_prediction'},
                'graph-edit-distance': {'title': 'Compute minimum graph edit cost with an executable witness',
                                        'description': 'Exact bounded native partial correspondences over '
                                                       'simple normalized directed or undirected graphs. '
                                                       'Selected categorical vertex/edge labels; decimal '
                                                       'rational costs. Vertex label replacement costs '
                                                       'insertion plus deletion, edge substitution competes '
                                                       'with deletion plus insertion. Returns normalized '
                                                       'graphs and an ordered stable-handle script whose '
                                                       'total is checked against the optimum. Weights and '
                                                       'timestamps are ignored.',
                                        'topic': 'graph_edit_distance_mcs'},
                'maximum-common-subgraph': {'title': 'Find the largest common graph by vertex count',
                                            'description': 'Exact bounded native induced matching, or '
                                                           'label-compatible maximum vertex matching for '
                                                           'non-induced output where isolated vertices are '
                                                           'allowed. Preserve direction and selected '
                                                           'categorical labels, ignore weights/timestamps. '
                                                           'Returns a checked common graph and injective '
                                                           'correspondence. No secondary maximum-edge '
                                                           'objective. Explicit loop/parallel normalization.',
                                            'topic': 'graph_edit_distance_mcs'},
                'network-alignment': {'title': 'Align two graphs while conserving edges and supplied '
                                               'similarities',
                                      'description': 'Exact bounded global injective assignment covering '
                                                     'every vertex of the smaller graph. Maximize '
                                                     'topology_weight times conserved edge value plus pair '
                                                     'priors. Direction must match. Drop loops and collapse '
                                                     'unweighted or sum nonnegative weighted parallel edges. '
                                                     'Weighted conservation is the minimum of paired '
                                                     'normalized edge weights.',
                                      'topic': 'network_alignment'}},
 'motifs': {'triangle-counting': {'title': 'Count or list triangles',
                                  'description': 'Count three-vertex cliques of an undirected graph. Discard '
                                                 'loops and collapse duplicate edges; weights are ignored. '
                                                 'GPU enumeration uses native CPU materialization with count '
                                                 'verification.',
                                  'topic': 'triangle_counting_listing'},
            'dynamic-triangle-counting': {'title': 'Update triangle counts after an edge batch',
                                          'description': 'Exact deletion-before-insertion batch on an '
                                                         'undirected simple graph. Reject repeated updates, '
                                                         'absent deletions and existing insertions; preserve '
                                                         'external IDs. EDTC GPU counts are checked against '
                                                         'bounded native materialization.',
                                          'topic': 'triangle_counting_listing'},
            'butterfly-counting': {'title': 'Count four-way connections between two sides',
                                   'description': 'Exact 2-by-2 biclique counts, participation and '
                                                  'alpha/beta cores. Every vertex requires '
                                                  'attributes.side=left|right. Reject directed input, loops '
                                                  'and same-side edges; collapse duplicates. Core thresholds '
                                                  'explicitly use degree or butterfly participation.',
                                   'topic': 'butterfly_counting_bipartite'},
            'graphlet-counting': {'title': 'Count connected induced graph shapes and vertex roles',
                                  'description': 'Native isomorphism classification against the complete '
                                                 'connected undirected graph atlas for sizes two through '
                                                 'seven. Static atlas IDs and exact automorphism orbits are '
                                                 'embedded; Python is not required. Discard loops and '
                                                 'duplicate edges, ignore weights. Counts and optional orbit '
                                                 'participation stay complete when memberships are capped.',
                                  'topic': 'graphlet_counting'},
            'motif-counting': {'title': 'Count supplied connected motifs',
                               'description': 'Exact structural embeddings with explicit occurrence '
                                              'identity: all mappings or unique vertex-set and image-edge '
                                              'classes. Preserve direction; simple projections discard '
                                              'loops, duplicate edges and weights. Non-induced motifs on the '
                                              'same vertex set can be distinct instances. Counts remain '
                                              'complete when lists are capped.',
                               'topic': 'graph_motif_counting'},
            'temporal-motifs': {'title': 'Count graph patterns with ordered edge events',
                                'description': 'Exact native structural matching and injective event '
                                               'assignments. Rational UTC timestamps, acyclic partial order, '
                                               'inclusive duration limit, optional temporal inducedness and '
                                               'typed predicates. Event tuples in query-edge input order '
                                               'identify occurrences. Counts and vertex participation remain '
                                               'complete when instance lists are capped.',
                                'topic': 'temporal_motif_mining'}},
 'patterns': {'subgraph-isomorphism': {'title': 'Find matches for a supplied graph pattern',
                                       'description': 'Exact native induced or non-induced injective '
                                                      'matching, preserving direction, loops and parallel '
                                                      'multiplicities. Declarative typed vertex and edge '
                                                      'predicates; distinct query edges must match distinct '
                                                      'data edges. Capped mapping collections are explicitly '
                                                      'incomplete.',
                                       'topic': 'subgraph_isomorphism'},
              'frequent-subgraphs': {'title': 'Mine patterns shared across graph transactions',
                                     'description': 'Exact bounded native enumeration of simple labeled '
                                                    'directed or undirected patterns, including disconnected '
                                                    'and isolated vertices. Support counts transactions '
                                                    'once. Native lexicographic canonicalization has its own '
                                                    'stable pattern IDs. Positive support fraction uses '
                                                    'exact decimal comparison. Explicit loop and parallel '
                                                    'policies; no Python runtime.',
                                     'topic': 'frequent_subgraph_mining'},
              'single-graph-frequent-subgraphs': {'title': 'Mine frequent labeled patterns within a graph',
                                                  'description': 'Exact connected undirected patterns '
                                                                 'including single vertices. Minimum-image '
                                                                 'support is the smallest host image-set '
                                                                 'size over all injective embeddings. Every '
                                                                 'vertex needs the selected label or type. '
                                                                 'Reject loops; explicit parallel collapse. '
                                                                 'Native canonical IDs, bounded enumeration '
                                                                 'and complete counts; count mode does not '
                                                                 'materialize patterns.',
                                                  'topic': 'single_graph_frequent_subgraph_mining'}},
 'selection': {'bipartite-matching': {'title': 'Match items on two sides by count, value or cost',
                                      'description': 'Exact cardinality, weight or cost matching with '
                                                     'attributes.side=left|right on every vertex. Reject '
                                                     'same-side edges and loops; keep the best parallel '
                                                     'edge. Weighted objectives require explicit weights. '
                                                     'Without required smaller-side coverage, empty matching '
                                                     'may be optimal. Infeasible coverage has no witness '
                                                     'port.',
                                      'topic': 'bipartite_matching_assignment'},
               'weighted-matching': {'title': 'Find the highest-value non-conflicting pairs',
                                     'description': 'Exact maximum-weight matching on an undirected graph, '
                                                    'with no cardinality constraint. Require nonnegative '
                                                    'weights; discard loops and keep the largest parallel '
                                                    'weight. Preserve selected original edge IDs and return '
                                                    'exact rational totals over admitted binary64 weights. '
                                                    'Zero-weight edges may be omitted.',
                                     'topic': 'general_graph_weighted_matching'},
               'maximal-independent-set': {'title': 'Find a non-conflicting group that cannot be extended',
                                           'description': 'Greedy maximal independent set with verified '
                                                          'independence and maximality; no maximum-size '
                                                          'claim. Undirected simple projection; discard '
                                                          'loops and duplicate edges, ignore weights and '
                                                          'preserve isolates.',
                                           'topic': 'maximal_independent_set'},
               'maximum-independent-set': {'title': 'Find the largest non-conflicting group',
                                           'description': 'Exact maximum independent set via maximum clique '
                                                          'of the complement. Undirected simple projection; '
                                                          'loops, duplicate edges and weights ignored. '
                                                          'Complement construction and search are bounded.',
                                           'topic': 'maximum_independent_set'},
               'minimum-vertex-cover': {'title': 'Cover every connection with as few vertices as possible',
                                        'description': 'Exact minimum vertex cover, or decision against k, '
                                                       'from a maximum independent set. Undirected simple '
                                                       'projection; loops, duplicate edges and weights '
                                                       'ignored. Native complement construction and search '
                                                       'are bounded.',
                                        'topic': 'minimum_vertex_cover'},
               'vertex-coloring': {'title': 'Assign different colors to nearby vertices',
                                   'description': 'Proper greedy distance-1 or distance-2 coloring; no '
                                                  'minimum-color claim. Undirected simple projection with '
                                                  'isolates preserved. GPU colors the native C++ constructed '
                                                  'distance conflict graph.',
                                   'topic': 'vertex_coloring'}},
 'preparation': {'entity-resolution': {'title': 'Find candidate record pairs and resolve declared matches',
                                       'description': 'Complete native disjunctive blocking rules with '
                                                      'equality, Unicode tokens, codepoint Levenshtein or '
                                                      'exact numeric difference. ICU NFKC and full case '
                                                      'folding; optional missing fields fail the predicate. '
                                                      'Input edges are unused hints. Connected-components '
                                                      'resolution or exact bounded minimum candidate-pair '
                                                      'disagreement partitions; neutral noncandidates and no '
                                                      'cross-component clusters.',
                                       'topic': 'entity_resolution_blocking'},
                 'graph-coarsening': {'title': 'Aggregate vertices and edges into a weighted quotient graph',
                                      'description': 'Supplied integer partition or native greedy maximal '
                                                     'matching; all vertices remain represented. Undirected '
                                                     'nonnegative input, reject loops. Sum original parallel '
                                                     'edge weights once, retain or drop intra-cluster edges, '
                                                     'sum or mean feature vectors. Exact rational aggregates '
                                                     'are reported separately from rounded binary64 graph '
                                                     'values. Greedy partition has no optimality claim.',
                                      'topic': 'graph_coarsening'},
                 'induced-subgraph': {'title': 'Extract a graph around selected vertices',
                                      'description': 'Exact induced or ego subgraph, preserving typed IDs, '
                                                     'edge instances and properties. Ego radius includes all '
                                                     'vertices within that distance. Direction affects '
                                                     'discovery only; output retains original edge '
                                                     'direction. GPU ego discovery uses libcugraph BFS with '
                                                     'native materialization.',
                                      'topic': 'induced_subgraph_ego_extraction'},
                 'knn-graph': {'title': 'Connect nearby feature vectors',
                               'description': 'Native exhaustive pairwise Euclidean, squared Euclidean or '
                                              'cosine distances with self-exclusion and input-order tie '
                                              'breaking. Directed, union or mutual symmetrization. Cosine '
                                              'rejects zero vectors. Exact neighbor search under numerical '
                                              'distances even when approximate is requested; preserves typed '
                                              'vector IDs.',
                               'topic': 'knn_graph_construction'},
                 'spectral-sparsification': {'title': 'Sample fewer edges and measure every Laplacian '
                                                      'distortion direction',
                                             'description': 'Native effective-resistance sampling with '
                                                            'replacement, exact rational draw normalization '
                                                            'and importance reweighting. LAPACK grounded '
                                                            'solves and all generalized eigenvalues measure '
                                                            'numerical distortion; requested epsilon must '
                                                            'pass. Explicit weighted undirected simple '
                                                            'input, no loops/parallels. Preserve original '
                                                            'IDs/attributes. Identity shortcut when budget '
                                                            'covers positive edges, zero-weight edges '
                                                            'removed. No probabilistic approximation '
                                                            'guarantee is claimed.',
                                             'topic': 'spectral_graph_sparsification'},
                 'neighborhood-sampling': {'title': 'Sample connections around starting vertices',
                                           'description': 'Outgoing edge-instance sampling with hop and '
                                                          'seed-batch provenance. Support uniform or exact '
                                                          'weighted draws, replacement, typed fanouts and '
                                                          'inclusive time cutoff. Fanout -1 includes every '
                                                          'eligible edge, including zero-weight edges; loops '
                                                          'and parallel identities are retained.',
                                           'topic': 'neighborhood_sampling'},
                 'random-walks': {'title': 'Generate walks from chosen vertices',
                                  'description': 'Uniform, weighted or node2vec walks with length measured '
                                                 'in transitions. Preserve direction and loops. Uniform '
                                                 'walks collapse parallel neighbors; weighted walks sum '
                                                 'parallel weights. CPU probabilities use exact rational '
                                                 'arithmetic. Repeated starts produce separate walks.',
                                  'topic': 'random_walk_generation'},
                 'force-directed-layout': {'title': 'Compute a force-directed network drawing',
                                           'description': 'Native Fruchterman-Reingold iterations in two or '
                                                          'three dimensions. Explicit 0.01 distance '
                                                          'regularization, linear cooling from one tenth of '
                                                          'the maximum coordinate span, no final rescaling. '
                                                          'Recompute matching potential and uncooled force '
                                                          'residual; no drawing optimality claim. Project '
                                                          'direction, drop loops, collapse unweighted or sum '
                                                          'weighted parallels.',
                                           'topic': 'graph_layout_force_directed'}},
 'spectral': {'laplacian-eigenpairs': {'title': 'Compute Laplacian eigenvalues and eigenvectors',
                                       'description': 'Native LAPACK symmetric eigensolver with '
                                                      'independently recomputed absolute residual and '
                                                      'orthogonality checks. Combinatorial or '
                                                      'symmetric-normalized Laplacian, including isolates. '
                                                      'Undirected input; reject loops and negative weights, '
                                                      'sum parallel weights. Dense solver uses work budgets; '
                                                      'no iteration parameter.',
                                       'topic': 'graph_laplacian_eigenpairs'},
              'graph-signal-denoising': {'title': 'Smooth noisy measurements over a graph',
                                         'description': 'Minimize half squared signal error plus Laplacian '
                                                        'quadratic, weighted total variation, or explicit '
                                                        'graph-trend penalty. Native positive-definite solve '
                                                        'or accelerated feasible-dual optimization; '
                                                        'tolerance bounds objective gap, with a separate L2 '
                                                        'solution-error bound. Undirected input, no loops, '
                                                        'nonnegative summed parallel weights.',
                                         'topic': 'graph_signal_denoising'},
              'persistent-homology': {'title': 'Track connected components and holes across edge thresholds',
                                      'description': 'Exact sparse boundary reduction of a flag complex over '
                                                     'a declared prime field. Vertices start at zero; '
                                                     'include cofaces needed to compute deaths in requested '
                                                     'dimensions. Undirected input; reject loops, require '
                                                     'nonnegative weights, keep minimum parallel filtration. '
                                                     'Optional cutoff marks unpaired intervals '
                                                     'right-censored.',
                                      'topic': 'persistent_homology'}},
 'statistics': {'graph-anomalies': {'title': 'Rank graph entities against a declared reference',
                                    'description': 'Native structural and numeric features for vertices, '
                                                   'original edge instances or supplied induced subgraphs. '
                                                   'Population or explicit location/scale reference; '
                                                   'weighted standardized L1, L2 or maximum deviation with '
                                                   'declared minimum scale. Recompute scores, preserve '
                                                   'zero-variance failures and disclose top-k truncation. '
                                                   'Numerical deviation scores are not learned ground truth.',
                                    'topic': 'graph_anomaly_detection'},
                'null-model-significance': {'title': 'Compare a statistic with a random graph ensemble',
                                            'description': 'Uniform G(n,m), or uniform stub pairing '
                                                           'conditioned on simplicity and exact degree '
                                                           'invariants. Dense fixed-degree graphs use '
                                                           'complement sampling. Preserve direction, discard '
                                                           'loops and collapse duplicates. Statistics: '
                                                           'triangles, directed triangles, k-cliques, '
                                                           'density or a supplied-partition modularity. '
                                                           'Report every sample, population standard '
                                                           'deviation and declared empirical tail; no hidden '
                                                           'pseudocount.',
                                            'topic': 'null_model_significance_testing'}},
 'learning': {'node-learning': {'title': 'Train a graph-based vertex classifier or regressor',
                                'description': 'Native simplified graph convolution: declared mean-message '
                                               'layers, then a trained linear softmax or scalar regression '
                                               'readout. Numeric vertex_features and training_labels use '
                                               'objects containing typed {vertex,value} rows. Disjoint '
                                               'train/validation/test IDs; preprocessing and loss use '
                                               'training labels only. Transductive unlabeled '
                                               'features/topology are explicit. Saved coefficients, split '
                                               'metrics, objective and convergence status; one self message, '
                                               'collapsed parallels, weights ignored.',
                                'topic': 'node_classification_regression'},
              'graph-learning': {'title': 'Train a permutation-invariant graph predictor',
                                 'description': 'Native independent per-graph mean message passing, sum/mean '
                                                'pooling, and trained linear softmax or scalar regression '
                                                'readout. Structural [one,in-degree,out-degree] or declared '
                                                'attribute features; empty graphs pool to zeros. '
                                                'graph_labels uses typed {graph,value} rows. Train-only '
                                                'fitted preprocessing and supervised loss, disjoint graph '
                                                'splits and saved model state. Weights ignored; no '
                                                'cross-graph edges.',
                                 'topic': 'graph_classification_regression'},
              'hypergraph-node-learning': {'title': 'Learn vertex targets through the original hyperedge '
                                                    'incidence',
                                           'description': 'Native hgnn-linear-v1: weighted hyperedge feature '
                                                          'means followed by normalized vertex incidence '
                                                          'means and a trained linear softmax/regression '
                                                          'layer. No pairwise projection. Isolates retain '
                                                          'features, singleton edges remain. Feature, target '
                                                          'and split attributes are explicit; only train '
                                                          'labels fit parameters or preprocessing. Record '
                                                          'model state, finite predictions and metrics with '
                                                          'split denominators. Optional model_parameters '
                                                          'declare layers and optimizer settings.',
                                           'topic': 'hypergraph_node_learning'},
              'graph-condensation': {'title': 'Learn synthetic graph features by matching supervised '
                                              'gradients',
                                     'description': 'Native gradient_matching_linear_sgc_v1 matches training '
                                                    'softmax gradients at zero readout parameters. Learn '
                                                    'synthetic features and fix class-balanced labels on '
                                                    'declared edgeless adjacency; this is not graph '
                                                    'coarsening. Original weighted SGC features use summed '
                                                    'parallel weights plus self messages; reject original '
                                                    'loops. Budget must cover training classes and not '
                                                    'exceed training vertices. Train labels only, explicit '
                                                    'transductive features/topology, new synthetic IDs. '
                                                    'Evaluate full versus synthetic training on held-out '
                                                    'original labels over declared seeds; report objective '
                                                    'and utility variance.',
                                     'topic': 'graph_condensation'},
              'graph-geolocation': {'title': 'Propagate geographic seed locations under a geodesic objective',
                                    'description': 'Native spatial propagation by sequential discrete '
                                                   'geodesic median coordinate descent. Minimize positive '
                                                   'edge weight times spherical distance, restricting '
                                                   'coordinates to seed locations in each connected '
                                                   'component. Undirected nonnegative input, reject loops, '
                                                   'sum parallels. Fixed seeds remain exact; seedless '
                                                   'components remain unresolved. Haversine handles the '
                                                   'antimeridian; report dispersion, stopping status and '
                                                   'optional held-out geodesic errors. No supervised model '
                                                   'or calibrated confidence claim.',
                                    'topic': 'graph_based_geolocation'},
              'node-embedding': {'title': 'Learn vertex vectors from edge or walk context objectives',
                                 'description': 'Native second-order LINE or DeepWalk/node2vec fixed-window '
                                                'contexts, optimized with full-softmax cross entropy and '
                                                'declared L2 regularization. Weighted outgoing transitions '
                                                'preserve direction unless projection is requested. Explicit '
                                                'loop handling and summed parallel weights; every vertex '
                                                'receives source and context vectors. Report actual context '
                                                'masses, objective, gradient norm, seed and stopping reason; '
                                                'no global optimum or unique embedding claim.',
                                 'topic': 'node_embedding'},
              'knowledge-graph-embedding': {'title': 'Learn typed directed triple scores with DistMult',
                                            'description': 'Native DistMult with mean logistic loss over '
                                                           'declared training positives and fixed sampled '
                                                           'corruptions, plus L2 regularization. Relations '
                                                           'come only from the training split; duplicate '
                                                           'triples collapse, distinct relation identities '
                                                           'and self triples remain. Validation never '
                                                           'affects fitting. Report entity/relation '
                                                           'parameters, training examples and filtered '
                                                           'head/tail ranking metrics with average ties; no '
                                                           'unseen-relation inference.',
                                            'topic': 'knowledge_graph_embedding'}}}

TOPICS = {'graph_record_queries': {'title': 'Canonical graph record queries',
                          'description': 'Look up, filter and summarize stored vertex and edge records, '
                                         'query bounded paths, or extract selected graph records. '
                                         'query-paths returns all hop-shortest or all vertex-simple '
                                         'source-to-target paths up to a hop limit over filtered records; '
                                         'bounded-paths-cycles in paths enumerates directed simple paths or '
                                         'cycles, with optional chronological ordering. query-subgraph '
                                         'extracts vertex-induced, edge-induced or filtered-neighborhood '
                                         'records; induced-subgraph in preparation extracts an induced graph '
                                         'on selected vertices or an ego neighborhood around seeds.'},
 'breadth_first_search': {'title': 'Breadth-First Search and Unweighted Shortest Paths',
                          'description': 'Compute minimum hop distances and optional predecessor paths from '
                                         'one or more source vertices.'},
 'single_source_shortest_paths': {'title': 'Weighted Single-Source Shortest Paths',
                                  'description': 'Compute minimum path-weight sums from one source to every '
                                                 'vertex in a graph with nonnegative edge weights.'},
 'many_source_shortest_paths': {'title': 'Many-Source and All-Pairs Shortest Distances',
                                'description': 'Compute a matrix of minimum path-weight sums for selected '
                                               'origins and destinations, including all-pairs queries.'},
 'widest_paths': {'title': 'Single-Source Widest Paths',
                  'description': 'For each vertex v, maximize the minimum edge capacity along a directed '
                                 'path from a designated source to v.'},
 'temporal_fastest_paths': {'title': 'Temporal Fastest and Earliest-Arrival Paths',
                            'description': 'Find time-respecting journeys minimizing elapsed duration or '
                                           'arrival time in a directed temporal graph.'},
 'top_k_critical_paths_dag': {'title': 'Top-k Critical Paths in DAGs',
                              'description': 'Return up to k distinct source-to-sink paths of greatest total '
                                             'edge delay in a directed acyclic graph.'},
 'hop_constrained_cycle_path_enumeration': {'title': 'Hop-Constrained Simple Path and Cycle Enumeration',
                                            'description': 'Given a directed graph and a hop bound k, '
                                                           'enumerate every simple (vertex-disjoint except '
                                                           'endpoints) s-t path with at most k edges, or '
                                                           'every simple cycle through a given vertex or '
                                                           'edge with at most k edges. bounded-paths-cycles '
                                                           'enumerates directed simple paths or cycles, with '
                                                           'optional chronological ordering. query-paths in '
                                                           'records also enumerates all hop-shortest or all '
                                                           'vertex-simple paths between endpoints over '
                                                           'filtered records; the distinction is the '
                                                           'requested path-analysis or record-query profile, '
                                                           'not whether enumeration is exhaustive.'},
 'transitive_closure_reachability': {'title': 'Transitive Closure and Reachability Indexing',
                                     'description': 'Given a directed graph, determine for queried vertex '
                                                    'pairs whether the target is reachable from the source '
                                                    'via a directed path, and optionally materialize or '
                                                    'index full reachability to answer many such queries '
                                                    'efficiently.'},
 'topological_sort': {'title': 'Topological Sorting and DAG Levels',
                      'description': 'Determine whether a directed graph is acyclic and return a valid '
                                     'topological vertex order and optional dependency levels.'},
 'connected_components': {'title': 'Connected Components (Weakly and Strongly Connected)',
                          'description': 'Partition all vertices into maximal groups such that every pair of '
                                         'vertices within a group is connected according to a declared '
                                         'connectivity definition: weak (undirected) connectivity, or strong '
                                         '(directed, mutual-reachability) connectivity.'},
 'biconnected_components': {'title': 'Biconnected Components, Articulation Points and Bridges',
                            'description': 'Compute vertex-biconnected blocks of a simple undirected graph, '
                                           'plus vertices and edges whose removal increases component '
                                           'count.'},
 'max_flow_min_cut': {'title': 'Maximum Flow and Minimum s-t Cut',
                      'description': 'Given a capacitated graph and distinct source and sink vertices, '
                                     'compute a maximum feasible flow and a minimum-capacity separating cut. '
                                     'With optional vertex capacities, the cut can contain both original '
                                     'edges and capacity-limited vertices.'},
 'spanning_tree_forest': {'title': 'Minimum and Maximum Spanning Trees and Forests',
                          'description': 'Select an acyclic spanning subgraph minimizing or maximizing total '
                                         'edge weight independently within each connected component.'},
 'group_steiner_tree': {'title': 'Group Steiner Tree',
                        'description': 'Given an edge-weighted graph and a collection of potentially '
                                       'overlapping vertex groups, find a minimum-weight connected subtree '
                                       'that includes at least one vertex from every group.'},
 'maximal_clique_enumeration': {'title': 'Maximal Clique Enumeration',
                                'description': 'Given an undirected graph, enumerate every vertex set that '
                                               'forms a clique and is not a proper subset of another '
                                               'clique.'},
 'maximum_clique': {'title': 'Maximum Clique',
                    'description': 'Given an undirected graph, find a clique with the largest possible '
                                   'number of vertices.'},
 'k_clique_counting_enumeration': {'title': 'k-Clique Counting and Enumeration',
                                   'description': 'Given an undirected graph and integer k, count or '
                                                  'enumerate every complete vertex set containing exactly k '
                                                  'vertices.'},
 'maximal_biclique_enumeration': {'title': 'Maximal Biclique Enumeration',
                                  'description': 'Given a bipartite graph, enumerate complete bipartite '
                                                 'subgraphs that cannot be extended by adding a vertex to '
                                                 'either side.'},
 'quasi_clique_mining': {'title': 'Quasi-Clique Mining',
                         'description': 'Find vertex subsets whose induced subgraphs satisfy a minimum '
                                        'internal-degree fraction, allowing dense groups that are not '
                                        'complete cliques.'},
 'densest_subgraph': {'title': 'Densest Subgraph',
                      'description': 'Find a nonempty vertex subset maximizing its induced k-clique count '
                                     'divided by the number of selected vertices. Clique order k=2 gives '
                                     'ordinary edge density; the k=2 weighted variant uses total induced '
                                     'edge weight. Clique order does not constrain result cardinality.'},
 'densest_k_subgraph': {'title': 'Densest k-Subgraph',
                        'description': 'Given an undirected graph and integer k, find exactly k vertices '
                                       'maximizing the total value of edges induced by those vertices.'},
 'k_core_decomposition': {'title': 'k-Core Decomposition',
                          'description': 'Assign every vertex its largest k for which it belongs to the '
                                         'maximal induced subgraph whose vertices all have internal degree '
                                         'at least k.'},
 'k_truss_decomposition': {'title': 'k-Truss Decomposition',
                           'description': 'Assign every edge the largest k for which it belongs to a maximal '
                                          'subgraph where each edge participates in at least k-2 triangles '
                                          'within that subgraph.'},
 'community_detection': {'title': 'Disjoint Community Detection',
                         'description': 'Partition all graph vertices into nonoverlapping communities that '
                                        'maximize a declared within-community quality function.'},
 'seeded_local_community_detection': {'title': 'Seeded Local Community Detection',
                                      'description': 'Find a nontrivial low-conductance vertex subset '
                                                     'containing a specified seed set.'},
 'overlapping_community_detection': {'title': 'Overlapping Community Detection by k-Clique Percolation',
                                     'description': 'Find overlapping communities formed by connected '
                                                    'components of the clique-adjacency graph, where two '
                                                    'k-cliques are adjacent when they share k-1 vertices.'},
 'balanced_graph_partitioning': {'title': 'Balanced k-Way Graph Partitioning',
                                 'description': 'Given an undirected graph and a target part count k, assign '
                                                'every vertex to exactly one of k parts of approximately '
                                                'equal size so that the total weight of edges crossing '
                                                'between parts is minimized.'},
 'hypergraph_partitioning': {'title': 'Balanced Hypergraph Partitioning',
                             'description': 'Partition vertices of a weighted hypergraph into balanced parts '
                                            'while minimizing a declared hyperedge cut objective.'},
 'signed_network_structural_balance': {'title': 'Signed Network Structural Balance and Frustration '
                                                'Minimization',
                                       'description': 'Given a graph whose edges are each labeled positive '
                                                      'or negative, determine whether it is structurally '
                                                      'balanced (partitionable into two factions so every '
                                                      'positive edge stays within a faction and every '
                                                      'negative edge crosses factions), and when it is not, '
                                                      'find a two-faction assignment minimizing the total '
                                                      'weight of frustrated edges.'},
 'centrality_influential_node_mining': {'title': 'Centrality and Influential-Node Mining',
                                        'description': 'Compute a declared centrality score for graph '
                                                       'vertices and rank the most structurally influential '
                                                       'vertices under that definition.'},
 'personalized_pagerank_rwr': {'title': 'Personalized PageRank and Random Walk with Restart',
                               'description': "Given one or more seed vertices, compute each vertex's "
                                              'steady-state visitation probability under a random walk that '
                                              'restarts to the seed distribution with fixed probability, and '
                                              'rank vertices by that score relative to the seeds.'},
 'influence_maximization': {'title': 'Influence Maximization under Diffusion Models',
                            'description': 'Given a directed graph with edge-level influence probabilities '
                                           'and a declared stochastic diffusion model, select a seed set of '
                                           'a given size that maximizes the expected number of vertices '
                                           'eventually activated.'},
 'simrank_vertex_similarity': {'title': 'SimRank and General Vertex-to-Vertex Structural Similarity',
                               'description': 'Compute a pairwise structural similarity score between '
                                              'vertices based on the recursive principle that two vertices '
                                              'are similar to the extent their in-neighbors (or neighbors) '
                                              'are similar, for a single source vertex, a query pair, or '
                                              'top-k over all vertices.'},
 'link_prediction': {'title': 'Link Prediction',
                     'description': 'Score and rank currently unconnected vertex pairs according to a '
                                    'declared structural link-prediction measure.'},
 'graph_edit_distance_mcs': {'title': 'Graph Edit Distance and Maximum Common Subgraph',
                             'description': 'Given two graphs, compute either the minimum total cost of '
                                            'vertex/edge insertions, deletions, and substitutions '
                                            'transforming one graph into the other (graph edit distance), or '
                                            'a largest common induced or non-induced subgraph shared by both '
                                            '(maximum common subgraph).'},
 'network_alignment': {'title': 'Pairwise Network Alignment',
                       'description': 'Given two graphs and optional vertex-similarity priors, find a vertex '
                                      'mapping between them that maximizes conserved topology (and prior '
                                      'similarity, when supplied), either as a global one-to-one mapping or '
                                      'a local many-to-one set of high-scoring alignments.'},
 'triangle_counting_listing': {'title': 'Triangle Counting and Listing',
                               'description': 'Count all unordered triples of vertices connected by all '
                                              'three possible edges and optionally list the triples or their '
                                              'per-vertex and per-edge participation counts.'},
 'butterfly_counting_bipartite': {'title': 'Butterfly Counting and (alpha,beta)-Core Decomposition on '
                                           'Bipartite Graphs',
                                  'description': 'Given a bipartite graph, count butterflies (complete 2x2 '
                                                 'bicliques) globally and per vertex/edge, and optionally '
                                                 'compute maximal vertex sets satisfying separate left/right '
                                                 'thresholds. core_measure explicitly distinguishes '
                                                 'conventional degree-based (alpha,beta)-cores from the '
                                                 'butterfly-participation variant.'},
 'graphlet_counting': {'title': 'Graphlet Counting',
                       'description': 'Classify and count small connected induced subgraphs by their '
                                      'unlabeled isomorphism class, optionally including per-vertex orbit '
                                      'participation.'},
 'graph_motif_counting': {'title': 'Graph Motif Counting',
                          'description': 'Count occurrences of one or more supplied small structural '
                                         'patterns in a directed or undirected graph.'},
 'temporal_motif_mining': {'title': 'Temporal Motif Mining',
                           'description': 'Count occurrences of a small ordered edge pattern whose matched '
                                          'events occur in the required order within a bounded time window.'},
 'subgraph_isomorphism': {'title': 'Subgraph Isomorphism and Pattern Matching',
                          'description': 'Find injective mappings from the vertices of a query graph to a '
                                         'data graph that preserve required edges, direction, and requested '
                                         'attribute predicates.'},
 'frequent_subgraph_mining': {'title': 'Frequent Subgraph Mining',
                              'description': 'Given a collection of graphs, discover unique subgraph '
                                             'patterns appearing in at least a specified fraction of the '
                                             'collection.'},
 'single_graph_frequent_subgraph_mining': {'title': 'Frequent Subgraphs in One Labeled Graph',
                                           'description': 'Enumerate or count connected labeled patterns '
                                                          'meeting a declared minimum-image-support '
                                                          'threshold in one labeled host graph.'},
 'bipartite_matching_assignment': {'title': 'Bipartite Matching and Linear Assignment',
                                   'description': 'Given a bipartite graph, find a matching (a set of edges '
                                                  'with no shared endpoints) that is optimal under a '
                                                  'declared objective: maximum cardinality, maximum total '
                                                  'weight, or minimum total cost.'},
 'general_graph_weighted_matching': {'title': 'General-Graph Weighted Matching',
                                     'description': 'Find a matching of high total nonnegative edge weight '
                                                    'in an undirected graph without a bipartiteness '
                                                    'assumption.'},
 'maximal_independent_set': {'title': 'Maximal Independent Set',
                             'description': 'Find one independent vertex set that cannot be enlarged by '
                                            'adding any remaining vertex.'},
 'maximum_independent_set': {'title': 'Maximum Independent Set',
                             'description': 'Find an independent vertex set of maximum cardinality in a '
                                            'simple undirected graph.'},
 'minimum_vertex_cover': {'title': 'Minimum Vertex Cover',
                          'description': 'Find a smallest set of vertices touching every edge, or decide '
                                         'whether a cover of size at most k exists.'},
 'vertex_coloring': {'title': 'Vertex Coloring',
                     'description': 'Assign colors so vertices within a declared graph distance receive '
                                    'different colors.'},
 'entity_resolution_blocking': {'title': 'Graph-Based Entity Resolution and Rule-Based Blocking',
                                'description': 'Given a collection of candidate entity records and one or '
                                               'more declared blocking rules over record attributes, '
                                               'generate the reduced set of candidate record pairs worth '
                                               'comparing, and optionally confirm matches and merge them '
                                               'into resolved-entity clusters.'},
 'graph_coarsening': {'title': 'Graph Coarsening and Quotient Construction',
                      'description': 'Map every vertex to a nonempty coarse cluster and construct the '
                                     'weighted quotient graph with declared edge and feature aggregation.'},
 'induced_subgraph_ego_extraction': {'title': 'Induced Subgraph and Ego-Network Extraction',
                                     'description': 'Extract the graph induced by an explicit vertex set or '
                                                    'by vertices within a hop radius of declared seeds. '
                                                    'induced-subgraph extracts an induced graph on selected '
                                                    'vertices or an ego neighborhood around seeds. '
                                                    'query-subgraph in records also supports vertex-induced, '
                                                    'edge-induced and filtered-neighborhood extraction with '
                                                    'record selectors.'},
 'knn_graph_construction': {'title': 'k-Nearest-Neighbor Graph Construction',
                            'description': 'Construct a graph connecting each feature vector to its k '
                                           'nearest distinct input vectors under a declared distance '
                                           'metric.'},
 'spectral_graph_sparsification': {'title': 'Spectral Graph Sparsification',
                                   'description': 'Construct a sparse reweighted subgraph approximating the '
                                                  'quadratic form of a weighted undirected graph Laplacian.'},
 'neighborhood_sampling': {'title': 'Neighborhood Sampling',
                           'description': 'Sample multihop neighborhoods around seed vertices using declared '
                                          'fanouts and neighbor-selection probabilities.'},
 'random_walk_generation': {'title': 'Graph Random-Walk Generation',
                            'description': 'Generate vertex sequences sampled from a declared graph '
                                           'transition process.'},
 'graph_layout_force_directed': {'title': 'Force-Directed Graph Layout',
                                 'description': 'Given a graph, compute a position for every vertex in 2 or '
                                                '3 dimensions under a declared force model, so that '
                                                'connected vertices are pulled together and all vertices '
                                                'repel each other, producing a drawing that visually reveals '
                                                'clusters and hubs.'},
 'graph_laplacian_eigenpairs': {'title': 'Graph Laplacian Eigenpairs',
                                'description': 'Compute selected eigenpairs of the combinatorial or '
                                               'symmetric normalized Laplacian of a nonnegative undirected '
                                               'graph.'},
 'graph_signal_denoising': {'title': 'Graph Signal Denoising and Trend Filtering',
                            'description': 'Estimate a vertex signal from noisy observations using a '
                                           'declared graph-difference regularizer.'},
 'persistent_homology': {'title': 'Flag-Complex Persistent Homology',
                         'description': 'Compute persistence intervals over a declared prime field for the '
                                        'flag-complex filtration induced by nonnegative undirected edge '
                                        'filtration values.'},
 'graph_anomaly_detection': {'title': 'Graph Anomaly Detection',
                             'description': 'Rank graph entities by how strongly their declared structural '
                                            'or temporal features deviate from a specified normality '
                                            'reference.'},
 'null_model_significance_testing': {'title': 'Null-Model Significance Testing via Degree-Preserving Graph '
                                              'Randomization',
                                     'description': 'Given an observed graph and a declared structural '
                                                    "statistic, determine how unusual the statistic's "
                                                    'observed value is by comparing it against its '
                                                    'distribution over an ensemble of randomized graphs '
                                                    'sampled from a declared null model, typically one '
                                                    'preserving the degree sequence.'},
 'node_classification_regression': {'title': 'Node Classification and Regression',
                                    'description': 'Train or apply a graph model to predict categorical '
                                                   'labels or numerical targets for specified vertices.'},
 'graph_classification_regression': {'title': 'Graph Classification and Regression',
                                     'description': 'Predict one categorical label or numerical target for '
                                                    'each graph in a collection.'},
 'hypergraph_node_learning': {'title': 'Hypergraph Node Classification and Regression',
                              'description': 'Train or evaluate a declared hypergraph neural model to '
                                             'predict vertex labels or targets while preserving hyperedge '
                                             'incidence.'},
 'graph_condensation': {'title': 'Learned Graph Condensation',
                        'description': 'Learn a smaller synthetic attributed graph whose supervised training '
                                       'utility approximates that of the original training graph.'},
 'graph_based_geolocation': {'title': 'Graph-Based Geolocation',
                             'description': 'Infer geographic coordinates for unlocated vertices using '
                                            'declared graph propagation or supervised graph-learning '
                                            'models.'},
 'node_embedding': {'title': 'Node Embedding',
                    'description': 'Learn a vector for every vertex under a declared graph '
                                   'representation-learning objective.'},
 'knowledge_graph_embedding': {'title': 'Knowledge-Graph Embedding',
                               'description': 'Learn entity and relation representations from typed directed '
                                              'triples for relational link prediction.'}}
