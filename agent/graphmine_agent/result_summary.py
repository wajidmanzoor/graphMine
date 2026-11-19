"""Server-owned result headlines and metric cards from recorded facts."""
from .analytics_answers import build_facts, result_sentence
from .graph_context import identity


def summary(view, saved, record, question=None):
    facts = view["profile_facts"]
    source = facts.get("input") or {}
    witness = facts.get("witness") or {}
    collection = facts.get("collection") or {}
    kind = view["profile"]["kind"]
    count_only = view["view_spec"]["view"] == "metric"
    operation = saved.get("operation", "Analysis")
    sides = view.get("bipartite_names", [])
    step = view["step"]
    sentence = result_sentence(saved, sides)
    if not sentence:
        labels = {identity(row["id"]): row["label"] for row in view.get("labels", [])}
        entries = build_facts({"steps": {step: {"status": "completed", "result": saved}}}, {}, labels, {step: sides})
        sentence = next((row["text"] for row in entries if row["kind"] != "quality"), "The calculation is complete.")
    cards = []
    def add(label, value, note=None):
        if value is not None:
            cards.append({"label": label, "value": value, "note": note})
    total = source.get("vertices")
    covered = collection.get("covered_vertices")
    if count_only:
        port = saved["ports"][view["port"]]
        add("Count" if "count" in operation else view["profile"]["title"], port["value"], f"out of {total} vertices" if total is not None else None)
    elif kind == "bipartite":
        add("Count", collection.get("count", facts["items"]))
        pair = collection.get("largest_sides")
        add("Largest", f"{pair[0]} × {pair[1]}" if pair else None, "By total members; ties use connection count")
        add("Typical size", collection.get("median_members"), "Median number of members")
        add("Coverage", f"{covered} / {total}" if covered is not None else None, "Distinct entities in any retained biclique")
    elif kind in {"groups", "partition"}:
        add("Groups", facts["groups"]["count"])
        add("Largest group", max((row["size"] for row in facts["groups"]["sizes"]), default=0))
        raw = saved.get("result", {})
        if raw.get("quality_function") == "modularity":
            add("Modularity", round(raw["quality_score"], 4) if raw.get("quality_score") is not None else None)
        add("Coverage", f"{covered} / {total}" if covered is not None else None)
    elif kind == "subgraph":
        raw = saved.get("result", {})
        if operation == "densest-subgraph" and raw.get("clique_order") == 2 and not saved.get("parameters", {}).get("weight_mode"):
            density = raw.get("density")
            base = source.get("edges", 0) / total if total else 0
            add("Density", f"{density:.4g} vs {base:.4g}" if isinstance(density, (int, float)) else None, "Connections per vertex: result vs input")
        else:
            a, b = witness.get("density"), source.get("density")
            add("Connection density", f"{a:.4g} vs {b:.4g}" if a is not None and b is not None else None, "Distinct non-loop connections / possible connections: result vs input")
        add("Vertices", f"{witness.get('vertices', view['vertex_count'])} / {total}" if total is not None else view["vertex_count"])
        add("Connections", witness.get("edges", view["edge_count"]))
    else:
        add("Items", facts["items"])
        if view["graph_available"]:
            add("Vertices", view["vertex_count"])
            add("Connections", view["edge_count"])
    return {"title": question or record.get("question") or operation.replace("-", " ").capitalize(),
            "sentence": sentence, "metrics": cards, "count_only": count_only,
            "quality": saved.get("quality"), "device": saved.get("backend", {}).get("device"),
            "validated": bool(record.get("validation", {}).get("workflow_hash"))}
