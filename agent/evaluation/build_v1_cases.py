from __future__ import annotations

import json
from pathlib import Path


DOMAINS = [
    ("general", "network", "vertices"),
    ("fraud_detection", "transaction network", "accounts"),
    ("bioinformatics", "protein interaction network", "proteins"),
    ("cybersecurity", "host communication network", "hosts"),
    ("social_networks", "social network", "people"),
    ("recommendation_ecommerce", "customer-product network", "customers"),
    ("knowledge_graphs", "knowledge graph", "entities"),
    ("communications_infrastructure", "router topology", "routers"),
    ("transportation_mobility", "transport network", "stations"),
]


OPERATIONS = [
    {
        "problem_id": "maximal_clique_enumeration",
        "operation_id": "maximal-cliques",
        "queries": [
            "Enumerate every inclusion-maximal fully connected group of {entities} in this {network}.",
            "List all complete {entities} groups that cannot be extended with another mutually connected member.",
            "Find every maximal clique in the {network}; do not confuse maximal with largest.",
        ],
    },
    {
        "problem_id": "maximum_clique",
        "operation_id": "maximum-clique",
        "queries": [
            "Find one largest fully connected set of {entities} in the {network}.",
            "What is the maximum clique in this {network}? I need the globally largest complete group.",
            "Return the largest pairwise-connected {entities} group, not every maximal group.",
        ],
    },
    {
        "problem_id": "k_clique_counting_enumeration",
        "operation_id": "k-cliques",
        "queries": [
            "Count all fully connected groups of exactly four {entities} in the {network}.",
            "How many 4-cliques does this {network} contain?",
            "Measure the number of complete four-member {entities} groups.",
        ],
        "parameters": {"k": 4},
    },
    {
        "problem_id": "quasi_clique_mining",
        "operation_id": "quasi-cliques",
        "queries": [
            "Find near-complete groups of at least five {entities} where each member reaches 80 percent of the others.",
            "Mine quasi-cliques in the {network} with minimum size 5 and degree ratio 0.8.",
            "Return dense five-or-more-member {entities} groups using an 80% minimum internal-degree threshold.",
        ],
        "parameters": {"minimum_size": 5, "minimum_degree_ratio": 0.8},
    },
    {
        "problem_id": "k_core_decomposition",
        "operation_id": "k-core",
        "queries": [
            "Compute all core numbers and show the {entities} in the 5-core of this {network}.",
            "Run k-core decomposition and return the members that survive at k equals 5.",
            "Find the core number of every vertex and return only the vertex members of the requested 5-core, not its edge list.",
        ],
        "parameters": {"requested_k": 5},
        "optional_outputs": ["requested_core_vertices"],
    },
    {
        "problem_id": "maximal_biclique_enumeration",
        "operation_id": "maximal-bicliques",
        "queries": [
            "Using the attached left partition, enumerate maximal bicliques with at least two left and three right vertices.",
            "Find all maximal complete bipartite groups in the {network}; require 2 left-side and 3 right-side members.",
            "With my left-partition file, list maximal 2-by-3-or-larger bicliques.",
        ],
        "parameters": {"minimum_left_size": 2, "minimum_right_size": 3},
        "auxiliary_roles": ["left_partition"],
    },
    {
        "problem_id": "triangle_counting_listing",
        "operation_id": "triangle-counting",
        "queries": [
            "Count all triangles among {entities} and include each vertex's triangle participation.",
            "Measure closed triples in this {network}, including per-vertex counts.",
            "How many three-way closed connections exist, and how many involve each member?",
        ],
        "optional_outputs": ["per_vertex_count"],
    },
    {
        "problem_id": "triangle_counting_listing",
        "operation_id": "dynamic-triangle-counting",
        "queries": [
            "Apply the attached edge updates and report inserted, deleted, and net triangle counts.",
            "Update this {network} from my insertion/deletion file and compute the triangle-count change.",
            "Use the uploaded dynamic batch to measure how many closed triples are gained and lost.",
        ],
        "auxiliary_roles": ["updates"],
    },
    {
        "problem_id": "graph_motif_counting",
        "operation_id": "graph-motifs",
        "queries": [
            "Count induced occurrences of the attached motif and include per-vertex participation.",
            "Run a structural motif census: count induced occurrences of my uploaded motif and aggregate participation for each {entities} member.",
            "Using the uploaded motif definition, count induced instances and report which {entities} participate.",
        ],
        "parameters": {"induced": True},
        "optional_outputs": ["per_vertex_participation"],
        "auxiliary_roles": ["motif"],
    },
    {
        "problem_id": "subgraph_isomorphism",
        "operation_id": "subgraph-isomorphism",
        "queries": [
            "Count label-respecting embeddings of the attached query graph and include the embeddings.",
            "Match my uploaded query pattern against this {network} without ignoring labels, and list every embedding.",
            "Find every embedding of the attached subgraph pattern among the {entities}.",
        ],
        "optional_outputs": ["embeddings"],
        "auxiliary_roles": ["query_graph"],
    },
    {
        "problem_id": "temporal_motif_mining",
        "operation_id": "temporal-motif-mining",
        "queries": [
            "Count time-ordered feed-forward triangle events that finish within 3600 seconds; return the count only, not instance details.",
            "Count temporal A-to-B, B-to-C, A-to-C motif occurrences in a one-hour window; do not list instances.",
            "Count ordered three-edge temporal motifs whose maximum span is 3600 seconds, without materializing instances.",
        ],
        "parameters": {"max_time_span": 3600},
    },
    {
        "problem_id": "community_detection",
        "operation_id": "community-detection",
        "queries": [
            "Partition the undirected {network} into modularity communities and return their members.",
            "Detect disjoint communities among the {entities} using modularity optimization and return every community's member vertices.",
            "Cluster this {network} into non-overlapping communities and include each community's vertices.",
        ],
        "optional_outputs": ["communities"],
    },
    {
        "problem_id": "centrality_influential_node_mining",
        "operation_id": "betweenness-centrality",
        "queries": [
            "Rank {entities} by betweenness centrality in this {network}.",
            "Which {entities} lie on the most shortest paths? Return the betweenness ranking.",
            "Compute every vertex's betweenness score and rank the influential bridge vertices.",
        ],
        "optional_outputs": ["ranking"],
    },
]


