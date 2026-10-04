"""Application task contracts derived from imported public graphs, not LLM labels."""

from __future__ import annotations

import copy

from ..models import ApplicationIntent
from .corpus import PROBLEMS, digest
from .meaning import expected_meaning
from .oracles import expected_answer

VOCABULARY = {
    "sociopatterns-workplace": {
        "role": "Workplace collaboration analyst",
        "entities": "participants",
        "entity": "participant",
        "relation": "had a recorded face-to-face contact",
        "scope": "the supplied anonymous workplace contact sample",
        "weight": "duration_seconds",
        "empty_field": "contact_intervals",
        "attribute_request": "Include the anonymous participant labels and departments.",
    },
    "string-ecoli": {
        "role": "Laboratory researcher organizing follow-up experiments",
        "entities": "proteins",
        "entity": "protein",
        "relation": "has a recorded functional association",
        "scope": "the supplied E. coli association sample",
        "weight": "score",
        "empty_field": "score",
        "attribute_request": "Use gene names and original STRING identifiers. Associations are not proof of binding or causation.",
    },
    "openflights": {
        "role": "Transport analyst studying historical airport connectivity",
        "entities": "airports",
        "entity": "airport",
        "relation": "had a listed nonstop route in both directions",
        "scope": "the supplied historical UK airport sample, not today's route network",
        "weight": "fare",
        "empty_field": "stops",
        "attribute_request": "Include airport names, cities and IATA codes. These are historical records, not current travel advice.",
    },
}


def make_task(
    graph: dict,
    vocabulary: dict,
    query: str,
    operation: str | None,
    *,
    parameters: dict | None = None,
    filters: list | None = None,
    behavior: str = "execute",
    reason: str = "",
    weights: bool = False,
) -> dict:
    intent = ApplicationIntent(
        objective=query,
        entity_type=vocabulary["entity"],
        relationship_meaning=vocabulary["relation"],
        filters=filters or [],
        filter_mode="replace",
        requires_edge_weights=weights,
        weight_attribute="attributes." + vocabulary["weight"] if weights else None,
        weight_usage="path_length" if weights else None,
    ).model_dump(mode="json")
    task = {
        "query": query,
        "operation_id": operation,
        "problem_id": PROBLEMS.get(operation),
        "parameters": parameters or {},
        "filters": filters or [],
        "optional_outputs": {
            "k-cliques": ["cliques"],
            "k-core": ["requested_core_vertices"],
            "betweenness-centrality": ["ranking"],
            "community-detection": ["communities"],
        }.get(operation, []),
        "behavior": behavior,
        "reason": reason,
        "intent": intent,
        "weight_attribute": "attributes." + vocabulary["weight"] if weights else None,
        "weight_usage": "path_length" if weights else None,
    }
    task["oracle"] = expected_answer(graph, task)
    return task


