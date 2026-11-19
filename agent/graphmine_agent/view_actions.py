"""Explicit, bounded exploration of immutable saved inputs.

All actions resolve ownership through AnalyticsService, check revisions, and
operate on snapshots. They never connect to a database or alter native results.
"""
from __future__ import annotations

import time
import json
from collections import Counter, defaultdict, deque
from typing import Annotated, Literal

from fastapi import Request
from pydantic import Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _key
from .database import RecordNotFound
from .models import FileInfo, FileRole, StrictModel
from .graph_context import display_name, identity
from .view_data import group_memberships, label_records
from .view_profile import fingerprint, node_type, rows_for

Entity = StrictInt | Annotated[StrictStr, Field(max_length=2048)]
MAX_SCAN = 250000


class ViewRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    index: int | None = Field(default=None, ge=0, strict=True)


class LabelRequest(ViewRequest):
    vertices: list[Entity] = Field(max_length=1000)


class ExpandRequest(ViewRequest):
    vertices: list[Entity] = Field(min_length=1, max_length=50)
    visible: list[Entity] = Field(default_factory=list, max_length=50000)
    offset: int = Field(default=0, ge=0, le=250000)
    limit: int = Field(default=50, ge=1, le=50)
    direction: Literal["out", "in", "both"] = "both"


class PathRequest(ViewRequest):
    source: Entity
    target: Entity
    direction: Literal["out", "both"] = "out"
    max_hops: int = Field(default=50, ge=0, le=200)


class ContextRequest(ViewRequest):
    vertices: list[Entity] = Field(default_factory=list, max_length=2000)
    edges: list[Entity] = Field(default_factory=list, max_length=5000)


def restore_context(service, workflow_id, step, port, body):
    """Restore explicitly saved context identities from the same input snapshot."""
    _, saved, graph = snapshot(service, workflow_id, step, port, body)
    require_input_namespace(saved, port)
    require_graph(graph)
    vertices, edges = {_key(v) for v in body.vertices}, {_key(e) for e in body.edges}
    found_edges = [e for e in graph["edges"] if _key(e.get("id")) in edges]
    # Include endpoints so every restored edge remains an actual input edge.
    vertices.update(_key(e[k]) for e in found_edges for k in ("source", "target"))
    if len(vertices) > 2000:
        raise AnalyticsError("Saved exploration context exceeds 2,000 vertices.", "resource_limit", 413)
    found_vertices = [v for v in graph["vertices"] if _key(v["id"]) in vertices]
    if len(found_vertices) != len(vertices) or len(found_edges) != len(edges):
        raise AnalyticsError("Saved context refers to records outside this input snapshot.", "invalid_view")
    return {"vertices": context_vertices(graph, found_vertices), "edges": found_edges,
            "provenance": {"kind": "saved_input_context", "changes_result": False}}


def merge_context(view, context):
    vertices = {_key(v["id"]): v for v in view["vertices"]}
    edges = {_key(e["id"]): e for e in view["edges"]}
    for vertex in context["vertices"]:
        vertices.setdefault(_key(vertex["id"]), {**vertex, "view": {"display_name": vertex.get("label", str(vertex["id"])), "role": "context", "result": False}})
    for edge in context["edges"]:
        edges.setdefault(_key(edge["id"]), {**edge, "view": {"edge_role": "context", "result": False}})
    return {**view, "vertices": list(vertices.values()), "edges": list(edges.values()), "exploration_context": context["provenance"]}


class SelectionRequest(ViewRequest):
    vertices: list[Entity] = Field(min_length=1, max_length=50000)


class ProjectionRequest(ViewRequest):
    method: Literal["pca"] = "pca"
    seed: int = Field(default=0, ge=0, le=2147483647)
    cached_only: bool = False


class CompareRequest(ViewRequest):
    workflow_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1, strict=True)
    step: str = Field(min_length=1, max_length=128)
    port: str = Field(min_length=1, max_length=128)
    other_index: int | None = Field(default=None, ge=0)
    allow_different_inputs: bool = False