UNSUPPORTED = [
    ("densest_subgraph", "Find the subgraph with maximum edge density."),
    ("densest_k_subgraph", "Find the densest subgraph containing exactly 25 vertices."),
    ("k_truss_decomposition", "Compute the full k-truss decomposition."),
    ("graphlet_counting", "Count every induced graphlet orbit up to size five."),
    ("frequent_subgraph_mining", "Mine frequent subgraphs across my graph collection."),
    (
        "overlapping_community_detection",
        "Find overlapping communities using exact k-clique percolation.",
    ),
    ("link_prediction", "Predict and rank the most likely missing edges."),
    ("graph_anomaly_detection", "Detect anomalous vertices and suspicious subgraphs."),
]


def build() -> dict:
    cases: list[dict] = []
    for domain_index, (domain_id, network, entities) in enumerate(DOMAINS):
        for operation in OPERATIONS:
            query = operation["queries"][domain_index % len(operation["queries"])]
            expected = {
                "problem_id": operation["problem_id"],
                "operation_id": operation["operation_id"],
                "supported": True,
            }
            for key in ("parameters", "optional_outputs", "auxiliary_roles"):
                if key in operation:
                    expected[key] = operation[key]
            cases.append(
                {
                    "id": f"v1-{domain_id}-{operation['operation_id']}",
                    "split": "v1_matrix_evaluation",
                    "domain_id": domain_id,
                    "user_query": query.format(network=network, entities=entities),
                    "expected": expected,
                }
            )
    for index, (problem_id, query) in enumerate(UNSUPPORTED):
        for variant in range(2):
            domain_id, network, _ = DOMAINS[(index * 2 + variant) % len(DOMAINS)]
            cases.append(
                {
                    "id": f"v1-unsupported-{problem_id}-{variant + 1}",
                    "split": "v1_routing_safety_evaluation",
                    "domain_id": domain_id,
                    "user_query": f"For this {network}, {query[0].lower() + query[1:]}",
                    "expected": {
                        "problem_id": problem_id,
                        "operation_id": None,
                        "supported": False,
                    },
                }
            )
    ambiguous = [
        ("general", "Find the important groups in this graph."),
        ("fraud_detection", "Tell me what looks interesting in these transactions."),
        ("bioinformatics", "Analyze the relevant protein structure."),
        ("transportation_mobility", "Which part of this transport network matters most?"),
    ]
    for index, (domain_id, query) in enumerate(ambiguous, 1):
        cases.append(
            {
                "id": f"v1-ambiguous-{index}",
                "split": "v1_routing_safety_evaluation",
                "domain_id": domain_id,
                "user_query": query,
                "expected": {
                    "problem_id": None,
                    "operation_id": None,
                    "supported": False,
                },
            }
        )
    return {
        "schema_version": "1.0.0",
        "purpose": (
            "Generated v1 domain/operation coverage and routing-safety matrix. "
            "This is an evaluation artifact, never a fine-tuning dataset."
        ),
        "cases": cases,
    }


if __name__ == "__main__":
    destination = Path(__file__).with_name("v1_query_cases.json")
    destination.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(build()['cases'])} cases to {destination}")
