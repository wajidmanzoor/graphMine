"""Opaque model choices resolve to application-owned native parameter values."""

from copy import deepcopy
import json

import jsonschema

from .analytics_lane_choices import explicit_parameters


VERTEX_LISTS = {"vertices", "sources", "seeds", "start_vertices", "seed_vertices", "vertices_or_seeds",
                "origins", "destinations", "required_vertices", "left_partition", "right_partition"}


def parameter_choices(cards, question, entities=(), lookups=(), selection=None, supplied=None):
    choices = []
    seen = set()

    def add(card, name, value, description):
        # The declared literal schema is checked again before native execution.
        from .analytics_planning import parameter_schema
        try:
            jsonschema.validate(value, parameter_schema(card["parameters"][name]))
        except jsonschema.ValidationError:
            return
        key = (card["id"], name, json.dumps(value, sort_keys=True))
        if key in seen:
            return
        seen.add(key)
        choices.append({"id": f"value_{len(choices)}", "problem": card["id"], "parameter": name,
                        "value": deepcopy(value), "description": description})

    for card in cards:
        stated = explicit_parameters(card, question, entities)
        selected = (supplied or {}).get(card["id"], {})
        if isinstance(selected, dict):
            stated.update(selected)
        for name, spec in card["parameters"].items():
            if "default" in spec:
                add(card, name, spec["default"], f"Use the documented default for {name}.")
            for value in spec.get("choices", spec.get("json_schema", {}).get("enum", [])):
                add(card, name, value, f"Use {value} for {name}.")
            if name in stated:
                add(card, name, stated[name], f"Use the value stated in the question for {name}.")
            if spec["kind"] == "vertex_id" or name in VERTEX_LISTS:
                for entity in entities:
                    value = entity["id"] if spec["kind"] == "vertex_id" else [entity["id"]]
                    add(card, name, value, f"Use {entity.get('label', entity['matched'])} from {entity['input']} for {name}.")
                if name in VERTEX_LISTS:
                    aliases = {entity["input"] for entity in entities}
                    for alias in sorted(aliases):
                        add(card, name, [entity["id"] for entity in entities if entity["input"] == alias],
                            f"Use all entities explicitly named in {alias} for {name}.")
                    if selection and selection.get("vertices") is not None:
                        add(card, name, selection["vertices"], f"Use the complete selected group's vertices for {name}.")
        for lookup in lookups:
            if lookup["problem"] != card["id"]:
                continue
            for name, value in lookup["plan"]["steps"][0]["parameters"].items():
                add(card, name, value, lookup["description"])
    return choices


def constrain_literals(wire, choices):
    wire = deepcopy(wire)
    steps = wire["properties"]["plan"]["anyOf"][0]["properties"]["steps"]
    for position in steps["prefixItems"]:
        for problem in position["oneOf"]:
            props = problem["properties"]
            problem_id = props["problem"]["const"]
            arguments = props["arguments"]
            retained = []
            for argument in arguments.get("items", {}).get("oneOf", []):
                name = argument["properties"]["name"]["const"]
                values = [row["id"] for row in choices if row["problem"] == problem_id and row["parameter"] == name]
                branches = argument["properties"]["value"]["oneOf"]
                branches[:] = [branch for branch in branches if "literal" not in branch["properties"]]
                if values:
                    branches.insert(0, {"type": "object", "additionalProperties": False,
                                       "properties": {"choice": {"enum": values}}, "required": ["choice"]})
                if branches:
                    retained.append(argument)
            arguments["maxItems"] = len(retained)
            if retained:
                arguments["items"] = {"oneOf": retained}
            else:
                arguments.pop("items", None)
    # Clarification wording may be generated, but offered replies come from code.
    labels = list(dict.fromkeys(row["description"][:120] for row in choices))
    wire["properties"]["choices"] = {"type": "array", "maxItems": min(4, len(labels)),
        "items": {"enum": labels} if labels else {"type": "string"}}
    return wire


def resolve_literals(proposal, choices):
    proposal = deepcopy(proposal)
    by_id = {row["id"]: row for row in choices}
    for step in (proposal.get("plan") or {}).get("steps", []):
        for argument in step["arguments"]:
            if "choice" not in argument["value"]:
                continue
            selected = by_id[argument["value"]["choice"]]
            if selected["problem"] != step["problem"] or selected["parameter"] != argument["name"]:
                raise ValueError("A parameter choice belongs to another problem or argument")
            argument["value"] = {"literal": deepcopy(selected["value"])}
    return proposal