def snapshot(service, workflow_id, step, port, body):
    from .result_views import input_graph
    record = service.get(workflow_id)
    if record["revision"] != body.expected_revision:
        raise AnalyticsError("This analysis revision changed. Reopen its results.", "revision_conflict", 409)
    saved = service._saved(workflow_id, step=step, expected_revision=body.expected_revision)["result"]
    if port not in saved.get("ports", {}):
        raise RecordNotFound("No such output port")
    return record, saved, input_graph(service, record, step)


def require_graph(graph):
    if graph is None:
        raise AnalyticsError("This saved input is not a graph.", "invalid_view")
    if len(graph["vertices"]) + len(graph["edges"]) > MAX_SCAN:
        raise AnalyticsError("This exploration exceeds its 250,000-record scan budget. Run a bounded calculation on a smaller input.", "resource_limit", 413)


def context_vertices(graph, vertices):
    """Context uses the same names, types and input-degree definition as members."""
    degree = Counter(identity(edge[end]) for edge in graph["edges"] for end in ("source", "target"))
    return [{**v, "label": display_name(v), "view": {
        "display_name": display_name(v), "vertex_type": node_type(v),
        "degree": degree[identity(v["id"])], "result": False, "role": "context",
    }} for v in vertices]


def labels(service, workflow_id, step, port, body):
    from .result_views import default_index, focus_graph
    _, saved, graph = snapshot(service, workflow_id, step, port, body)
    if saved["ports"][port]["type"] in {"graph", "pattern_collection"}:
        graph = focus_graph(graph, saved, port, default_index(saved["ports"][port], body.index))[0]
    if saved["ports"][port]["type"] == "cross_graph_mapping":
        raise AnalyticsError("Correspondences use separate input namespaces.", "invalid_view")
    require_graph(graph)
    return {"labels": label_records(graph, body.vertices, 1000), "revision": body.expected_revision}


def expand(service, workflow_id, step, port, body):
    _, saved, graph = snapshot(service, workflow_id, step, port, body)
    require_input_namespace(saved, port)
    require_graph(graph)
    seeds, visible = {_key(v) for v in body.vertices}, {_key(v) for v in body.visible}
    available = {_key(v["id"]): v for v in graph["vertices"]}
    if not seeds <= available.keys():
        raise AnalyticsError("A selected entity is absent from this saved input.", "invalid_view")
    candidates = set()
    directed = graph.get("graph", {}).get("directed", False)
    for edge in graph["edges"]:
        a, b = _key(edge["source"]), _key(edge["target"])
        if a in seeds and (not directed or body.direction in {"out", "both"}):
            candidates.add(b)
        if b in seeds and (not directed or body.direction in {"in", "both"}):
            candidates.add(a)
    candidates -= visible | seeds
    ordered = [key for key in available if key in candidates]
    new = ordered[body.offset:body.offset + body.limit]
    shown = visible | seeds | set(new)
    edges = [e for e in graph["edges"] if _key(e["source"]) in shown and _key(e["target"]) in shown and (_key(e["source"]) in set(new) or _key(e["target"]) in set(new))]
    return {"graph": graph["graph"], "vertices": context_vertices(graph, [available[k] for k in new]), "edges": edges[:5000],
            "total_neighbors": len(ordered), "remaining": max(0, len(ordered) - body.offset - len(new)),
            "edges_truncated": len(edges) > 5000, "revision": body.expected_revision,
            "provenance": {"kind": "saved_input_neighbors", "direction": body.direction, "changes_result": False}}


