#!/usr/bin/env python3
"""Reviewed source-to-problem mappings for the October 2026 research sweep.

This is declarative catalog data. Running it writes specs/configuration only;
catalog_sweep.py separately collects the referenced artifacts.
"""
import json
from acquire import ROOT, SOURCES, write_json
from define_new_problems import main as define_problems


def main():
    define_problems()
    folders = {int(p.name[:2]): p.name for p in ROOT.glob('[0-9][0-9]_*') if (p / 'problem.json').is_file()}
    publications, entries = {}, []

    def reuse(key, folder, paper_id):
        m = json.loads((ROOT / folders[folder] / 'papers' / paper_id / 'metadata.json').read_text())
        publications[key] = {k: m.get(k) for k in ['title', 'authors', 'year', 'venue', 'doi', 'publication_url', 'pdf_url']}
        publications[key]['role'] = m.get('paper_role', 'algorithm')

    reuse('gunrock', 38, '2017_gunrock_bfs')
    reuse('graphblast', 38, '2019_graphblast_bfs')
    reuse('gardenia', 38, '2017_gardenia_direction_bfs')
    reuse('pyg', 48, '2019_pyg_induced_subgraph')
    reuse('dgl', 48, '2019_dgl_node_subgraph')
    reuse('g2miner', 11, '2022_g2miner')
    publications['g2miner']['role'] = 'framework'
    publications['g2miner']['title'] = 'Efficient and Scalable Graph Pattern Mining on GPUs'
    publications['g2miner']['authors'] = ['Xuhao Chen', 'Arvind']

    def pub(key, title, year, url, pdf, authors=(), venue='Research preprint', role='algorithm', doi=None):
        publications[key] = dict(title=title, year=year, publication_url=url, pdf_url=pdf,
                                 authors=list(authors), venue=venue, role=role, doi=doi)

    def arxiv(key, title, year, id_, authors=(), **kwargs):
        pub(key, title, year, 'https://arxiv.org/abs/' + id_, 'https://arxiv.org/pdf/' + id_, authors, **kwargs)

    pub('hornet', 'Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs', 2018,
        'https://davidbader.net/publication/2018-bgbb/', 'https://davidbader.net/publication/2018-bgbb/2018-bgbb.pdf',
        ['Federico Busato', 'Oded Green', 'Nicola Bombieri', 'David A. Bader'], 'IEEE HPEC 2018', 'framework')
    pub('pygod', 'PyGOD: A Python Library for Graph Outlier Detection', 2024,
        'https://jmlr.org/papers/v25/23-0963.html', 'https://jmlr.org/papers/volume25/23-0963/23-0963.pdf',
        venue='Journal of Machine Learning Research 25(141)', role='framework')
    pub('greedy_matching', 'A GPU Algorithm for Greedy Graph Matching', 2012,
        'https://research-portal.uu.nl/en/publications/a-gpu-algorithm-for-greedy-graph-matching',
        'https://research-portal.uu.nl/ws/files/62547756/Algorithm.pdf',
        ['Bas O. Fagginger Auer', 'Rob H. Bisseling'], 'Facing the Multicore-Challenge II, LNCS 7174',
        doi='10.1007/978-3-642-30397-5_10')
    arxiv('hyspecpro', 'HySpecPro: Scalable Hypergraph Partitioning via Spectral Projection Optimization', 2026,
          '2607.00055', ['Rongjian Liang', 'Zhuo Feng', 'Haoxing Ren'])
    arxiv('blocked_fw', 'A Multi-Stage CUDA Kernel for Floyd-Warshall', 2010, '1001.4108', ['Ben Lund', 'Justin W. Smith'])
    pub('mg_mis', 'A Multi-GPU Algorithm for Computing Maximal Independent Sets in Large Graphs', 2025,
        'https://github.com/burtscher/MG-MIS', 'https://userweb.cs.txstate.edu/~mb92/papers/ics25.pdf',
        ['Anju Mongandampulath Akathoott', 'Benila Virgin Jerald Xavier', 'Martin Burtscher'], 'ACM ICS 2025')
    pub('cupy', 'CuPy: A NumPy-Compatible Library for NVIDIA GPU Calculations', 2017,
        'https://learningsys.github.io/nips17/schedule.html', 'https://learningsys.github.io/nips17/assets/papers/paper_16.pdf',
        ['Ryosuke Okuta', 'Yuya Unno', 'Daisuke Nishino', 'Shohei Hido', 'Crissman Loomis'],
        'LearningSys workshop at NIPS 2017', 'framework')
    pub('nn_descent', 'Fast k-NN Graph Construction by GPU based NN-Descent', 2021,
        'https://doi.org/10.1145/3459637.3482344', 'https://cmmlab.xmu.edu.cn/pubs/cikmwang2021.pdf',
        ['Hui Wang', 'Wanlei Zhao', 'Xiangxiang Zeng', 'Jianye Yang'], 'ACM CIKM 2021', doi='10.1145/3459637.3482344')
    arxiv('faiss', 'Billion-scale similarity search with GPUs', 2017, '1702.08734',
          ['Jeff Johnson', 'Matthijs Douze', 'Herve Jegou'], venue='IEEE Transactions on Big Data, published 2019')
    arxiv('hgnn', 'Hypergraph Neural Networks', 2018, '1809.09401', venue='AAAI 2019')
    pub('hypergcn', 'HyperGCN: A New Method of Training Graph Convolutional Networks on Hypergraphs', 2019,
        'https://papers.nips.cc/paper/2019/hash/1efa39bcaec6f3900149160693694536-Abstract.html',
        'https://papers.nips.cc/paper/2019/file/1efa39bcaec6f3900149160693694536-Paper.pdf', venue='NeurIPS 2019')
    arxiv('hnhn', 'HNHN: Hypergraph Networks with Hyperedge Neurons', 2020, '2006.12278')
    arxiv('dynamic_mis', 'Maximum Independent Set: Self-Training through Dynamic Programming', 2023,
          '2310.18672', ['Lorenzo Brusca', 'Lars C. P. M. Quaedvlieg', 'Stratis Skoulakis',
                         'Grigorios G. Chrysos', 'Volkan Cevher'], venue='NeurIPS 2023')
    pub('difusco', 'DIFUSCO: Graph-based Diffusion Solvers for Combinatorial Optimization', 2023,
        'https://papers.nips.cc/paper_files/paper/2023/hash/0ba520d93c3df592c83a611961314c98-Abstract-Conference.html',
        'https://papers.nips.cc/paper_files/paper/2023/file/0ba520d93c3df592c83a611961314c98-Paper-Conference.pdf',
        ['Zhiqing Sun', 'Yiming Yang'], 'NeurIPS 2023')
    pub('pcqo', 'Differentiable Quadratic Optimization For the Maximum Independent Set Problem', 2025,
        'https://proceedings.mlr.press/v267/alkhouri25a.html',
        'https://raw.githubusercontent.com/mlresearch/v267/main/assets/alkhouri25a/alkhouri25a.pdf',
        ['Ismail Alkhouri', 'Cedric Le Denmat', 'Yingjie Li', 'Cunxi Yu', 'Jia Liu', 'Rongrong Wang', 'Alvaro Velasquez'], 'ICML 2025')
    arxiv('ripser', 'GPU-Accelerated Computation of Vietoris-Rips Persistence Barcodes', 2020, '2003.07989',
          ['Simon Zhang', 'Mengbai Xiao', 'Hao Wang'], venue='arXiv, revised 2026')
    arxiv('pangolin', 'Pangolin: An Efficient and Flexible Graph Pattern Mining System on CPU and GPU', 2019,
          '1911.06969', ['Xuhao Chen', 'Roshan Dathathri', 'Gurbinder Gill', 'Keshav Pingali'], venue='PVLDB 2020', role='framework')
    arxiv('mvc_components', 'Faster Vertex Cover Algorithms on GPUs with Component-Aware Parallel Branching', 2025,
          '2512.18334', ['Hussein Amro', 'Basel Fakhri', 'Amer E. Mouawad', 'Izzat El Hajj'],
          venue='IEEE TPDS 37(2), 2026', doi='10.1109/TPDS.2025.3641049')
    arxiv('mvc_parallel', 'Parallel Vertex Cover Algorithms on GPUs', 2022, '2204.10402',
          ['Peter Yamout', 'Karim Barada', 'Adnan Jaljuli', 'Amer E. Mouawad', 'Izzat El Hajj'])
    arxiv('gcond', 'Graph Condensation for Graph Neural Networks', 2021, '2110.07580', venue='ICLR 2022')
    arxiv('doscond', 'Condensing Graphs via One-Step Gradient Matching', 2022, '2206.07746', venue='ACM KDD 2022')
    arxiv('gcdm', 'Graph Condensation via Receptive Field Distribution Matching', 2022, '2206.13697')
    pub('pygmtools', 'Pygmtools: A Python Graph Matching Toolkit', 2024,
        'https://jmlr.org/papers/v25/23-0572.html', 'https://jmlr.org/papers/volume25/23-0572/23-0572.pdf',
        venue='Journal of Machine Learning Research 25(33)', role='framework')

    def add(n, id_, algorithm, source, paths, publication=None, *, notes, gpu=None, fit='variant', constraints=(), docs=(), code_url=None, shortfall=None):
        entries.append(dict(problem_dir=folders[n], paper_id=id_, algorithm_name=algorithm,
                            source=source, entrypoints=paths, publication=publication, semantic_fit=fit,
                            notes=notes, gpu_scope=gpu or 'Inspected CUDA implementation; host orchestration and input conversion remain outside GPU kernels. No build or runtime validation performed.',
                            variant_constraints=list(constraints), documentation_urls=list(docs),
                            code_url=code_url, code_shortfall=shortfall))

    # cuGraph coverage uses the pinned C++ implementation, including APIs that
    # are not exposed through the current Python package. API pages are not papers.
    cg = [
        (7, 'core_number', 'Core-number peeling', 'cores/core_number_impl.cuh', 'Core numbers for a simple unweighted graph; degree convention and isolates need canonical conversion.'),
        (8, 'k_truss', 'Fixed-k truss extraction', 'community/k_truss_impl.cuh', 'Returns a fixed-k truss subgraph. Full edge trussness decomposition requires an additional driver.', 'building_block'),
        (10, 'triangle_count', 'Vertex triangle counting', 'community/triangle_count_impl.cuh', 'Vertex counts can be aggregated to a global count; no explicit triangle-listing API is supplied.'),
        (16, 'louvain', 'Louvain modularity optimization', 'community/louvain_impl.cuh', 'Weighted undirected modularity heuristic with a resolution parameter; no global optimum claim.'),
        (16, 'leiden', 'Leiden community detection', 'community/leiden_impl.cuh', 'Modularity-based Leiden implementation; verify API-supported objective and resolution before adapting.'),
        (16, 'ecg', 'Ensemble Clustering for Graphs', 'community/ecg_impl.cuh', 'Ensemble Louvain edge reweighting followed by partitioning; seed and ensemble size are algorithm inputs.'),
        (18, 'eigenvector', 'Eigenvector centrality', 'centrality/eigenvector_centrality_impl.cuh', 'Iterative centrality; report tolerance, convergence, direction and normalization.'),
        (18, 'katz', 'Katz centrality', 'centrality/katz_centrality_impl.cuh', 'Attenuated walk centrality with explicit alpha, beta and convergence requirements.'),
        (18, 'betweenness', 'Betweenness centrality', 'centrality/betweenness_centrality_impl.cuh', 'Exact or sampled source-based shortest-path centrality; normalization and sampling must be declared.'),
        (19, 'jaccard', 'Jaccard link scores', 'link_prediction/jaccard_impl.cuh', 'Score requested nonedges from neighborhood intersection/union; handle empty unions explicitly.'),
        (19, 'sorensen', 'Sorensen-Dice link scores', 'link_prediction/sorensen_impl.cuh', 'Score 2|N(u) intersect N(v)|/(deg(u)+deg(v)); this is a link-scoring variant, not SimRank.'),
        (19, 'overlap', 'Overlap-coefficient link scores', 'link_prediction/overlap_impl.cuh', 'Normalize intersection by the smaller degree; zero-degree convention must be declared.'),
        (19, 'cosine', 'Cosine neighborhood link scores', 'link_prediction/cosine_similarity_impl.cuh', 'Dot product of adjacency vectors divided by their norms; define zero-norm behavior.'),
        (21, 'personalized_pagerank', 'Personalized PageRank', 'link_analysis/pagerank_impl.cuh', 'Use a nonuniform personalization vector and explicit dangling-node treatment; unpersonalized PageRank is a separate configuration.'),
        (26, 'simple_cycles', 'Elementary cycle enumeration', 'components/simple_cycles_impl.cuh', 'Source contains GPU simple-cycle enumeration; adapters must enforce hop bounds and normalize cycle rotation/direction; path queries are not supplied.'),
        (31, 'hungarian', 'Dense Hungarian assignment', 'linear_assignment/legacy/hungarian.cu', 'Legacy CUDA weighted rectangular assignment, not a general-graph matching solver; check padding and infeasible-edge conventions.'),
        (35, 'wcc', 'Weakly connected components', 'components/weakly_connected_components_impl.cuh', 'Direction is ignored for weak connectivity; this is not strongly connected components.'),
        (35, 'scc', 'Strongly connected components', 'components/strongly_connected_components_impl.cuh', 'Directed mutual reachability; component labels are compared as partitions, not raw integers.'),
        (36, 'force_atlas2', 'ForceAtlas2 layout', 'layout/legacy/force_atlas2.cu', 'GPU force-directed layout; input positions, seed, iteration count and force parameters affect the result.'),
        (38, 'bfs', 'Breadth-first traversal', 'traversal/bfs_impl.cuh', 'Unweighted hop distances and predecessors from a specified source; optional direction optimization.'),
        (39, 'sssp', 'Single-source shortest paths', 'traversal/sssp_impl.cuh', 'Nonnegative weighted shortest paths; reject unsupported negative weights.'),
        (42, 'mis', 'Maximal independent set', 'components/mis_impl.cuh', 'A maximal set is inclusion-wise unextendable and does not imply maximum cardinality.'),
        (43, 'coloring', 'Vertex coloring', 'components/vertex_coloring_impl.cuh', 'Proper coloring; no minimum-color guarantee.'),
        (44, 'weighted_matching', 'Approximate weighted matching', 'community/approx_weighted_matching_impl.cuh', 'Symmetric loop-free graph and nonnegative edge weights; the routine is approximate, not an exact maximum-weight matching solver.'),
        (46, 'random_walks', 'GPU random walks', 'sampling/random_walks_impl.cuh', 'Use only the transition rule supported by the selected API; specify dead-end padding and seed.'),
        (47, 'neighbor_sampling', 'Neighbor sampling', 'sampling/neighbor_sampling_impl.cuh', 'Declare hop fanouts, with/without replacement, edge direction and seed.'),
        (48, 'induced_subgraph', 'Induced subgraph extraction', 'structure/induced_subgraph_impl.cuh', 'Retain exactly edges with both endpoints in the requested vertex set; preserve isolates and external ID mapping.'),
        (48, 'egonet', 'Ego-network extraction', 'community/egonet_impl.cuh', 'Radius and seed inclusion must follow the public API; output is an induced neighborhood graph.'),
        (62, 'quotient', 'Weighted graph coarsening', 'structure/coarsen_graph_impl.cuh', 'Supply a cluster assignment; quotient edges are aggregated on the GPU. Assignment generation is a separate stage.'),
    ]
    for row in cg:
        n, key, name, path, note, *fit = row
        add(n, '2026_cugraph_' + key, 'cuGraph ' + name, 'cugraph', ['cpp/src/' + path],
            notes=note + ' No associated GPU research paper was verified for this specific implementation; documentation is retained as documentation.',
            fit=fit[0] if fit else 'variant', docs=['https://docs.nvidia.com/cugraph/stable/api_docs/cugraph_cpp/'])

    hornet = [
        (7, 'kcore', 'K-core peeling', 'KCore/KCore.cu', 'Unweighted undirected core decomposition.'),
        (8, 'ktruss', 'K-truss peeling', 'KTruss/KTruss.cu', 'Triangle-support peeling; inspect fixed-k versus full-decomposition output before adapting.'),
        (10, 'triangles', 'Triangle counting', 'TriangleCounting/triangle.cu', 'Undirected simple-graph count; output normalization must account for the symmetric representation.'),
        (18, 'bc', 'Exact betweenness centrality', 'BetweennessCentrality/exact_bc.cu', 'All-source unweighted betweenness; map normalization and direction to the problem contract.'),
        (18, 'katz', 'Katz centrality', 'KatzCentrality/Katz.cu', 'Katz iteration with declared attenuation and stopping rule.'),
        (35, 'cc', 'Connected components', 'ConnectedComponents/CC.cu', 'Undirected connected components; arbitrary component identifiers.'),
        (38, 'bfs', 'Top-down BFS', 'BreadthFirstSearch/TopDown.cu', 'Unweighted breadth-first distances; this is a distinct Hornet implementation.'),
        (39, 'sssp', 'SSSP', 'ShortestPath/SSSP.cu', 'Weighted shortest paths under the supported nonnegative-weight configuration.'),
    ]
    for n, key, name, path, note in hornet:
        add(n, '2018_hornet_' + key, 'Hornet ' + name, 'hornet', ['hornetsnest/src/Static/' + path], 'hornet',
            notes=note + (' The inspected driver exposes maximum k and fixed-k peeling, not a complete per-edge trussness map; it remains a building block for problem 08.' if n == 8 else '') +
                  ' The associated PDF describes the Hornet GPU framework; it is not a separate paper for each routine.',
            fit='building_block' if n == 8 else 'variant')

    for n, key, path, note in [
        (7, 'kcore', 'include/gunrock/algorithms/kcore.hxx', 'Core decomposition for simple undirected graphs.'),
        (10, 'tc', 'include/gunrock/algorithms/tc.hxx', 'Triangle counting; listing is not supplied.'),
        (18, 'bc', 'include/gunrock/algorithms/bc.hxx', 'Unweighted Brandes-style centrality with explicit source aggregation.'),
        (21, 'ppr', 'include/gunrock/algorithms/ppr.hxx', 'Approximate seeded personalized PageRank, with explicit residual tolerance and seed convention.')]:
        add(n, '2017_gunrock_' + key, 'Gunrock ' + key, 'gunrock', [path], 'gunrock', notes=note + ' Paired with the Gunrock framework publication.')
    for n, key, note in [
        (10, 'tc', 'Triangle count expressed as sparse linear algebra.'),
        (18, 'pr', 'Global PageRank centrality, not arbitrary seeded local-community output.'),
        (35, 'cc', 'Undirected component propagation using GPU GraphBLAS primitives.')]:
        add(n, '2019_graphblast_' + key, 'GraphBLAST ' + key, 'graphblast', ['graphblas/algorithm/' + key + '.hpp'],
            'graphblast', notes=note + ' This is a framework-paper pairing.')
    add(35, '2017_gunrock_cc', 'Gunrock connected components', 'gunrock_legacy',
        ['gunrock/app/cc/cc_enactor.cuh'], 'gunrock', notes='Legacy Gunrock connected-components implementation for the undirected/weak-connectivity variant.')
    add(21, '2019_graphblast_seeded_diffusion', 'GraphBLAST seeded residual-push PageRank', 'graphblast',
        ['graphblas/algorithm/lgc.hpp'], 'graphblast',
        notes='Single-seed approximate PageRank vector from GPU residual pushing. The source uses a lazy walk: '
              'to match ordinary-walk restart probability r, use upstream alpha=r/(2-r). '
              'Restrict to undirected graphs with positive degree, report approximation and iteration termination, '
              'and check residual/missing mass before claiming the requested tolerance. The routine alone does not return a local community.',
        constraints=['single seed', 'undirected positive-degree graph', 'approximate mode', 'lazy-walk restart conversion required'])

    for key in ['dominant', 'anomalydae', 'cola']:
        add(20, '2024_pygod_' + key, 'PyGOD ' + key.upper(), 'pygod',
            ['pygod/detector/' + key + '.py', 'pygod/nn/' + key + '.py'], 'pygod',
            notes='Attributed-graph node anomaly scores. ' +
                  ('This CoLA library variant uses neighbor sampling instead of the original paper random walks. ' if key == 'cola' else '') +
                  'GPU selection is explicit: the default gpu=-1 uses CPU. The PDF is the PyGOD framework paper, shared by three distinct models.',
            gpu='PyTorch/PyG tensor operations on CUDA when gpu>=0; preprocessing and sampling can include CPU stages.',
            constraints=['node anomaly mode', 'numeric vertex features', 'gpu must be explicitly enabled'])
    for key, path, publication in [('g2miner_enumeration', 'src/motif/gpu_base.cu', 'g2miner'),
                                    ('g2miner_formula', 'src/motif/gpu_formula.cu', 'g2miner'),
                                    ('pangolin', 'src/pangolin/motif/base.cu', 'pangolin')]:
        add(12, '2022_' + key, key + ' induced graphlets', 'graphminer', [path], publication,
            notes='Connected vertex-induced graphlet class counts for supported sizes (3 and 4). No per-vertex orbit counts are supplied; request include_orbit_counts=false.',
            constraints=['connected undirected graphlets', '3 or 4 vertices', 'no orbit counts'])

    for key in ['rrwm', 'sm', 'ipfp']:
        add(25, '2024_pygmtools_' + key, 'pygmtools ' + key.upper(), 'pygmtools',
            ['pygmtools/classic_solvers.py', 'pygmtools/pytorch_backend.py'], 'pygmtools',
            notes='Quadratic graph matching using an explicit node/edge affinity tensor. Different solver entrypoints share the same backend file. '
                  'Discretization can use a CPU Hungarian step; an affinity definition and a mapping adapter are required. This is network alignment, not a certified GED solver.',
            gpu='PyTorch solver iterations can run on CUDA; affinity preparation and Hungarian discretization may use CPU.',
            constraints=['one-to-one global matching', 'caller-supplied affinity', 'hybrid GPU/CPU pipeline'])
    add(40, '2010_blocked_cuda_floyd_warshall', 'Blocked CUDA Floyd-Warshall (Bojanowski implementation)',
        'apsp_blocked_lic', ['lib/cuda/cuda_apsp.cu'], 'blocked_fw',
        notes='Public MIT-licensed third-party implementation explicitly based on Lund and Smith. It is not represented as the paper authors original artifact. '
              'Dense integer-distance APSP; check infinity sentinel, overflow and block-size assumptions; selected source/destination pairs are extracted from the full matrix.',
        constraints=['dense distance matrix', 'integer weights', 'no negative cycles', 'adapter must check numeric range'])
    add(42, '2025_mg_mis', 'MG-MIS', 'mg_mis', ['MG-MIS_10.cu'], 'mg_mis',
        notes='Multi-GPU maximal independent set for large simple undirected graphs. It does not solve maximum independent set.',
        gpu='CUDA multi-device implementation; device count and peer communication are deployment requirements.')
    add(44, '2012_torch_cluster_greedy_matching', 'PyTorch Cluster weighted greedy matching', 'torch_cluster',
        ['torch_cluster/graclus.py', 'csrc/cuda/graclus_cuda.cu'], 'greedy_matching',
        notes='CUDA randomized red/blue greedy matching from the paper cited by upstream. Cluster IDs encode matched pairs or singletons; select the weighted mode and reconstruct pair endpoints.',
        constraints=['undirected symmetric edges', 'nonnegative weights', 'approximate matching', 'explicit CUDA tensors'])
    add(44, '2012_dgl_greedy_matching', 'DGL weighted neighbor matching', 'dgl',
        ['python/dgl/geometry/edge_coarsening.py', 'src/geometry/cuda/edge_coarsening_impl.cu'], 'greedy_matching',
        notes='Independent DGL CUDA implementation of the same Auer-Bisseling greedy matching publication used by PyTorch Cluster. Pair/singleton cluster IDs require output conversion.',
        constraints=['bidirected graph', 'nonnegative weights', 'approximate matching'])
    add(54, '2026_hyspecpro', 'HySpecPro', 'hyspecpro', ['HySpecPro.py', 'helper.py'], 'hyspecpro',
        notes='GPU spectral-projection hypergraph bipartitioning. The public driver supports two-way partitioning; do not claim arbitrary k-way support or exact optimization.',
        gpu='PyTorch sparse and dense optimization on CUDA; Python orchestration and input loading remain on CPU.',
        constraints=['two-way hypergraph partitioning', 'declared imbalance bound', 'heuristic cut objective'])
    add(54, '2026_fastpartitioner', 'FastPartitioner GPU hypergraph refinement', 'fastpartitioner',
        ['CN/gpu_partition.cu', 'TV/gpu_partition.cu'],
        notes='CUDA cut-net/connectivity refinement with CPU initialization and external dependencies. An associated research PDF was not verified; retained as a source-and-documentation record.',
        gpu='Hybrid CPU partition initialization and GPU refinement.')

    add(61, '2026_nvgraph_widest_path', 'nvGRAPH max-min widest path', 'nvgraph', ['cpp/src/widest_path.cu'],
        notes='Archived NVIDIA nvGRAPH source implements max-min path relaxation. The CUDA library manual documents the operation but is not a research paper.',
        docs=['https://docs.nvidia.com/cuda/archive/9.1/pdf/nvGRAPH_Library.pdf'])
    add(62, '2026_nvgraph_contraction', 'nvGRAPH graph contraction', 'nvgraph',
        ['cpp/src/graph_contraction/contraction_csr_sum.cu', 'cpp/src/graph_contraction/contraction_mv_float_sum.cu'],
        notes='GPU CSR quotient and vertex-value aggregation for a supplied assignment. Sum-reduction mode matches the contract; other semirings are different variants.',
        docs=['https://docs.nvidia.com/cuda/archive/9.1/pdf/nvGRAPH_Library.pdf'])
    add(62, '2019_pyg_average_pool', 'PyG quotient construction with average feature pooling', 'pyg',
        ['torch_geometric/nn/pool/avg_pool.py', 'torch_geometric/nn/pool/pool.py'], 'pyg',
        notes='Uses a supplied assignment and tensor scatter/coalesce to form a pooled graph. Select mean feature aggregation and drop internal self-loops to match upstream behavior; cluster assignment generation is separate.',
        gpu='PyTorch scatter/coalesce operations on CUDA when graph tensors are CUDA-resident.',
        constraints=['feature_reduction=mean', 'self_loop_policy=drop'])
    for key, name, path in [('lanczos', 'Sparse Lanczos eigsh', 'cupyx/scipy/sparse/linalg/_eigen.py'),
                             ('lobpcg', 'Block LOBPCG', 'cupyx/scipy/sparse/linalg/_lobpcg.py'),
                             ('dense_eigh', 'Dense Hermitian eigensolver', 'cupy/linalg/_eigenvalue.py')]:
        add(63, '2017_cupy_' + key, 'CuPy ' + name, 'cupy', [path], 'cupy',
            notes='Apply the upstream eigensolver to the explicitly constructed symmetric graph Laplacian. '
                  'These are three numerical algorithms sharing the CuPy framework paper, not three graph-specific publications. '
                  'Laplacian assembly and canonical output conversion are adapter requirements; verify residuals and nullspace multiplicity.',
            gpu='CUDA/CuPy matrix operations and device eigensolver routines; iterative control is host-driven.',
            constraints=['real symmetric Laplacian', 'algorithm-specific k and convergence limits'])
    add(64, '2021_cuvs_nn_descent', 'cuVS GPU NN-Descent', 'cuvs',
        ['cpp/src/neighbors/nn_descent.cu', 'cpp/src/neighbors/detail/nn_descent.cuh'], 'nn_descent',
        notes='Approximate kNN graph construction; recall must be measured. The cuVS implementation cites GPU NN-Descent. CAGRA navigation-graph pruning is not treated as an exact kNN output.',
        constraints=['approximate search', 'supported distance metrics only'])
    add(64, '2017_faiss_flat_knn', 'Faiss GPU exhaustive nearest neighbors', 'faiss',
        ['faiss/gpu/GpuIndexFlat.cu', 'faiss/gpu/impl/FlatIndex.cu'], 'faiss',
        notes='Query every input vector against a GPU flat index and remove its own ID. Distinct vectors with identical values remain valid neighbors. k+1 retrieval and tie handling must preserve k non-self outputs.',
        constraints=['exact flat index', 'squared Euclidean distance', 'query every input vector'])
    add(64, '2019_torch_cluster_knn', 'PyTorch Cluster kNN graph', 'torch_cluster',
        ['torch_cluster/knn.py', 'csrc/cuda/knn_cuda.cu'], 'pyg',
        notes='CUDA nearest-neighbor graph operator used by the PyG ecosystem. Respect the pinned kernel k limit, batch partitioning, distance convention and self-loop flag.',
        gpu='CUDA kNN kernel selected for CUDA-resident tensors.', constraints=['supported k bound', 'explicit distance convention'])
    for key in ['hgnn', 'hypergcn', 'hnhn']:
        add(65, '2020_dhg_' + key, 'DeepHypergraph ' + key.upper(), 'dhg',
            ['dhg/models/hypergraphs/' + key + '.py', 'dhg/structure/hypergraphs/hypergraph.py'], key,
            notes='Hypergraph node-learning model on native incidence data. The model-specific propagation or mediator expansion is explicit; choose CUDA for both model and hypergraph tensors.',
            gpu='PyTorch sparse/dense CUDA operations; CPU dataset preparation and training orchestration.',
            constraints=['explicit CUDA device', 'node classification configuration'])
    add(66, '2023_dynamic_mis', 'Dynamic programming self-trained MIS', 'dynamic_mis',
        ['MIS/model.py', 'MIS/recursive_tree.py'], 'dynamic_mis',
        notes='Learned heuristic for maximum-cardinality independent sets. CPU graph recursion calls a CUDA neural comparator. No optimality certificate is supplied.',
        gpu='Hybrid NetworkX/NumPy recursion with PyTorch CUDA neural inference.', constraints=['heuristic mode', 'model checkpoint/training required'])
    add(66, '2023_difusco_mis', 'DIFUSCO independent set', 'difusco',
        ['difusco/pl_mis_model.py', 'difusco/utils/mis_utils.py'], 'difusco',
        notes='CUDA diffusion model followed by CPU/NumPy feasibility decoding. Report heuristic quality and checkpoint identity; feasibility does not certify optimality.',
        gpu='GPU neural diffusion; CPU final decoding.', constraints=['heuristic mode', 'checkpoint required'])
    add(66, '2025_pcqo_reference', 'pCQO-MIS', None, [], 'pcqo',
        notes='The ICML paper links a refactor branch that was unavailable at collection time. The current repository did not expose a top-level license; source redistribution is blocked and this record does not count as a local pair.',
        gpu='Paper describes GPU tensor optimization; no local implementation was retained.',
        code_url='https://github.com/ledenmat/pCQO-mis-benchmark',
        shortfall='Published refactor branch unavailable; default-branch snapshot has no detected top-level license.')
    add(67, '2020_ripserplusplus', 'Ripser++', 'ripserplusplus', ['ripserplusplus/ripser++.cu'], 'ripser',
        notes='GPU-accelerated Vietoris-Rips/flag persistence. Use supported sparse or distance-matrix input with absent edges represented correctly; verify supported coefficient field and cutoff semantics.',
        gpu='GPU filtration/apparent-pair stages with CPU residual reduction; this is a hybrid algorithm.',
        constraints=['supported field and homology dimension', 'explicit sparse missing-edge semantics'])
    for key, path, publication in [('graphminer', 'src/fsm/gpu_base.cu', 'g2miner'), ('pangolin', 'src/pangolin/fsm/base.cu', 'pangolin')]:
        add(68, '2022_' + key + '_mni', key + ' single-graph MNI mining', 'graphminer', [path], publication,
            notes='Labeled single-host-graph domain/MNI support. The upstream driver reports the number of frequent patterns; pattern listing and unsupported size bounds must not be claimed. This does not implement graph-database transaction support in problem 14.',
            constraints=['single labeled host graph', 'count output', 'non-induced edge embeddings', 'inspect compiled pattern-size bound'])
    add(69, '2023_dynamic_mvc', 'Self-trained neural vertex-cover heuristic', 'dynamic_mis',
        ['MVC/model.py', 'MVC/recursion_tree.py'], 'dynamic_mis',
        notes='The authors repository includes a separate MVC adaptation. It combines CPU branching with GPU neural scoring; minimum size is not certified.',
        gpu='Hybrid NumPy/NetworkX graph transformations and PyTorch CUDA inference.', constraints=['heuristic mode'])
    add(69, '2026_component_aware_mvc', 'Component-aware GPU vertex cover', 'mvc_components', ['src/main.cu'], 'mvc_components',
        notes='Author implementation of exact and parameterized vertex-cover search with component-aware branching. The CLI reports optimum size/decision; a witness set is not guaranteed by its current interface.',
        constraints=['simple undirected graph', 'size/decision output', 'timeout must remain unknown'])
    add(69, '2022_parallel_mvc_reference', 'Parallel GPU vertex cover', None, [], 'mvc_parallel',
        notes='The author source repository is public but has no detected top-level license. Retained as a publication/source reference without redistributing a new snapshot.',
        gpu='Paper describes CUDA search; source not retained because license terms were not detected.',
        code_url='https://github.com/pky00/Parallel-Vertex-Cover-Algorithms-on-GPUs',
        shortfall='No detected top-level license; new source redistribution blocked.')
    for key in ['gcond', 'doscond', 'gcdm']:
        add(70, '2022_graphslim_' + key, 'GraphSlim ' + key.upper(), 'graphslim',
            ['graphslim/condensation/' + key + '.py'], key,
            notes='GPU graph condensation implementation. ' +
                  ('GraphSlim adapts one-step gradient matching to its node-learning pipeline; this is not a claim of reproducing every original graph-classification experiment. ' if key == 'doscond' else '') +
                  'Synthetic graph utility must be measured under a fixed train/validation/test protocol. GraphSlim CPU sparsification routines are not GPU spectral sparsifiers.',
            gpu='PyTorch CUDA optimization when the device is configured; preprocessing and evaluation orchestration may use CPU.')

    gaps = {
        4: 'Only cuQC is currently paired with verified local GPU source and paper; no two further matching GPU quasi-clique artifacts were verified.',
        5: 'The existing CDS source reference lacks a detected redistribution license. Densest-subgraph optimization is not interchangeable with k-core peeling.',
        6: 'No licensed public GPU implementation matching fixed-cardinality densest-k-subgraph was verified. Clique and unrestricted density objectives do not satisfy this contract.',
        8: 'Fixed-k truss extraction is not a complete trussness decomposition; library building blocks and the available decomposition artifacts are listed separately.',
        9: 'MBE-GPU source references are present but redistribution license terms were not detected; cuMBE remains a separate artifact.',
        14: 'The contract uses support across a collection of graph transactions. GraphMiner/Pangolin use single-graph MNI support and are cataloged separately in problem 68.',
        15: 'Everest and Mayura remain the two verified local temporal motif artifacts; static motif counters do not honor temporal ordering/window semantics.',
        17: 'The current contract is k-clique percolation. Generic overlapping community models and ordinary Louvain/Leiden are not equivalent; no matching public GPU artifact was verified.',
        19: 'cuGraph provides verified GPU similarity/link-score code, but no associated research PDF was verified for these library implementations. Documentation does not count as a research paper.',
        21: 'Seeded diffusion implementations are included where their objective matches PPR; a community sweep or an unseeded PageRank routine cannot substitute for the requested vector.',
        22: 'Some older GPU max-flow source references lack a detected license or public source release; their publication records remain explicit.',
        23: 'Some butterfly-counting papers lack a verified public GPU artifact; rectangle kernels require inspection of bipartite and counting semantics before they qualify.',
        24: 'Graph matching/alignment optimizes a different objective from certified GED/MCS. Public fast-GED source exists in the older workspace; license and semantic review remain explicit.',
        26: 'cuGraph simple cycles is documented, but no associated research PDF was verified; cycle-only routines do not implement all bounded-path modes.',
        27: 'Ordinary terminal Steiner tree handles only singleton groups, and circuit-specific routing does not establish unrestricted group Steiner support.',
        29: 'No new verified GPU SimRank artifact was found. Jaccard, cosine and learned embeddings do not solve the SimRank fixed-point objective.',
        30: 'Public GPU partitioning references were reviewed, but a new complete licensed code-and-paper trio was not verified. Hypergraph partitioning and unconstrained modularity are distinct problems.',
        31: 'Weighted dense assignment and unweighted bipartite cardinality matching are explicit variants; the cuGraph legacy implementation has documentation but no paired GPU research PDF.',
        32: 'GraphB+ and ECL-SGB source availability is restored where licensed; fewer than three independent implementation records have a verified local paper.',
        33: 'GDlog supplies GPU transitive-closure evaluation. Paper-only references remain incomplete; repeated BFS building blocks are not recorded as a fabricated new upstream algorithm.',
        34: 'HyperBlocker is a real GPU blocking artifact, but no license was detected for redistribution of a new snapshot. Similarity search alone is not the full entity-resolution blocking contract.',
        36: 'GPU ForceAtlas2 implementations are available; the library-only cuGraph entry has no paired GPU research paper.',
        37: 'No matching GPU end-to-end degree-preserving null-ensemble significance artifact was verified. R-MAT generators, random walks and independent edge sampling do not preserve the required degree sequence.',
        45: 'cuGraph has CUDA topological levels, but no paired research PDF was verified. DGL topological traversal falls back to CPU, and TopoGPU solves a restricted image-derived DAG.',
        49: 'PPR/diffusion kernels omit the required seed-containing conductance sweep and community result. They remain building blocks, not complete local-community algorithms.',
        55: 'dyGRASS incremental and decremental variants require an initial sparsifier. No third licensed GPU source-and-paper pair was verified; GraphSlim sparsification uses CPU NetworKit.',
        57: 'The temporal path papers were reviewed, but no matching public GPU source release was verified. Static SSSP cannot replace time-respecting earliest-arrival/fastest-path semantics.',
        58: 'G-PathGen has a research PDF but no verified public source release. Circuit-specific bounded path analysis and CPPR are different/restricted tasks.',
        59: 'No complete matching GPU graph-signal denoising solver was verified. Sparse fused-lasso primitives and learned node classifiers do not establish the specified denoising objective.',
        60: 'Gunrock geolocation and HB-Geo are paired. GT-Geo source is available but its associated publisher PDF could not be collected from a verified open source.',
        61: 'The archived nvGRAPH widest-path implementation is local; its manual is documentation, so the research-paper target remains open.',
        62: 'GPU quotient construction is available in cuGraph, nvGRAPH and PyG. Only PyG currently has a paired framework PDF; supplied assignment and clustering generation are separate stages.',
        66: 'Dynamic-MIS and DIFUSCO are paired heuristic implementations. pCQO has a paper but its referenced branch/license availability prevents a new redistributable source snapshot.',
        67: 'Ripser++ is a verified hybrid GPU artifact. CPU Ripser/GUDHI and image-only persistence routines do not create two additional matching GPU pairs.',
        68: 'Two upstream GPU MNI mining implementations are included. Their count-only interfaces and compiled size limits remain explicit; transaction-support mining is separate.',
        69: 'Two eligible implementations are collected. The older parallel vertex-cover repository has no detected license and is retained as a reference only.',
    }
    exclusions = [
        dict(source='https://github.com/HPCGraphAnalysis/CMGraph', decision='Placeholder repository contains README/LICENSE but no algorithm implementation; not counted as an artifact.'),
        dict(source='https://github.com/Emory-Melody/GraphSlim', decision='Graph condensation uses GPU tensor operations; spectral/structural sparsification wrappers using NetworKit remain CPU and are excluded from GPU sparsification counts.'),
        dict(source='https://github.com/dmlc/dgl', decision='Topological traversal has CPU execution paths; CUDA availability elsewhere in DGL does not make this a GPU topological-sort artifact.'),
        dict(source='https://github.com/chenxuhao/GraphMiner', decision='Single-graph MNI support is not transaction support across a graph database.'),
        dict(source='https://github.com/miki998/GyRAPH', decision='Repository returned HTTP 404 during verification.'),
        dict(source='https://github.com/dannygar/apsp', decision='No detected top-level license; used the separately licensed MTB90 blocked-Floyd-Warshall implementation, with its actual provenance.'),
    ]
    coverage = {}
    for n, folder in folders.items():
        coverage[folder] = dict(method='Problem-contract audit against pinned library implementations, existing author artifacts and targeted publication/repository searches.',
                                sources_reviewed=sorted({r['source'] for r in entries if r['problem_dir'] == folder and r['source']}),
                                shortfall=gaps.get(n, 'Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.'),
                                notes='A matching input variant can qualify without supporting every optional mode. Missing canonical adapters and absent runtime validation remain separate from research collection eligibility.')
    libraries = []
    for p in sorted(SOURCES.glob('*.json')):
        m = json.loads(p.read_text())
        related = [e for e in entries if e.get('source') == p.stem]
        libraries.append(dict(key=p.stem, source_url=m['source_url'], commit=m.get('commit'),
                              source_manifest='../_sources/' + p.name,
                              mapped_problems=sorted({e['problem_dir'] for e in related}),
                              mapping_status='mapped_to_reviewed_records' if related else 'existing_artifact_or_inspected_candidate',
                              build_status='not_tested', runtime_status='not_tested'))
    config = dict(research_cutoff='2026-10-09', search_exhaustive=False,
                  source_policy='Pinned upstream source only, with license availability recorded. No invented algorithm implementations or papers.',
                  pair_policy='A qualifying GPU implementation variant plus a locally parsed research PDF. Shared framework papers are allowed and identified; documentation is not a paper.',
                  publications=publications, entries=entries, coverage=coverage, libraries=libraries,
                  excluded_candidates=exclusions,
                  search_topics=['cuGraph C++ algorithm API and implementation inventory', 'GPU graph libraries Gunrock GraphBLAST Hornet GARDENIA nvGRAPH libgrape',
                                 'GPU graph learning PyG DGL PyGOD DeepHypergraph graph matching GraphSlim',
                                 'GPU hypergraph partitioning HySpecPro gHyPart HGNN-Part',
                                 'GPU maximum independent set and minimum vertex cover author artifacts',
                                 'GPU temporal paths topological sorting local community detection graph signal denoising',
                                 'GPU spectral sparsification critical-path enumeration graph geolocation',
                                 'GPU all-pairs shortest paths blocked Floyd-Warshall',
                                 'GPU graphlet mining transaction-support versus MNI support',
                                 'GPU nearest-neighbor graph construction cuVS Faiss PyTorch Cluster',
                                 'GPU persistent homology Ripser++ and graph Laplacian eigensolvers'])
    write_json(ROOT / '_collection/sweep_additions_2026_10_09.json', config)
    print('Defined', len(entries), 'new implementation/research records and', 10, 'new problem statements.')


if __name__ == '__main__':
    main()
