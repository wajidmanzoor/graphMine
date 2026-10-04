"""Freeze development language/context challenges before observing model outputs.

These manually specified semantic fixtures are evaluation-only. They use
validation graphs and are not a fresh, independent test of graph generalization.
The saved primary suite supplies the exact model/decoding/provenance contract.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from graphmine_agent.catalog import Catalog
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.adapter_eval import read_suite, score_route
from graphmine_agent.learning.corpus import digest, load_corpus
from graphmine_agent.learning.pipeline import training_route_payload
from graphmine_agent.models import (
    AnalysisTask,
    ApplicationIntent,
    RouteDecision,
    utc_now,
)


def build_cases(corpus: Path, catalog: Catalog):
    manifest, graphs = load_corpus(corpus)
    sources = {}
    for example in manifest["examples"]:
        if example["split"] == "validation":
            sources.setdefault(example["family"], example)
    ordinary = sources["cycle_chords"]
    retail = sources["retail_nested"]
    events = sources["events_cycle"]
    graph_info = {g["id"]: g for g in manifest["graphs"]}
    vocabulary = graph_info[ordinary["graph_id"]]["vocabulary"]
    noun, relation = vocabulary["plural"], vocabulary["relation"]
    train_queries = {
        x["task"]["query"] for x in manifest["examples"] if x["split"] == "train"
    }
    cases = []

    def add(
        name,
        query,
        operation=None,
        *,
        source=ordinary,
        behavior="execute",
        intent=None,
        active=None,
        extra=(),
        problem=None,
        category="new_wording",
    ):
        graph = graphs[source["graph_id"]]
        expected_intent = ApplicationIntent(
            objective=query, filter_mode="replace", **(intent or {})
        )
        route = RouteDecision(
            problem_id=problem
            or (catalog.operation(operation).problem_id if operation else None),
            operation_id=operation if behavior == "execute" else None,
            supported=behavior == "execute",
            confidence=1,
            ambiguity=["What outcome are you trying to achieve?"]
            if behavior == "clarify"
            else [],
            explanation="Evaluation contract defined before inference.",
            intent=expected_intent,
            additional_analyses=[
                AnalysisTask(
                    question=q,
                    problem_id=catalog.operation(op).problem_id,
                    operation_id=op,
                )
                for op, q in extra
            ],
        )
        payload = training_route_payload(catalog, source, graph, query=query)
        payload["active_constraints"] = (
            ApplicationIntent(**active).model_dump(mode="json") if active else None
        )
        case = {
            "id": name,
            "split": "development_challenge",
            "family": category,
            "domain": source["domain"],
            "behavior": behavior,
            "operation_id": operation,
            "source_graph_id": source["graph_id"],
            "source_graph_sha256": digest(graph),
            "query_seen_in_training": query in train_queries,
            "payload": payload,
            "expected": route.model_dump(mode="json"),
            "label_source": "manually specified application semantics; evaluation only",
        }
        # A fully materialized replacement scope must satisfy the exact oracle.
        score = score_route(case, route.model_dump_json(), catalog)
        if not score["passed"]:
            raise ValueError(f"Inconsistent challenge {name}: {score['issues']}")
        cases.append(case)

    def edge(field, operator, value):
        return {
            "target": "edges",
            "field": f"attributes.{field}",
            "operator": operator,
            "value": value,
        }

    def vertex(field, operator, value):
        return {
            "target": "vertices",
            "field": f"attributes.{field}",
            "operator": operator,
            "value": value,
        }

    year = edge("year", "eq", 2026)
    north = vertex("region", "eq", "North")
    maximal = f"Find all groups of at least three {noun} where every pair {relation}; discard any group contained in a larger such group."
    add(
        "language-maximal",
        f"Give me the complete circles of {noun}: everyone in a circle must have a recorded link to everyone else in it, and nobody else can be added without breaking that rule. Ignore circles smaller than three.",
        "maximal-cliques",
    )
    add(
        "language-maximum",
        f"For a single meeting I need as many {noun} as possible, with a recorded connection between every two invitees. Pick one biggest possible group; tied alternatives are unnecessary.",
        "maximum-clique",
    )
    add(
        "language-exact-size",
        f"Show every possible four-member set of {noun} whose members all have direct links to each other. Include sets that sit inside bigger fully connected groups.",
        "k-cliques",
    )
    add(
        "language-core",
        f"Repeatedly remove {noun} who have fewer than three connections to those still present. Keep repeating until no more removals are possible, then list the survivors.",
        "k-core",
    )
    add(
        "language-bridges",
        f"Rank every {noun} by the fraction of shortest routes between other pairs that pass through them. Count one step per recorded link.",
        "betweenness-centrality",
    )
    add(
        "language-communities",
        f"Split the {noun} into exploratory groups using connection structure, putting each in just one group and treating all links equally. Show the resulting memberships.",
        "community-detection",
    )
    add(
        "language-retail",
        "Show customer sets and product sets where each customer purchased every listed product. Each side needs at least two members. Include every pair of sets that cannot be expanded on either side.",
        "maximal-bicliques",
        source=retail,
    )
    temporal = {
        "requires_direction": True,
        "pattern_vertex_count": 3,
        "pattern_edges": [[0, 1], [1, 2], [0, 2]],
        "time_unit": "seconds",
        "time_window": 5,
    }
    add(
        "language-temporal",
        "Find ordered messages X to Y, then Y to Z, then X to Z. X, Y and Z must be different hosts, and the last message must be no more than five seconds after the first.",
        "temporal-motif-mining",
        source=events,
        intent=temporal,
    )
    add(
        "filter-year-inequality",
        "Use relationships recorded after 2025. " + maximal,
        "maximal-cliques",
        intent={"filters": [edge("year", "gt", 2025)]},
        category="changed_filter",
    )
    add(
        "filter-ascore",
        "Use only links with ascore at least 0.5; this time I mean ascore, not score. "
        + maximal,
        "maximal-cliques",
        intent={"filters": [edge("ascore", "gte", 0.5)]},
        category="changed_filter",
    )
    add(
        "filter-two-conditions",
        "Keep relationships with score at least 0.5 and cost no more than 10. Treat the remaining links equally. "
        + maximal,
        "maximal-cliques",
        intent={"filters": [edge("score", "gte", 0.5), edge("cost", "lte", 10)]},
        category="changed_filter",
    )
    add(
        "filter-node-and-edge",
        f"Use only {noun} in the South region and only links from 2025. " + maximal,
        "maximal-cliques",
        intent={"filters": [vertex("region", "eq", "South"), edge("year", "eq", 2025)]},
        category="changed_filter",
    )
    add(
        "filter-empty",
        "Restrict members to region Atlantis, even if that leaves nobody. "
        + maximal
        + " If the result is empty, simply report no groups.",
        "maximal-cliques",
        intent={"filters": [vertex("region", "eq", "Atlantis")]},
        category="empty_selection",
    )
    add(
        "filter-cost-without-weight",
        f"Discard links costing more than 10, then rank all {noun} by how often they lie on shortest routes between other pairs. Measure routes by number of links, not cost.",
        "betweenness-centrality",
        intent={"filters": [edge("cost", "lte", 10)]},
        category="filter_vs_weight",
    )
    add(
        "weight-cost",
        f"Rank {noun} by how often they lie on cheapest routes between other pairs. A route's length is the sum of its link costs, not its number of links.",
        "betweenness-centrality",
        behavior="unsupported",
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.cost",
            "weight_usage": "path_length",
        },
        category="unsupported_weight",
    )
    add(
        "weight-strength",
        f"Divide {noun} into exploratory groups, but use score as the strength of each connection in the grouping calculation; do not treat links equally.",
        "community-detection",
        behavior="unsupported",
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.score",
            "weight_usage": "strength",
        },
        category="unsupported_weight",
    )
    add(
        "filter-plus-weight",
        f"Keep only links from 2025, then rank {noun} by shortest-route mediation using cost as link length, not the number of links.",
        "betweenness-centrality",
        behavior="unsupported",
        intent={
            "filters": [edge("year", "eq", 2025)],
            "requires_edge_weights": True,
            "weight_attribute": "attributes.cost",
            "weight_usage": "path_length",
        },
        category="unsupported_weight",
    )
    add(
        "temporal-milliseconds",
        "Find X to Y, then Y to Z, then X to Z on three different hosts within 20000 milliseconds from first event to last.",
        "temporal-motif-mining",
        source=events,
        intent={**temporal, "time_unit": "milliseconds", "time_window": 20000},
        category="changed_temporal",
    )
    add(
        "temporal-four-hosts",
        "Find X to Y, then Y to Z, then Z to W, where all four hosts are different and all three events happen within five seconds.",
        "temporal-motif-mining",
        source=events,
        behavior="unsupported",
        intent={
            **temporal,
            "pattern_vertex_count": 4,
            "pattern_edges": [[0, 1], [1, 2], [2, 3]],
        },
        category="unsupported_pattern",
    )
    add(
        "temporal-cycle",
        "Find X to Y, then Y to Z, then Z to X on three different hosts, within five seconds from the first event to the last.",
        "temporal-motif-mining",
        source=events,
        behavior="unsupported",
        intent={**temporal, "pattern_edges": [[0, 1], [1, 2], [2, 0]]},
        category="unsupported_pattern",
    )
    add(
        "followup-change-analysis",
        "Keep the 2026 restriction. Now give one largest fully connected group instead of every group; one is enough if tied.",
        "maximum-clique",
        intent={"filters": [year]},
        active={"filters": [year]},
        category="contextual_scope",
    )
    add(
        "followup-add-filter",
        "Keep the year restriction and add score at least 0.5. " + maximal,
        "maximal-cliques",
        intent={"filters": [year, edge("score", "gte", 0.5)]},
        active={"filters": [year]},
        category="contextual_scope",
    )
    add(
        "followup-replace-year",
        "Change the year restriction from 2026 to 2025. " + maximal,
        "maximal-cliques",
        intent={"filters": [edge("year", "eq", 2025)]},
        active={"filters": [year]},
        category="contextual_scope",
    )
    add(
        "followup-clear-one-filter",
        "Include all regions now, while keeping the 2026 link restriction. " + maximal,
        "maximal-cliques",
        intent={"filters": [year]},
        active={"filters": [year, north]},
        category="contextual_scope",
    )
    add(
        "followup-clear-all-filters",
        "Remove every year and region restriction and use the whole network. "
        + maximal,
        "maximal-cliques",
        active={"filters": [year, north]},
        category="contextual_scope",
    )
    add(
        "followup-exact-size",
        "Keep the North-region restriction, but list all fully connected groups of exactly four, including those inside larger groups.",
        "k-cliques",
        intent={"filters": [north]},
        active={"filters": [north]},
        category="contextual_scope",
    )
    add(
        "multiple-analyses",
        maximal
        + f" Separately, rank all {noun} by how often shortest routes between other pairs pass through them, counting one step per link.",
        "maximal-cliques",
        extra=[
            (
                "betweenness-centrality",
                "Rank all entities by shortest-route mediation with unit link lengths.",
            )
        ],
        category="multiple_analyses",
    )
    add(
        "ambiguous-action",
        f"Which {noun} should I investigate? I haven't decided what kind of pattern matters.",
        behavior="clarify",
        category="ambiguous_intent",
    )

    # Existing v1 safety/operation cases are development regressions. Their
    # expected numeric parameters are deliberately not claimed by this routing check.
    legacy_path = (
        catalog.settings.repository_root / "agent/evaluation/v1_query_cases.json"
    )
    legacy = json.loads(legacy_path.read_text())["cases"]
    seen_unsupported = set()
    for item in legacy:
        if not (
            item["id"].startswith("v1-general-")
            or item["split"] == "v1_routing_safety_evaluation"
        ):
            continue
        expected = item["expected"]
        query = item["user_query"]
        if not expected["supported"] and expected["problem_id"]:
            if expected["problem_id"] in seen_unsupported:
                continue
            seen_unsupported.add(expected["problem_id"])
            # Preserve the formal task while matching this fixture's vocabulary.
            query = "For this network, " + query.partition(", ")[2]
        query = (
            query.replace("these transactions", "these relationships")
            .replace("protein structure", "relationship structure")
            .replace("this transport network", "this network")
        )
        op = expected["operation_id"]
        intent = {}
        source = ordinary
        if op == "maximal-bicliques":
            source = retail
        if op == "temporal-motif-mining":
            source = events
            intent = {**temporal, "time_window": 3600}
        behavior = (
            "execute"
            if expected["supported"]
            else "unsupported"
            if expected["problem_id"]
            else "clarify"
        )
        add(
            "retention-" + item["id"],
            query,
            op,
            source=source,
            behavior=behavior,
            problem=expected["problem_id"],
            intent=intent,
            category="existing_operation_retention"
            if behavior == "execute"
            else "existing_safety_retention",
        )
        cases[-1]["legacy_case_sha256"] = digest(item)
        cases[-1]["legacy_wording_adapted"] = query != item["user_query"]
    return cases


def prepare(template: Path, output: Path):
    if output.exists():
        raise ValueError("Use a new challenge-suite directory")
    plan, _, _ = read_suite(template)
    cases = build_cases(Path(plan["corpus"]), Catalog(Settings.from_env()))
    if any(c["query_seen_in_training"] for c in cases):
        raise ValueError("Challenge questions must differ from pilot training text")
    output.mkdir(parents=True, mode=0o700)
    HistoryStore.write(output / "cases.json", cases)
    result = deepcopy(plan)
    result.update(
        created_at=utc_now().isoformat(),
        split="development_challenge",
        case_count=len(cases),
        cases_sha256=HistoryStore.digest(output / "cases.json"),
        queries_seen_in_training=0,
        builder_sha256=HistoryStore.digest(Path(__file__)),
        template_plan_sha256=HistoryStore.digest(template / "plan.json"),
        limitations=[
            "Manually specified development language/scope contracts; not blinded independent review.",
            "Validation graphs were seen during token-loss evaluation, never weight training.",
            "Existing v1 operation/safety cases are previously inspected regressions, not untouched holdouts.",
            "Contextual scope uses explicit prior state; it is not a complete multi-turn agent replay.",
            "Numeric parameters, native answers, explanation quality and presentation are outside this routing score.",
            "FP8 has different precision/engine; only NF4 arms isolate adapter impact.",
        ],
    )
    (output / "builder.py").write_bytes(Path(__file__).read_bytes())
    (output / "evaluator.py").write_bytes((template / "evaluator.py").read_bytes())
    HistoryStore.write(output / "plan.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.template, args.output)
    print(
        json.dumps(
            {k: result[k] for k in ("case_count", "split", "queries_seen_in_training")}
        )
    )
