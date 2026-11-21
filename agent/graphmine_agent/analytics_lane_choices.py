"""Evidence and small plans that a router may select, never author."""

from copy import deepcopy
import json
import re

from .graph_context import fields


def describes(profiles):
    facts = []

    def add(alias, property, value, statement):
        facts.append({"id": f"input_{len(facts)}", "input": alias, "property": property,
                      "value": value, "statement": statement})

    for alias, profile in profiles.items():
        for key, noun in (("vertices_count", "vertices"), ("edges_count", "connections"),
                          ("graphs_count", "graphs"), ("hyperedges_count", "hyperedges"), ("vectors_count", "vectors")):
            if key in profile:
                add(alias, key, profile[key], f"{alias} contains {profile[key]:,} {noun}.")
        if profile["input_kind"] != "graph":
            continue
        types = profile["vertex_types"]
        add(alias, "vertex_types", types, f"The vertex types in {alias} are {', '.join(types) or 'none'}.")
        for name, count in profile["vertex_type_count"].items():
            add(alias, f"vertex_type_count.{name}", count, f"{alias} contains {count:,} {name} records.")
        for name, count in profile["edge_type_count"].items():
            add(alias, f"edge_type_count.{name}", count, f"{alias} contains {count:,} {name} connections.")
        add(alias, "directed", profile["directed"], f"{alias} is {'directed' if profile['directed'] else 'undirected'}.")
        weights = ', '.join(profile['weight_fields'])
        add(alias, "weighted", profile["weighted"],
            f"Numeric connection values are available in {weights}." if weights else "No numeric connection weights are present.")
        add(alias, "bipartite", profile["bipartite"],
            "The declared or inferred sides have every connection crossing between them." if profile["bipartite"] else "The snapshot does not have a valid declared or two-type bipartition.")
        add(alias, "temporal", profile["temporal"],
            "Connection timestamps are present." if profile["temporal"] else "No connection timestamps are present.")
        for key, noun in (("vertex_fields", "vertex"), ("edge_fields", "connection")):
            names = sorted(profile[key])
            add(alias, key, names, f"The {noun} fields are {', '.join(names)}.")
    return facts


def description_answer(fact_ids, facts):
    by_id = {fact["id"]: fact for fact in facts}
    selected = [deepcopy(by_id[key]) for key in fact_ids]
    # Equivalent full-type counts remain explicit evidence as well as prose.
    for fact in list(selected):
        total_property = next((total for prefix, total in (("vertex_type_count.", "vertices_count"), ("edge_type_count.", "edges_count"))
                               if fact["property"].startswith(prefix)), None)
        if total_property:
            total = next(row for row in facts if row["input"] == fact["input"] and row["property"] == total_property)
            if total["value"] == fact["value"] and total["id"] not in fact_ids:
                selected.append(deepcopy(total))
    return {"text": " ".join(fact["statement"] for fact in selected), "facts": selected,
            "citations": [{"id": fact["id"], "kind": "fact", "ref": f"input:{fact['input']}:{fact['property']}"} for fact in selected]}


def one_step(operation, alias, parameters, device):
    return {"version": 1, "device": device, "steps": [{"id": "answer", "operation": operation,
            "input": {"input": alias}, "parameters": deepcopy(parameters), "bindings": {}}]}


def lookup_choices(inputs, cards, entities, question, device):
    """Finite choices contain actual records/fields; no model-generated IDs."""
    available = {card["id"] for card in cards}
    choices, seen = [], set()

    def add(operation, alias, parameters, description):
        key = (operation, alias, json.dumps(parameters, sort_keys=True))
        if operation not in available or key in seen:
            return
        seen.add(key)
        choices.append({"id": f"lookup_{len(choices)}", "operation": operation,
                        "description": description, "plan": one_step(operation, alias, parameters, device)})

    for alias, descriptor in inputs.items():
        if descriptor["kind"] != "graph":
            continue
        graph = descriptor["data"]
        matches = [row for row in entities if row["input"] == alias]
        for match in matches[:12]:
            name = match.get("label") or match["matched"]
            add("node-lookup", alias, {"vertices": [match["id"]]}, f"Return the full record for {name} in {alias}.")
            for direction, label in (("out", "outgoing"), ("in", "incoming"), ("both", "either direction")):
                add("neighbors", alias, {"entity": match["id"], "direction": direction},
                    f"List direct neighbors of {name}, using {label} connections in {alias}.")
        # Values are read from the question against real field names. Unknown
        # values are valid predicates and can return an empty result.
        names = sorted({name for row in graph["vertices"] for name in fields(row)
                        if name not in {"id", "label"}})
        predicates, predicate_labels = [], []
        for name in names:
            short = name.removeprefix("attributes.")
            matched = re.search(r"\b" + re.escape(short) + r"\s*(?:is|equals?|=)\s*(?:\"([^\"]*)\"|'([^']*)'|([^,?.;]+?)(?=\s+and\s+\w+\s*(?:is|equals?|=)|[,?.;]|$))", question, re.I)
            if not matched:
                continue
            value = next(group for group in matched.groups() if group is not None).strip()
            actual = [fields(row)[name] for row in graph["vertices"] if name in fields(row)]
            same = next((item for item in actual if str(item).casefold() == value.casefold()), value)
            if any(isinstance(item, (int, float)) and not isinstance(item, bool) for item in actual):
                try:
                    same = json.loads(value)
                except ValueError:
                    continue
                if not isinstance(same, (int, float)) or isinstance(same, bool):
                    continue
            predicates.append({"field": name, "op": "eq", "value": same})
            predicate_labels.append(f"{short} equal to {same!r}")
        if predicates and not re.search(r"\bor\b", question, re.I):
            add("node-lookup", alias, {"vertex_filters": predicates},
                f"List full records with {' and '.join(predicate_labels)} in {alias}.")
        for direction, label in (("outgoing", "outgoing"), ("incoming", "incoming"), ("both", "incoming and outgoing")):
            add("degree-centrality", alias, {"normalized": False, "direction_mode": direction},
                f"Find who has the most {label} connections in {alias}; compute all degrees to retain ties.")
    return choices