def shortest_connection(service, workflow_id, step, port, body):
    _, saved, graph = snapshot(service, workflow_id, step, port, body)
    require_input_namespace(saved, port)
    require_graph(graph)
    vertices = {_key(v["id"]): v for v in graph["vertices"]}
    source, target = _key(body.source), _key(body.target)
    if source not in vertices or target not in vertices:
        raise AnalyticsError("Both entities must belong to the saved input.", "invalid_view")
    adjacency = defaultdict(list)
    directed = graph.get("graph", {}).get("directed", False) and body.direction == "out"
    deadline = time.monotonic() + 2
    for edge in graph["edges"]:
        a, b = _key(edge["source"]), _key(edge["target"])
        adjacency[a].append((b, edge))
        if not directed:
            adjacency[b].append((a, edge))
    queue, previous = deque([(source, 0)]), {source: None}
    while queue and target not in previous:
        if time.monotonic() > deadline:
            raise AnalyticsError("The connection search reached its two-second budget.", "resource_limit", 413)
        vertex, depth = queue.popleft()
        if depth >= body.max_hops:
            continue
        for neighbor, edge in adjacency[vertex]:
            if neighbor not in previous:
                previous[neighbor] = (vertex, edge)
                queue.append((neighbor, depth + 1))
    selected, edges = [], []
    if target in previous:
        cursor = target
        while cursor is not None:
            selected.append(vertices[cursor])
            link = previous[cursor]
            if link is None:
                break
            cursor, edge = link
            edges.append(edge)
        selected.reverse(); edges.reverse()
    return {"graph": graph["graph"], "vertices": context_vertices(graph, selected), "edges": edges, "found": target in previous,
            "revision": body.expected_revision, "max_hops": body.max_hops,
            "provenance": {"kind": "exploration_shortest_hop_path", "weights_used": False, "direction": body.direction, "changes_result": False},
            "note": "Shortest connection by number of edges in the saved input; weights are ignored. This is a separate exploration result."}


def meta_graph(service, workflow_id, step, port, body):
    _, saved, graph = snapshot(service, workflow_id, step, port, body)
    require_graph(graph)
    value = saved["ports"][port]
    if value["type"] not in {"vertex_partition", "vertex_groups"}:
        raise AnalyticsError("A meta-graph requires recorded group membership.", "invalid_view")
    rows, total = rows_for(value, MAX_SCAN)
    if total > MAX_SCAN:
        raise AnalyticsError("Group membership exceeds the exploration budget.", "resource_limit", 413)
    try:
        groups = group_memberships(value, rows)
    except ValueError as error:
        raise AnalyticsError(str(error), "resource_limit", 413) from error
    if any(len(member) > 1 for member in groups.values()):
        raise AnalyticsError("These groups overlap. Use the membership view to avoid double-counting connections.", "invalid_view")
    counts = Counter(_key(member[0]) for member in groups.values())
    labels_by_key = {_key(member[0]): member[0] for member in groups.values()}
    edge_counts = Counter()
    for edge in graph["edges"]:
        a, b = groups.get(identity(edge["source"])), groups.get(identity(edge["target"]))
        if a and b:
            pair = (_key(a[0]), _key(b[0]))
            if not graph["graph"].get("directed"):
                pair = tuple(sorted(pair))
            edge_counts[pair] += 1
    largest = dict(counts.most_common(2000))
    edges = [{"id": "meta-edge-" + str(i), "source": "group:" + a, "target": "group:" + b, "weight": count} for i, ((a, b), count) in enumerate(edge_counts.items()) if a in largest and b in largest]
    return {"graph": {"id": "group-meta-graph", "directed": graph["graph"].get("directed", False)},
            "vertices": [{"id": "group:" + key, "label": "Group " + str(labels_by_key[key]), "attributes": {"group": labels_by_key[key], "size": size}} for key, size in largest.items()],
            "edges": edges[:5000], "vertex_count": len(counts), "edge_count": len(edge_counts),
            "vertices_truncated": len(largest) < len(counts), "edges_truncated": len(edges) > 5000,
            "revision": body.expected_revision, "complete": value.get("complete", False),
            "note": "Each node represents a recorded group. Edge weight counts saved input edges, including parallel records. Self-loops count internal connections."}


