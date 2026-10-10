from __future__ import annotations

import json
import unicodedata
from fractions import Fraction
from itertools import combinations

import networkx as nx
from rapidfuzz.distance import Levenshtein

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import external_id
from ..inputs import finite_number
from ..registry import register
from ._milp import BinaryModel

_MISSING = object()


def _field(attributes, path):
    for key in path.split("."):
        if not isinstance(attributes, dict) or key not in attributes:
            return _MISSING
        attributes = attributes[key]
    return attributes


def _rule(spec, records, work):
    if (
        not isinstance(spec, dict)
        or set(spec) != {"all"}
        or not isinstance(spec["all"], list)
        or not spec["all"]
    ):
        raise GraphMineError("A rule must contain a nonempty all array of predicates")
    predicates = []
    for predicate in spec["all"]:
        if not isinstance(predicate, dict) or set(predicate) - {
            "field",
            "operator",
            "max_distance",
            "normalization",
            "optional",
        }:
            raise GraphMineError("Unknown entity predicate fields")
        field, op = predicate.get("field"), predicate.get("operator")
        if not isinstance(field, str) or not all(field.split(".")):
            raise GraphMineError("Predicate field must be a nonempty attributes path")
        if not isinstance(op, str) or op not in {
            "eq",
            "shared_token",
            "edit_distance",
            "numeric_difference",
        }:
            raise GraphMineError("Unsupported entity predicate operator")
        optional = predicate.get("optional", False)
        normalization = predicate.get("normalization", "none")
        if type(optional) is not bool or normalization not in (
            "none",
            "casefold",
            "nfkc_casefold",
        ):
            raise GraphMineError("Invalid optional/normalization predicate setting")
        distance = None
        if op in {"edit_distance", "numeric_difference"}:
            distance = finite_number(
                predicate.get("max_distance"), "max_distance", nonnegative=True
            )
            if op == "edit_distance" and type(distance) is not int:
                raise GraphMineError("edit_distance max_distance must be an integer")
        elif "max_distance" in predicate:
            raise GraphMineError("max_distance applies only to distance predicates")
        if op == "numeric_difference" and normalization != "none":
            raise GraphMineError(
                "Text normalization does not apply to numeric_difference"
            )
        values = []
        for record in records:
            work.tick()
            value = _field(record.get("attributes", {}), field)
            if value is _MISSING:
                if not optional:
                    raise GraphMineError(
                        f"Record {record['id']!r} is missing required field {field!r}"
                    )
            elif op == "numeric_difference":
                value = Fraction(finite_number(value, f"Field {field}"))
            else:
                if (
                    op in {"shared_token", "edit_distance"} or normalization != "none"
                ) and not isinstance(value, str):
                    raise GraphMineError(
                        f"Field {field!r} must be text for this predicate"
                    )
                if normalization == "nfkc_casefold":
                    value = unicodedata.normalize("NFKC", value)
                if normalization != "none":
                    value = value.casefold()
                if op == "shared_token":
                    value = frozenset(value.split())
                elif op == "eq":
                    value = json.dumps(
                        value, sort_keys=True, ensure_ascii=False, allow_nan=False
                    )
            values.append(value)
        predicates.append((op, values, distance))

    def compare(u, v):
        for op, values, distance in predicates:
            work.tick()
            a, b = values[u], values[v]
            if a is _MISSING or b is _MISSING:
                return False
            if op == "eq":
                matched = a == b
            elif op == "shared_token":
                matched = bool(a & b)
            elif op == "numeric_difference":
                matched = abs(a - b) <= Fraction(distance)
            else:
                work.tick(len(a) + len(b))
                # Unit-cost distance never exceeds the longer string length.
                # Avoid narrowing an arbitrary JSON integer to a native cutoff.
                matched = (
                    distance >= max(len(a), len(b))
                    or Levenshtein.distance(a, b, score_cutoff=distance) <= distance
                )
            if not matched:
                return False
        return True

    return compare