def build_cases(records: list[dict]) -> list[dict]:
    cases = []
    for record in records:
        graph, source = record["graph"], record["source_id"]
        words = VOCABULARY[source]
        noun, relation, scope = words["entities"], words["relation"], words["scope"]
        suffix = " " + words["attribute_request"]

        def task(query, operation, graph=graph, words=words, **kwargs):
            return make_task(graph, words, query, operation, **kwargs)

        def case(category, steps, record=record, source=source, words=words):
            identifier = record["id"] + "-" + category
            cases.append(
                {
                    "id": identifier,
                    "source_id": source,
                    "graph_id": record["id"],
                    "split": record["split"],
                    "domain": record["domain"],
                    "role": words["role"],
                    "category": category,
                    "steps": steps,
                    "task_origin": "application_contract_template_and_independent_reference",
                    "training_eligible": False,
                }
            )

        all_groups = task(
            f"In {scope}, list every group of at least three {noun} where every pair {relation}. "
            "Leave out groups contained in a larger group satisfying the same rule."
            + suffix,
            "maximal-cliques",
            parameters={"minimum_clique_size": 3},
        )
        if record["synthetic_perturbation"]:
            case("untrusted-record-text", [all_groups])
            continue
        largest = task(
            f"Using only {scope}, find one biggest group of {noun} where every pair {relation}. "
            "One group is enough if several tie." + suffix,
            "maximum-clique",
        )
        case("one-largest-group", [largest])
        case("all-unextendable-groups", [all_groups])
        case(
            "exact-size",
            [
                task(
                    f"In {scope}, list all groups of exactly three {noun} where every pair {relation}, "
                    "including trios that also belong to larger groups." + suffix,
                    "k-cliques",
                    parameters={"k": 3},
                )
            ],
        )
        case(
            "iterative-pruning",
            [
                task(
                    f"Using {scope}, repeatedly remove any {words['entity']} with fewer than three "
                    f"remaining direct partners. Keep doing this until nobody else can be removed. Show who remains."
                    + suffix,
                    "k-core",
                    parameters={"requested_k": 3},
                )
            ],
        )
        case(
            "unweighted-connectors",
            [
                task(
                    f"In {scope}, rank all {noun} by how often they sit between other pairs "
                    "along routes with the fewest relationship steps. Every link counts as one step; ignore recorded strengths or durations."
                    + suffix,
                    "betweenness-centrality",
                )
            ],
        )
        case(
            "connection-groups",
            [
                task(
                    f"Suggest connection-based groups in {scope}, using each recorded link equally. "
                    "Assign each member to one group and show the groups as exploratory suggestions, not established categories."
                    + suffix,
                    "community-detection",
                )
            ],
        )
        case(
            "ambiguous-priority",
            [
                task(
                    f"I need to decide which {noun} in {scope} to focus on first. Can you help?",
                    None,
                    behavior="clarify",
                    reason="undefined_priority",
                )
            ],
        )
        case(
            "unsupported-weighted-routes",
            [
                task(
                    f"Rank the {noun} in {scope} by how often they sit between other pairs on "
                    f"shortest routes, using each link's {words['weight']} as its length rather than treating every step equally."
                    + suffix,
                    "betweenness-centrality",
                    weights=True,
                    behavior="unsupported",
                    reason="weighted_routes_unavailable",
                )
            ],
        )
        # Zero-duration contacts / zero-confidence associations are absent by construction.
        empty_value = 99 if source == "openflights" else 0
        empty_filter = [
            {
                "target": "edges",
                "field": "attributes." + words["empty_field"],
                "operator": "eq",
                "value": empty_value,
            }
        ]
        case(
            "empty-result",
            [
                task(
                    f"In {scope}, only use relationships whose recorded {words['empty_field']} equals {empty_value}. "
                    f"List every unextendable group of at least three {noun} in which every pair is directly connected."
                    + suffix,
                    "maximal-cliques",
                    parameters={"minimum_clique_size": 3},
                    filters=empty_filter,
                )
            ],
        )
        if record["split"] == "holdout":
            continue
        if source == "sociopatterns-workplace":
            value = min(v["attributes"]["department"] for v in graph["vertices"])
            filters = [
                {
                    "target": "vertices",
                    "field": "attributes.department",
                    "operator": "eq",
                    "value": value,
                }
            ]
            correction = f"Now only include participants in department {value}. Keep the group rules."
            reset = "Drop the department restriction and use all participants again. Keep the group rules."
        else:
            value = max(e["attributes"]["score"] for e in graph["edges"])
            filters = [
                {
                    "target": "edges",
                    "field": "attributes.score",
                    "operator": "eq",
                    "value": value,
                }
            ]
            correction = f"Now only use associations whose recorded score is exactly {value}. Keep the group rules."
            reset = "Drop the score restriction and use all supplied associations again. Keep the group rules."
        changed_query = (
            f"Actually, I need every group of at least three {noun}, not just one biggest group. "
            "Every pair must have a direct recorded relationship. Leave out groups contained in a larger qualifying group."
        )
        changed = task(
            changed_query, "maximal-cliques", parameters={"minimum_clique_size": 3}
        )
        scoped = task(
            correction,
            "maximal-cliques",
            parameters={"minimum_clique_size": 3},
            filters=filters,
        )
        cleared = task(reset, "maximal-cliques", parameters={"minimum_clique_size": 3})
        case("correction-filter-reset", [largest, changed, scoped, cleared])
    return cases


def reference_meaning(task: dict) -> dict:
    return {
        **expected_meaning(task).model_dump(mode="json"),
        "weight_attribute": task["weight_attribute"],
        "weight_usage": task["weight_usage"],
    }


def calibration_controls(cases: list[dict]) -> list[dict]:
    """Eight explicit controls; expected meanings never sent to the reviewer."""
    controls = []
    choices = (
        ("sociopatterns-workplace", "one-largest-group"),
        ("sociopatterns-workplace", "iterative-pruning"),
        ("sociopatterns-workplace", "ambiguous-priority"),
        ("string-ecoli", "unsupported-weighted-routes"),
        ("string-ecoli", "exact-size"),
        ("string-ecoli", "empty-result"),
        ("sociopatterns-workplace", "correction-filter-reset"),
    )
    for source, category in choices:
        case = next(
            c for c in cases if c["source_id"] == source and c["category"] == category
        )
        controls.append(
            {
                "id": "control-" + case["id"],
                "graph_id": case["graph_id"],
                "queries": [t["query"] for t in case["steps"]],
                "expected": [reference_meaning(t) for t in case["steps"]],
            }
        )
    pruning = copy.deepcopy(controls[1])
    pruning["id"] = "control-one-pass-not-repeated-pruning"
    pruning["queries"] = [
        "List the participants with at least three direct contact partners in the original sample. Check once; do not keep removing people and recounting."
    ]
    pruning["expected"][0]["goal"] = "single_pass_partner_filter"
    controls.append(pruning)
    return controls


def case_digest(case: dict) -> str:
    return digest(case)