def compare(service, workflow_id, step, port, body):
    from .result_views import result_view
    record, saved, graph = snapshot(service, workflow_id, step, port, body)
    other = ViewRequest(expected_revision=body.revision, index=body.other_index)
    right_record, right_saved, right_graph = snapshot(service, body.workflow_id, body.step, body.port, other)
    same_input = fingerprint(graph) == fingerprint(right_graph)
    same_operation = saved.get("operation") == right_saved.get("operation")
    if not (same_input and same_operation) and not body.allow_different_inputs:
        raise AnalyticsError("Automatic comparison requires the same saved input and operation. Choose an explicit comparison to inspect different runs.", "incompatible_views", 409)
    left = result_view(service, workflow_id, step, port, index=body.index, expected_revision=body.expected_revision)
    right = result_view(service, body.workflow_id, body.step, body.port, index=body.other_index, expected_revision=body.revision)
    a, b = {_key(v["id"]): v["id"] for v in left["vertices"]}, {_key(v["id"]): v["id"] for v in right["vertices"]}
    # IDs in independently generated/coarsened namespaces do not establish a
    # correspondence, even when the source input happens to match.
    comparable = same_input and all(r.get("operation") not in {"graph-coarsening", "graph-condensation", "knn-graph"} and r["ports"][p]["type"] != "cross_graph_mapping" for r, p in ((saved, port), (right_saved, body.port)))
    diff = {"left_only": [a[k] for k in sorted(a.keys() - b.keys())], "right_only": [b[k] for k in sorted(b.keys() - a.keys())], "both": [a[k] for k in sorted(a.keys() & b.keys())]} if comparable else None
    edge_diff = None
    if comparable:
        a_edges, b_edges = ({_key(e["id"]): e["id"] for e in v["edges"]} for v in (left, right))
        edge_diff = {"left_only": [a_edges[k] for k in sorted(a_edges.keys() - b_edges.keys())], "right_only": [b_edges[k] for k in sorted(b_edges.keys() - a_edges.keys())], "both": [a_edges[k] for k in sorted(a_edges.keys() & b_edges.keys())]}
    transitions, skipped = [], 0
    if comparable and all(r["ports"][p]["type"] in {"vertex_groups", "vertex_partition"} for r, p in ((saved, port), (right_saved, body.port))):
        try:
            memberships = [group_memberships(r["ports"][p], rows_for(r["ports"][p])[0]) for r, p in ((saved, port), (right_saved, body.port))]
            counts = Counter()
            for key in memberships[0].keys() & memberships[1].keys():
                x, y = memberships[0][key], memberships[1][key]
                if len(x) == len(y) == 1:
                    counts[(_key(x[0]), _key(y[0]))] += 1
                else:
                    skipped += 1
            transitions = [{"source": json.loads(x), "target": json.loads(y), "count": count} for (x, y), count in counts.most_common(1000)]
        except ValueError:
            skipped = None
    return {"left": left, "right": right, "same_input": same_input, "comparable_entities": comparable, "same_operation": same_operation, "diff": diff, "edge_diff": edge_diff, "membership_transitions": transitions, "ambiguous_memberships": skipped,
            "diff_complete": not any(v.get("vertices_truncated") or v.get("edges_truncated") or not v.get("complete") for v in (left, right)),
            "parameters": [next((s for s in r["validation"]["plan"]["steps"] if s["id"] == key), {}) for r, key in ((record, step), (right_record, body.step))]}


def require_input_namespace(saved, port):
    typ = saved["ports"][port]["type"]
    if typ in {"pattern_collection", "cross_graph_mapping", "relation_embeddings"} or typ == "graph" and saved.get("operation") in {"graph-coarsening", "graph-condensation", "knn-graph"}:
        raise AnalyticsError("This view uses a different entity namespace. Open its source input before exploring neighbors or creating a selection.", "invalid_view")