def reply_sources(cards, repository_root):
    """Native contracts and local documentation, retrieved for this turn."""
    sources = [{"id": f"contract.{card['id']}", "kind": "contract", "ref": f"operation:{card['id']}",
                "title": card["title"], "text": card["description"]} for card in cards]
    document = json.loads((repository_root / "catalog/agent_concepts.json").read_text())
    sources.extend({"id": f"doc.{row['id']}", "kind": "doc", "ref": f"catalog/agent_concepts.json#{row['id']}",
                    "title": row["title"], "text": row["text"]} for row in document["sections"])
    return sources


def explicit_parameters(card, question, entities=(), alias=None):
    """Only literal values stated in the question; defaults remain native-owned."""
    parameters, text = {}, question.casefold()
    for name, spec in card["parameters"].items():
        stated = [choice for choice in spec.get("choices", []) if isinstance(choice, str)
                  and re.search(r"\b" + re.escape(choice.replace("_", " ")) + r"\b", text)]
        stated = [choice for choice in stated if not any(choice != other and choice.replace('_', ' ') in other.replace('_', ' ') for other in stated)]
        if len(stated) == 1:
            parameters[name] = stated[0]
        if spec["kind"] == "boolean":
            match = re.search(r"\b" + re.escape(name.replace("_", " ")) + r"\s*(?:=|is)?\s*(true|false)\b", text)
            if match:
                parameters[name] = match[1] == "true"
        if spec["kind"] in ("integer", "number"):
            expression = r"\b" + re.escape(name.replace("_", " ")) + r"\s*(?:=|is|of)?\s*(-?\d+(?:\.\d+)?)\b"
            match = re.search(expression, text)
            if match:
                value = float(match[1])
                if spec["kind"] == "number" or value.is_integer():
                    parameters[name] = int(value) if spec["kind"] == "integer" else value
    for operation, noun, parameter in (("k-core", "core", "requested_k"), ("k-truss", "truss", "requested_k"), ("k-cliques", "clique", "k")):
        if card["id"] == operation:
            match = re.search(r"\b(\d+)[ -]" + noun, text)
            if match:
                parameters[parameter] = int(match[1])
    if "normalized" in card["parameters"] and re.search(r"without normalization|unnormalized|not normalized", text):
        parameters["normalized"] = False
    if card["id"] == "degree-centrality":
        for word, mode in (("outgoing", "outgoing"), ("incoming", "incoming")):
            if word in text:
                parameters["direction_mode"] = mode
    candidates = [row for row in entities if alias is None or row["input"] == alias]
    if card["id"] == "many-source-shortest-paths":
        endpoints = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)|\bbetween\s+(.+?)\s+and\s+(.+)", text)
        if endpoints:
            segments = endpoints.groups()[:2] if endpoints[1] is not None else endpoints.groups()[2:]
            for name, segment in zip(("origins", "destinations"), segments):
                matches = [row for row in candidates if re.search(
                    r"(?<!\w)" + re.escape(row["matched"].casefold()) + r"(?!\w)", segment)]
                if len(matches) == 1:
                    parameters[name] = [matches[0]["id"]]
    for name, spec in card["parameters"].items():
        if spec.get("required") and name not in parameters and name in ("source", "source_vertex", "entity", "sources", "start_vertices", "seed_vertices", "seeds"):
            if len(candidates) == 1:
                parameters[name] = [candidates[0]["id"]] if spec["kind"] == "array" else candidates[0]["id"]
    return parameters


# Related computations have different mathematical objectives. These are
# alternatives to explicit operation choices, not interpretations of vague words.
ALTERNATIVES = {
    "maximal-cliques": ("maximum-clique", {}), "maximum-clique": ("maximal-cliques", {}),
    "maximal-bicliques": ("butterfly-counting", {}), "butterfly-counting": ("maximal-bicliques", {}),
    "triangle-counting": ("graphlet-counting", {"graphlet_sizes": [3]}),
    "k-core": ("k-truss", {}), "k-truss": ("k-core", {}),
    "pagerank": ("degree-centrality", {"normalized": False}),
    "degree-centrality": ("pagerank", {}), "community-detection": ("connected-components", {}),
    "connected-components": ("community-detection", {}),
    "breadth-first-search": ("single-source-shortest-paths", {}),
    "single-source-shortest-paths": ("breadth-first-search", {}),
}
