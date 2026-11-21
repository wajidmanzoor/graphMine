"""Complete, input-scoped bipartitions for the bounded analytics planner."""

from copy import deepcopy

from .analytics import AnalyticsError
from .graph_context import infer_bipartition

def prepare_bipartitions(inputs):
    """Offer only two typed sides verified against every vertex and edge."""
    prepared = {}
    for alias, descriptor in inputs.items():
        if descriptor["kind"] != "graph":
            continue
        graph = descriptor["data"]
        if graph["graph"].get("directed") or infer_bipartition(graph) is None:
            continue
        groups = {}
        for vertex in graph["vertices"]:
            groups.setdefault(vertex["type"], []).append(vertex["id"])
        prepared[alias] = groups
    return prepared


def resolve_partitions(plan, prepared):
    """Expand planner references without changing literals or graph scope."""
    resolved = deepcopy(plan)
    for step in resolved["steps"]:
        if step["operation"] != "maximal-bicliques":
            continue
        for name in ("left_partition", "right_partition"):
            value = step["parameters"].get(name)
            if not isinstance(value, dict) or "input_partition" not in value:
                continue
            selection = value["input_partition"]
            alias, kind = selection["input"], selection["type"]
            if step["input"] != {"input": alias}:
                raise AnalyticsError(
                    "A prepared partition must use the same original graph as the biclique step. "
                    "Do not reuse its membership on a different or transformed graph."
                )
            if alias not in prepared or kind not in prepared[alias]:
                raise AnalyticsError("The requested complete input partition is unavailable.")
            step["parameters"][name] = list(prepared[alias][kind])
    return resolved