def selection_input(runtime, workflow_id, step, port, body):
    record, saved, graph = snapshot(runtime.analytics, workflow_id, step, port, body)
    require_input_namespace(saved, port)
    require_graph(graph)
    chosen = {_key(v) for v in body.vertices}
    vertices = [v for v in graph["vertices"] if _key(v["id"]) in chosen]
    if len(vertices) != len(chosen):
        raise AnalyticsError("A selected entity is absent from the saved input.", "invalid_view")
    selected = {**graph, "vertices": vertices, "edges": [e for e in graph["edges"] if _key(e["source"]) in chosen and _key(e["target"]) in chosen]}
    provenance = {"kind": "graph", "source": {"type": "saved_view_selection", "workflow_id": workflow_id, "revision": body.expected_revision,
                  "step": step, "port": port, "input_fingerprint": fingerprint(graph), "vertices": body.vertices,
                  "selection_semantics": "vertex-induced subgraph of the immediate saved input"}}
    file = runtime.graph_store.ingest(session_id=record["session_id"], role=FileRole.graph, filename="selected-entities.json", content=json.dumps(selected, ensure_ascii=False).encode(), media_type="application/json", provenance=provenance)
    from .analytics_eligibility import input_profile
    return {"file": FileInfo.from_stored(file).model_dump(mode="json"), "selection_profile": input_profile({"kind": "graph", "data": selected}),
            "note": "A separate input was saved with the selected entities and their connections. The original analysis is unchanged."}


def enumeration_input(runtime, workflow_id, step, port, body):
    _, saved, graph = snapshot(runtime.analytics, workflow_id, step, port, body)
    require_graph(graph)
    operation = saved.get("operation")
    options = {"maximal-biclique-counting": ("maximal-bicliques", {}), "triangle-counting": ("triangle-counting", {"mode": "enumerate"}), "k-cliques": ("k-cliques", {"mode": "enumerate"}), "motif-counting": ("motif-counting", {"list_instances": True}), "graphlet-counting": ("graphlet-counting", {"list_instances": True}), "temporal-motifs": ("temporal-motifs", {"list_instances": True})}
    if operation not in options:
        raise AnalyticsError("This metric does not declare a corresponding enumeration calculation.", "invalid_view")
    if len(graph["vertices"]) > 50000:
        raise AnalyticsError("This follow-up exceeds the 50,000-vertex input-copy budget.", "resource_limit", 413)
    target, overrides = options[operation]
    result = selection_input(runtime, workflow_id, step, port, SelectionRequest(expected_revision=body.expected_revision, vertices=[v["id"] for v in graph["vertices"]]))
    result.update(operation=target, parameters={**(saved.get("parameters", {}) if target == operation else {}), **overrides})
    return result