@register(
    id="entity-resolution",
    problem_id="entity_resolution_blocking",
    family="data_preparation",
    title="Generate candidate record pairs and resolve entities using declared rules",
    description="RapidFuzz Levenshtein and declared equality/token/numeric predicates generate complete candidate pairs. NetworkX components provide transitive resolution; SciPy/HiGHS can minimize unit candidate-pair disagreements instead. Noncandidate pairs are neutral; clusters never cross candidate-graph components. Input graph edges are unused hints, not match decisions.",
    library="rapidfuzz",
    parameters={
        "task": P("string", required=True, choices=("blocking", "resolution")),
        "blocking_rules": P(
            "array",
            required=True,
            description="Nonempty rules with id and all predicates. Each predicate needs field (attributes path), operator (eq/shared_token/edit_distance/numeric_difference), optional=false, normalization=none|casefold|nfkc_casefold. Distance operators require nonnegative max_distance (integer for edit distance). Rules form a disjunction; predicates within each all form a conjunction.",
        ),
        "match_decision_rule": P(
            "object",
            None,
            nullable=True,
            description="An all predicate array, required for resolution.",
        ),
        "clustering_policy": P(
            "string",
            "connected_components",
            choices=("connected_components", "correlation_clustering"),
        ),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    references=(
        "https://rapidfuzz.github.io/RapidFuzz/Usage/distance/Levenshtein.html",
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html",
    ),
)
def resolve_entities(graph, args, work, backend="networkx"):
    records = graph.to_canonical()["vertices"]
    rules, ids = [], set()
    if not args["blocking_rules"]:
        raise GraphMineError("blocking_rules must not be empty")
    for rule in args["blocking_rules"]:
        if not isinstance(rule, dict) or set(rule) != {"id", "all"}:
            raise GraphMineError("Every blocking rule needs exactly id and all")
        rule_id = external_id(rule["id"])
        if rule_id in ids:
            raise GraphMineError("Blocking rule IDs must be unique")
        ids.add(rule_id)
        rules.append((rule_id, _rule({"all": rule["all"]}, records, work)))
    decision = args["match_decision_rule"]
    if args["task"] == "resolution":
        if decision is None:
            raise GraphMineError("resolution requires match_decision_rule")
        decide = _rule(decision, records, work)
    elif decision is not None or args["clustering_policy"] != "connected_components":
        raise GraphMineError(
            "Match decisions and clustering policy apply only to resolution"
        )
    n = graph.vertex_count
    possible = n * (n - 1) // 2
    candidates, matches = [], {}
    candidate_graph = nx.Graph(backend="networkx")
    candidate_graph.add_nodes_from(range(n))
    for u, v in combinations(range(n), 2):
        work.tick()
        satisfied = [rule_id for rule_id, compare in rules if compare(u, v)]
        if not satisfied:
            continue
        candidates.append(
            {
                "source": graph.vertex_id(u),
                "target": graph.vertex_id(v),
                "rule_ids": satisfied,
            }
        )
        candidate_graph.add_edge(u, v)
        if args["task"] == "resolution":
            matches[u, v] = decide(u, v)
        work.output(len(candidates))
    data = {
        "candidate_pairs": candidates,
        "reduction_ratio": 1 - len(candidates) / possible if possible else 0.0,
        "complete": True,
    }
    ports = {
        "candidates": {
            "type": "record_pair_collection",
            "value": candidates,
            "complete": True,
        }
    }
    evidence = {
        "input_edges": "ignored_coreference_hints",
        "missing_optional_field": "predicate_false",
        "tokenization": "unicode_whitespace_split",
        "noncandidate_pairs": "neutral",
    }
    quality = "exact"
    if args["task"] == "resolution":
        relation = nx.Graph(backend="networkx")
        relation.add_nodes_from(range(n))
        if args["clustering_policy"] == "connected_components":
            relation.add_edges_from(pair for pair, match in matches.items() if match)
        else:
            work.tick(n * (n - 1) * max(0, n - 2) // 6)
            pairs = list(combinations(range(n), 2))
            indices = {pair: i for i, pair in enumerate(pairs)}
            model = BinaryModel(
                [
                    -1
                    if matches.get(pair) is True
                    else 1
                    if matches.get(pair) is False
                    else 0
                    for pair in pairs
                ],
                work,
            )
            component = {
                v: i
                for i, nodes in enumerate(
                    nx.connected_components(candidate_graph, backend="networkx")
                )
                for v in nodes
            }
            for (u, v), index in indices.items():
                if component[u] != component[v]:
                    model.constrain({index: 1}, upper=0)
            for u, v, w in combinations(range(n), 3):
                i, j, k = indices[u, v], indices[u, w], indices[v, w]
                for excluded, a, b in ((i, j, k), (j, i, k), (k, i, j)):
                    model.constrain({excluded: -1, a: 1, b: 1}, upper=1)
            values, solver = model.solve()
            if values is None:
                raise GraphMineError("Correlation clustering unexpectedly infeasible")
            relation.add_edges_from(
                pair for pair, value in zip(pairs, values, strict=True) if value
            )
            if any(
                relation.subgraph(nodes).number_of_edges()
                != len(nodes) * (len(nodes) - 1) // 2
                for nodes in nx.connected_components(relation, backend="networkx")
            ):
                raise GraphMineError(
                    "Correlation-clustering relation is not transitive"
                )
            quality = "numerical_optimum"
            evidence.update(solver)
        groups = sorted(
            (
                sorted(nodes)
                for nodes in nx.connected_components(relation, backend="networkx")
            ),
            key=lambda nodes: nodes[0],
        )
        group_of = {v: i for i, nodes in enumerate(groups) for v in nodes}
        assignments = [
            {"vertex": graph.vertex_id(v), "cluster": group_of[v]} for v in range(n)
        ]
        disagreements = sum(
            (group_of[u] == group_of[v]) != match for (u, v), match in matches.items()
        )
        data.update(
            resolved_entity_id=assignments,
            match_decision=[
                {
                    "source": graph.vertex_id(u),
                    "target": graph.vertex_id(v),
                    "match": match,
                }
                for (u, v), match in matches.items()
            ],
            candidate_pair_disagreements=disagreements,
            clustering_optimal=args["clustering_policy"] == "correlation_clustering",
        )
        ports["clusters"] = {
            "type": "vertex_partition",
            "value": assignments,
            "complete": True,
        }
        work.output(len(candidates) + len(matches) + len(assignments))
    return AlgorithmOutput(data, ports, quality=quality, diagnostics=evidence)
