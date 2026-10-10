"""Declared possible output ports; conditional availability is checked at runtime."""

from .exceptions import GraphMineError

OUTPUT_PORTS = {
    "node-lookup": {"rows": "table", "count": "scalar", "vertices": "vertex_set"},
    "edge-filter": {
        "rows": "table",
        "count": "scalar",
        "edges": "edge_ids",
        "vertices": "vertex_set",
    },
    "neighbors": {"rows": "table", "count": "scalar", "vertices": "vertex_set"},
    "common-neighbors": {"rows": "table", "count": "scalar", "vertices": "vertex_set"},
    "query-paths": {
        "rows": "table",
        "count": "scalar",
        "vertices": "vertex_set",
        "edges": "edge_ids",
    },
    "graph-aggregate": {"rows": "table", "count": "scalar", "scores": "vertex_scores"},
    "query-subgraph": {"graph": "graph", "vertices": "vertex_set", "edges": "edge_ids"},
    "graph-edit-distance": {
        "distance": "rational_scalar",
        "mapping": "cross_graph_mapping",
        "edits": "table",
    },
    "maximum-common-subgraph": {
        "graph": "graph",
        "mapping": "cross_graph_mapping",
        "size": "scalar",
    },
    "frequent-subgraphs": {"patterns": "pattern_collection", "count": "scalar"},
    "single-graph-frequent-subgraphs": {
        "patterns": "pattern_collection",
        "count": "scalar",
    },
    "force-directed-layout": {"positions": "vertex_positions"},
    "influence-maximization": {"vertices": "vertex_set", "spread": "scalar"},
    "spectral-sparsification": {"graph": "graph"},
    "network-alignment": {"mapping": "cross_graph_mapping"},
    "graph-anomalies": {"ranking": "entity_ranking"},
    "maximal-bicliques": {"bicliques": "bipartite_groups"},
    "butterfly-counting": {
        "count": "scalar",
        "scores": "vertex_scores",
        "edges": "edge_scores",
        "cores": "vertex_groups",
    },
    "bipartite-matching": {"edges": "edge_set"},
    "pagerank": {"scores": "vertex_scores"},
    "personalized-pagerank": {"scores": "vertex_scores"},
    "betweenness-centrality": {"scores": "vertex_scores"},
    "degree-centrality": {"scores": "vertex_scores"},
    "link-prediction": {"pairs": "table"},
    "knn-graph": {"graph": "graph", "neighbors": "neighbor_lists"},
    "graph-coarsening": {"graph": "graph", "mapping": "vertex_coarsening"},
    "densest-subgraph": {"vertices": "vertex_set"},
    "densest-k-subgraph": {"vertices": "vertex_set"},
    "quasi-cliques": {"groups": "vertex_groups"},
    "entity-resolution": {
        "candidates": "record_pair_collection",
        "clusters": "vertex_partition",
    },
    "bounded-paths-cycles": {"sequences": "edge_sequence_collection"},
    "hypergraph-partitioning": {"partition": "vertex_partition"},
    "seeded-local-community": {"vertices": "vertex_set"},
    "null-model-significance": {"samples": "numeric_sample"},
    "maximum-independent-set": {"vertices": "vertex_set"},
    "minimum-vertex-cover": {"vertices": "vertex_set"},
    "weighted-matching": {"edges": "edge_set"},
    "max-flow-min-cut": {"value": "scalar", "vertices": "vertex_set"},
    "community-detection": {"groups": "vertex_groups", "partition": "vertex_partition"},
    "balanced-partitioning": {
        "groups": "vertex_groups",
        "partition": "vertex_partition",
    },
    "signed-balance": {"partition": "vertex_partition"},
    "widest-paths": {"paths": "widest_path_tree"},
    "top-k-critical-paths": {"paths": "path_set"},
    "subgraph-isomorphism": {"matches": "vertex_mappings"},
    "motif-counting": {"counts": "table", "instances": "motif_instances"},
    "graphlet-counting": {"counts": "table", "instances": "graphlet_instances"},
    "random-walks": {"walks": "walk_sample"},
    "neighborhood-sampling": {"edges": "edge_sample", "vertices": "vertex_set"},
    "simrank": {"pairs": "pair_scores"},
    "laplacian-eigenpairs": {"eigenpairs": "eigenpairs"},
    "graph-signal-denoising": {"signal": "vertex_signal"},
    "group-steiner-tree": {"vertices": "vertex_set", "edges": "edge_set"},
    "connected-components": {"groups": "vertex_groups"},
    "biconnected-components": {
        "groups": "vertex_groups",
        "vertices": "vertex_set",
        "edges": "edge_set",
    },
    "k-core": {"scores": "vertex_scores", "vertices": "vertex_set"},
    "k-truss": {"edges": "edge_set"},
    "maximal-cliques": {"groups": "vertex_groups"},
    "maximum-clique": {"groups": "vertex_groups", "vertices": "vertex_set"},
    "k-cliques": {"groups": "vertex_groups", "count": "scalar"},
    "triangle-counting": {"count": "scalar", "groups": "vertex_groups"},
    "overlapping-communities": {"groups": "vertex_groups"},
    "maximal-independent-set": {"vertices": "vertex_set"},
    "vertex-coloring": {"scores": "vertex_scores"},
    "temporal-paths": {"paths": "temporal_path_table"},
    "temporal-motifs": {"instances": "temporal_occurrence_collection"},
    "persistent-homology": {"intervals": "persistence_intervals"},
    "breadth-first-search": {"vertices": "vertex_set", "distances": "table"},
    "single-source-shortest-paths": {"distances": "vertex_scores"},
    "many-source-shortest-paths": {"distances": "table"},
    "spanning-tree-forest": {"edges": "edge_set", "vertices": "vertex_set"},
    "topological-sort": {"vertices": "vertex_set"},
    "induced-subgraph": {"graph": "graph", "vertices": "vertex_set"},
    "transitive-closure": {"pairs": "table"},
}


def validate_ports(operation, ports):
    declared = OUTPUT_PORTS.get(operation, {})
    for name, value in ports.items():
        if name not in declared or value.get("type") != declared[name]:
            raise GraphMineError(
                f"Undeclared or mistyped output port: {operation}.{name}"
            )
        if "value" not in value or type(value.get("complete")) is not bool:
            raise GraphMineError(f"Output port needs a value and completeness: {name}")