def project_embedding(service, workflow_id, step, port, body):
    record, saved, _ = snapshot(service, workflow_id, step, port, body)
    if saved["ports"][port]["type"] not in {"vertex_embeddings", "relation_embeddings", "entity_embeddings"}:
        raise AnalyticsError("PCA requires a saved embedding output.", "invalid_view")
    rows, total = rows_for(saved["ports"][port], 5001)
    if total > 5000:
        raise AnalyticsError("PCA previews are limited to 5,000 retained embeddings. Choose a smaller calculation.", "resource_limit", 413)
    key = fingerprint({"result": saved["ports"][port], "method": body.method, "seed": body.seed, "implementation": "pca-full-normalized-v2"})
    path = service._directory(record) / f"view-projection-{key}.json" if hasattr(service, "_directory") else None
    if path is not None and path.is_file():
        return service._read_result(path)
    if body.cached_only:
        raise RecordNotFound("The saved projection is unavailable. Calculate it explicitly to create a new display artifact.")
    import numpy as np
    from sklearn.decomposition import PCA
    from threadpoolctl import threadpool_limits
    vectors = [r.get("values", r.get("embedding", [])) for r in rows]
    if not vectors or not all(isinstance(v, list) and len(v) == len(vectors[0]) for v in vectors) or not 2 <= len(vectors[0]) <= 256 or len(rows) < 2:
        raise AnalyticsError("PCA needs at least two equal-length vectors with 2–256 dimensions.", "invalid_view")
    try:
        values = np.asarray(vectors, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalyticsError("PCA requires finite numeric coordinates.", "invalid_view") from exc
    if not np.isfinite(values).all():
        raise AnalyticsError("PCA requires finite coordinates.", "invalid_view")
    # Normalize extreme magnitudes before SVD without changing PCA directions.
    magnitude = float(np.max(np.abs(values))) or 1.0
    with threadpool_limits(limits=1):
        model = PCA(n_components=2, svd_solver="full", random_state=body.seed)
        coordinates = model.fit_transform(values / magnitude)
    variance = [float(v) if np.isfinite(v) else 0 for v in model.explained_variance_ratio_]
    result = {"id": key, "method": "pca", "seed": body.seed, "points": [{"index": i, "entity": r.get("vertex", r.get("entity", r.get("relation"))), "x": float(p[0]), "y": float(p[1])} for i, (r, p) in enumerate(zip(rows, coordinates))],
            "explained_variance_ratio": variance, "revision": body.expected_revision,
            "provenance": {"input_fingerprint": fingerprint(vectors), "changes_result": False, "implementation": "scikit-learn PCA/full"},
            "coordinate_scale": magnitude,
            "note": "PCA is a separate display projection of the retained vectors, normalized by their largest magnitude. Distances may differ from the original embedding."}
    if path is not None:
        service._write(path, result)
    return result


def register_view_action_routes(router):
    path = "/workflows/{workflow_id}/steps/{step}/ports/{port}/view"

    @router.get("/visualization/map-config")
    async def map_config(request: Request):
        settings = request.app.state.runtime.settings
        url = settings.map_tile_url or ""
        # Deployments may reverse-proxy their licensed provider. Keeping tile
        # requests same-origin preserves the existing content security policy.
        enabled = url.startswith("/tiles/") and not any(c in url for c in ("\\", "..", "?", "#")) and all(token in url for token in ("{z}", "{x}", "{y}"))
        return {"enabled": enabled, "tile_url": url if enabled else None, "attribution": settings.map_attribution if enabled else "", "note": "Maps require a configured tile provider. Coordinate plots work without one."}

    @router.post(path + "/labels")
    async def read_labels(workflow_id: str, step: str, port: str, body: LabelRequest, request: Request):
        return await run_in_threadpool(labels, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/neighbors")
    async def expand_neighbors(workflow_id: str, step: str, port: str, body: ExpandRequest, request: Request):
        return await run_in_threadpool(expand, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/context")
    async def saved_context(workflow_id: str, step: str, port: str, body: ContextRequest, request: Request):
        return await run_in_threadpool(restore_context, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/connection")
    async def connection(workflow_id: str, step: str, port: str, body: PathRequest, request: Request):
        return await run_in_threadpool(shortest_connection, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/meta-graph")
    async def aggregate_groups(workflow_id: str, step: str, port: str, body: ViewRequest, request: Request):
        return await run_in_threadpool(meta_graph, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/compare")
    async def compare_runs(workflow_id: str, step: str, port: str, body: CompareRequest, request: Request):
        return await run_in_threadpool(compare, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/selection", status_code=201)
    async def save_selection(workflow_id: str, step: str, port: str, body: SelectionRequest, request: Request):
        from .analytics_eligibility import eligible
        runtime = request.app.state.runtime
        response = await run_in_threadpool(selection_input, runtime, workflow_id, step, port, body)
        profile = response.pop("selection_profile")
        cards = (await runtime.analytics.capabilities())["operations"]
        direction = "directed" if profile["directed"] else "undirected"
        response["compatible_operations"] = [card["id"] for card in cards if eligible(card, profile)[0]
                                             and card["requirements"]["direction"] in {"either", direction}]
        return response

    @router.post(path + "/projection")
    async def projection(workflow_id: str, step: str, port: str, body: ProjectionRequest, request: Request):
        return await run_in_threadpool(project_embedding, request.app.state.runtime.analytics, workflow_id, step, port, body)

    @router.post(path + "/enumeration-input", status_code=201)
    async def prepare_enumeration(workflow_id: str, step: str, port: str, body: ViewRequest, request: Request):
        return await run_in_threadpool(enumeration_input, request.app.state.runtime, workflow_id, step, port, body)
