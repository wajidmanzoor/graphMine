"""Application-owned biclique parameters; model context never enumerates sides."""

from collections import Counter
from copy import deepcopy

from .graph_context import identity, infer_bipartition


CONVERT_CHOICE = "Treat these connections as undirected and find the maximal bicliques."
KEEP_CHOICE = "Keep the graph directed and do not run bicliques."


def partition_context(graph):
    types = dict(Counter(row.get("type", "unspecified") for row in graph["vertices"]))
    left = infer_bipartition(graph)
    declared = any("side" in row.get("attributes", {}) for row in graph["vertices"])
    return {
        "entity_types": types,
        "available": left is not None,
        "source": "attributes.side" if declared else "entity_type",
        "left_count": len(left) if left is not None else None,
        "right_count": len(graph["vertices"]) - len(left) if left is not None else None,
        "application_fills_partitions": True,
    }


def planning_cards(cards, inputs):
    """A planner-only contract; the public native card/plan stays unchanged."""
    result = deepcopy(cards)
    types = sorted({
        kind
        for descriptor in inputs.values()
        if descriptor["kind"] == "graph"
        for kind in partition_context(descriptor["data"])["entity_types"]
        if kind != "unspecified"
    })
    for card in result:
        if card["id"] != "maximal-bicliques":
            continue
        for name in ("left_partition", "right_partition"):
            card["parameters"].pop(name, None)
        if types:
            card["parameters"]["entity_type"] = {
                "kind": "string", "required": False, "nullable": False,
                "default": None, "choices": types,
            }
        card["description"] = (
            "Find exact inclusion-maximal bicliques with nonempty sides. "
            "The application fills left_partition and right_partition from the FULL input "
            "after planning. Never list vertex IDs for partitions. Optionally select the "
            "left side's entity_type from the supplied types, or omit it to use declared "
            "attributes.side or the inferred two types. If bipartition.available is true, "
            "the sides are available: do not ask for IDs or repeat a side confirmation. "
            "For directed inputs the application asks permission to create an undirected "
            "copy before validation. Do not invent a conversion operation or parameter."
        )
    return result


def missing_sides():
    return {
        "status": "needs_information", "plan": None, "choices": [],
        "message": "Which records belong on each side? Supply two vertex types with "
        "connections crossing between them, or mark every vertex's side as left or right.",
    }


def complete_partitions(plan, inputs):
    """Fill both sides only from the actual selected snapshot, never its preview."""
    plan = deepcopy(plan)
    directed = set()
    for step in plan["steps"]:
        if step["operation"] != "maximal-bicliques":
            continue
        descriptor = inputs.get(step["input"].get("input"))
        if descriptor is None or descriptor["kind"] != "graph":
            return None, {
                **missing_sides(),
                "message": "Choose a graph snapshot with known sides for the biclique "
                "analysis. The sides of this earlier step's output are not available yet.",
            }, set()
        graph = descriptor["data"]
        preferred = step["parameters"].pop("entity_type", None)
        if any(name in step["parameters"] for name in ("left_partition", "right_partition")):
            # Explicit, user-owned partitions must reach the native validator
            # intact. It checks both sides, complete coverage and crossing edges.
            if graph["graph"]["directed"]:
                directed.add(step["input"]["input"])
            continue
        left = infer_bipartition(graph, preferred)
        if left is None:
            return None, missing_sides(), set()
        left_ids = {identity(value) for value in left}
        step["parameters"].update(
            left_partition=left,
            right_partition=[row["id"] for row in graph["vertices"]
                             if identity(row["id"]) not in left_ids],
        )
        if graph["graph"]["directed"]:
            directed.add(step["input"]["input"])
    return plan, None, directed


def missing_required_parameter(plan, cards, entities=()):
    """Ask for unavailable values; an omitted, identified entity is repairable."""
    by_id = {card["id"]: card for card in cards}
    for step in plan["steps"]:
        specs = by_id[step["operation"]]["parameters"]
        assigned = {identity(step["parameters"][name]) for name, spec in specs.items()
                    if spec["kind"] == "vertex_id" and name in step["parameters"]}
        for name, spec in specs.items():
            if (spec.get("required") and spec.get("default") is None
                    and name not in step["parameters"] and name not in step["bindings"]):
                if spec["kind"] == "vertex_id" and any(
                    entity["input"] == step["input"].get("input")
                    and identity(entity["id"]) not in assigned for entity in entities
                ):
                    # The model saw an actual matching ID in this question.
                    # Preserve the bounded repair for an omitted supplied value.
                    continue
                return {
                    "status": "needs_information", "plan": None,
                    "message": f"What value should I use for {name.replace('_', ' ')}?",
                    "choices": [str(value) for value in spec.get("choices", [])][:4],
                }
    return None
