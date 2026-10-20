"""Result-specific presentation contracts and views of saved evidence.

This module selects recorded witnesses, never runs a graph algorithm. Full
saved inputs/results are resolved before applying browser preview limits.
"""

from __future__ import annotations

import copy
import itertools
from collections import defaultdict

from fastapi import Query, Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _key
from .database import RecordNotFound

# Every native operation has an intentional presentation contract. Adding an
# algorithm requires adding a contract (the catalog coverage test enforces it).
_PROFILES = [
    (
        "path",
        "Path witness",
        ["path", "path_steps", "table"],
        "query-paths top-k-critical-paths bounded-paths-cycles temporal-paths random-walks",
        ["rows", "paths", "sequences", "walks"],
    ),
    (
        "path_tree",
        "Predecessor tree / selected path",
        ["path", "distance_table", "table"],
        "single-source-shortest-paths widest-paths breadth-first-search",
        ["distances", "paths"],
    ),
    (
        "subgraph",
        "Returned subgraph",
        ["subgraph", "membership", "table"],
        "densest-subgraph densest-k-subgraph seeded-local-community k-core",
        ["vertices", "scores"],
    ),
    (
        "groups",
        "One returned group",
        ["group", "group_sizes", "membership", "table"],
        "maximal-cliques maximum-clique k-cliques quasi-cliques overlapping-communities connected-components biconnected-components triangle-counting dynamic-triangle-counting",
        ["groups", "inserted", "deleted", "vertices"],
    ),
    (
        "partition",
        "Partition overview",
        ["partition", "group_sizes", "membership", "table"],
        "community-detection balanced-partitioning signed-balance hypergraph-partitioning",
        ["partition", "groups"],
    ),
    (
        "bipartite",
        "Returned biclique",
        ["bipartite", "membership", "table"],
        "maximal-bicliques",
        ["bicliques"],
    ),
    (
        "edges",
        "Returned edges",
        ["edges", "edge_table", "table"],
        "spanning-tree-forest group-steiner-tree weighted-matching bipartite-matching k-truss neighborhood-sampling edge-filter",
        ["edges"],
    ),
    (
        "vertices",
        "Returned vertices",
        ["selected_vertices", "membership", "table"],
        "node-lookup neighbors common-neighbors maximal-independent-set maximum-independent-set minimum-vertex-cover influence-maximization",
        ["vertices"],
    ),
    (
        "scores",
        "Scores on the input graph",
        ["scores", "ranked_bars", "table"],
        "pagerank degree-centrality betweenness-centrality personalized-pagerank graph-aggregate butterfly-counting graph-signal-denoising graph-anomalies",
        ["scores", "signal", "ranking"],
    ),
    (
        "graph",
        "Returned graph",
        ["graph", "membership", "table"],
        "query-subgraph induced-subgraph maximum-common-subgraph graph-coarsening spectral-sparsification knn-graph graph-condensation",
        ["graph"],
    ),
    (
        "patterns",
        "One returned pattern",
        ["pattern", "support", "table"],
        "frequent-subgraphs single-graph-frequent-subgraphs",
        ["patterns"],
    ),
    (
        "instances",
        "One recorded occurrence",
        ["occurrence", "membership", "table"],
        "subgraph-isomorphism motif-counting graphlet-counting temporal-motifs",
        ["matches", "instances"],
    ),
    (
        "flow",
        "Positive flow and cut",
        ["flow", "cut", "edge_table", "table"],
        "max-flow-min-cut",
        ["vertices", "value"],
    ),
    (
        "pairs",
        "Pair results",
        ["pair_table", "pair_matrix", "table"],
        "many-source-shortest-paths transitive-closure simrank link-prediction entity-resolution",
        ["distances", "pairs", "candidates"],
    ),
    (
        "mapping",
        "Correspondence table",
        ["mapping_table", "table"],
        "graph-edit-distance network-alignment",
        ["mapping", "edits", "distance"],
    ),
    (
        "embedding",
        "Embedding coordinates",
        ["embedding", "table"],
        "node-embedding knowledge-graph-embedding",
        ["embeddings", "entities", "relations"],
    ),
    (
        "predictions",
        "Predicted values",
        ["prediction_table", "table"],
        "node-learning graph-learning hypergraph-node-learning",
        ["predictions", "metrics"],
    ),
    (
        "locations",
        "Estimated locations",
        ["coordinates", "confidence", "table"],
        "graph-geolocation",
        ["locations", "confidence"],
    ),
    (
        "positions",
        "Computed layout",
        ["coordinates", "table"],
        "force-directed-layout",
        ["positions"],
    ),
    (
        "ordered",
        "Recorded order",
        ["ordered_list", "table"],
        "topological-sort",
        ["vertices"],
    ),
    (
        "colors",
        "Vertex coloring",
        ["color_classes", "table"],
        "vertex-coloring",
        ["colors", "scores"],
    ),
    (
        "intervals",
        "Persistence barcode",
        ["barcode", "table"],
        "persistent-homology",
        ["intervals"],
    ),
    (
        "samples",
        "Sample distribution",
        ["histogram", "table"],
        "null-model-significance",
        ["samples"],
    ),
    (
        "spectrum",
        "Eigenvalue spectrum",
        ["spectrum", "table"],
        "laplacian-eigenpairs",
        ["eigenpairs"],
    ),
    ("scalar", "Count", ["metric", "table"], "maximal-biclique-counting", ["count"]),
]
PROFILES = {
    operation: {
        "kind": kind,
        "title": title,
        "blocks": blocks,
        "preferred_ports": ports,
    }
    for kind, title, blocks, operations, ports in _PROFILES
    for operation in operations.split()
}


def profile(operation):
    return copy.deepcopy(
        PROFILES.get(
            operation,
            {
                "kind": "table",
                "title": "Recorded output",
                "blocks": ["table"],
                "preferred_ports": [],
            },
        )
    )


def input_graph(service, record, step_id, seen=None):
    """Resolve the actual immediate graph input, including derived graphs."""
    seen = set() if seen is None else seen
    if step_id in seen:
        raise AnalyticsError("Cyclic saved input references", "data_integrity", 409)
    seen.add(step_id)
    steps = {s["id"]: s for s in record["validation"]["plan"]["steps"]}
    ref = steps.get(step_id, {}).get("input", {})
    if "input" in ref:
        data = service._read_result(service._directory(record) / "inputs.json")
        source = data.get(ref["input"], {})
        return source.get("data") if source.get("kind") == "graph" else None
    if "step" in ref:
        ports = service._saved(record["id"], step=ref["step"])["result"]["ports"]
        port = ports.get(ref.get("port"), {})
        if port.get("type") == "graph":
            return port["value"]
        if (
            port.get("type") == "pattern_collection"
            and ref.get("select", {}).get("kind") == "pattern_graph"
        ):
            return port["value"][ref["select"]["index"]]["pattern"]
    return None


def source_files(record, step_id):
    steps = {s["id"]: s for s in record["validation"]["plan"]["steps"]}
    for _ in steps:
        if steps.get(step_id, {}).get("operation") in {
            "graph-coarsening",
            "graph-condensation",
            "knn-graph",
            "frequent-subgraphs",
            "single-graph-frequent-subgraphs",
        }:
            return []
        ref = steps.get(step_id, {}).get("input", {})
        if ref.get("select", {}).get("kind") == "pattern_graph":
            return []
        if "input" in ref:
            source = record.get("input_files", {}).get(ref["input"], {})
            return [source["file_id"]] if source.get("file_id") else []
        step_id = ref.get("step")
    return []


def _members(row):
    if isinstance(row, list):
        return [
            v["data_vertex"] if isinstance(v, dict) else v
            for v in row
            if type(v) in (int, str) or isinstance(v, dict) and "data_vertex" in v
        ]
    if isinstance(row, dict):
        if isinstance(row.get("vertices"), list):
            return _members(row["vertices"])
        if "left" in row and "right" in row and isinstance(row["left"], list):
            return row["left"] + row["right"]
        if isinstance(row.get("mapping"), dict):
            return list(row["mapping"].values())
        return [row[key] for key in ("vertex", "source", "target") if key in row]
    return [row] if type(row) in (int, str) else []


def view_items(port):
    value = port.get("value")
    if isinstance(value, list):
        return value
    if port.get("type") in {"motif_instances", "graphlet_instances"} and isinstance(
        value, dict
    ):
        return [
            {"pattern": name, "vertices": row}
            for name in sorted(value)
            for row in value[name]
        ]
    return []


def default_index(port, index):
    if (
        index is None
        and port.get("type")
        in {
            "vertex_groups",
            "bipartite_groups",
            "pattern_collection",
            "vertex_mappings",
            "motif_instances",
            "graphlet_instances",
            "path_set",
            "temporal_path_table",
            "edge_sequence_collection",
            "walk_sample",
            "temporal_occurrence_collection",
        }
        and view_items(port)
    ):
        return 0
    if (
        index is None
        and port.get("type") == "table"
        and any(
            isinstance(r, dict) and isinstance(r.get("edges"), list)
            for r in view_items(port)
        )
    ):
        return 0
    return index


def _edge_witness(graph, rows, *, maximize=False):
    """Select recorded endpoint witnesses without inventing parallel edges."""
    available = defaultdict(list)
    directed = graph["graph"].get("directed", False)
    for edge in graph["edges"]:
        pair = (_key(edge["source"]), _key(edge["target"]))
        available[pair].append(edge)
        if not directed:
            available[pair[::-1]].append(edge)
    result = []
    by_id = {_key(e["id"]): e for e in graph["edges"]}
    for row in rows:
        if type(row) in (str, int):
            if _key(row) in by_id:
                result.append(by_id[_key(row)])
        elif isinstance(row, dict) and "source" in row and "target" in row:
            identity = row.get("id", row.get("edge"))
            if identity is not None and _key(identity) in by_id:
                result.append(by_id[_key(identity)])
                continue
            candidates = available[(_key(row["source"]), _key(row["target"]))]
            if "weight" in row:
                candidates = [
                    e for e in candidates if e.get("weight", 1) == row["weight"]
                ]
            if candidates:
                result.append(
                    (max if maximize else min)(
                        candidates, key=lambda e: e.get("weight", 1)
                    )
                )
    return list({_key(e["id"]): e for e in result}.values())


def focus_graph(graph, result, port_name, index=None):
    """Return a full witness graph and presentation note before UI truncation."""
    spec = profile(result.get("operation"))
    kind = spec["kind"]
    ports = result.get("ports", {})
    port = ports.get(port_name, {})
    value, typ = port.get("value"), port.get("type")
    rows = view_items(port)
    index = default_index(port, index)
    if index is not None and not 0 <= index < len(rows):
        raise AnalyticsError("No result at that position", "invalid_selection")
    if typ == "graph":
        return (
            value,
            "Returned graph",
            [v["id"] for v in value["vertices"]],
            [e["id"] for e in value["edges"]],
        )
    if typ == "pattern_collection":
        row = value[index or 0] if value else {}
        return (
            row.get("pattern"),
            "Pattern-local IDs; source enrichment requires an occurrence mapping.",
            [],
            [],
        )
    if not graph or not isinstance(graph.get("vertices"), list):
        return None, "This output has no source graph representation.", [], []
    chosen = rows[index] if index is not None else rows[0] if rows else None
    vertices, edges = None, None
    note = spec["title"]
    if kind != "flow" and typ in (
        "scalar",
        "rational_scalar",
        "numeric_sample",
        "persistence_intervals",
        "eigenpairs",
        "model_state",
        "learning_metrics",
    ):
        return (
            None,
            "Recorded values; no graph witness is present in this output.",
            [],
            [],
        )
    if typ == "cross_graph_mapping":
        return (
            None,
            "Correspondences use separate input namespaces; inspect the mapping table.",
            [],
            [],
        )
    if kind == "flow":
        flows = [
            r for r in result.get("result", {}).get("flows", []) if r.get("flow", 0) > 0
        ]
        edges = _edge_witness(graph, flows)
        vertices = [r[k] for r in flows for k in ("source", "target")]
        note = (
            "Edges carrying positive flow; the cut and capacities are shown separately."
        )
    elif typ in (
        "vertex_groups",
        "bipartite_groups",
        "motif_instances",
        "graphlet_instances",
        "vertex_mappings",
    ):
        vertices = _members(chosen) if chosen is not None else []
        note = "Selected recorded group or occurrence; edges are the input connections between its members."
    elif typ == "vertex_partition":
        if index is not None:
            label = chosen.get("part")
            vertices = [row["vertex"] for row in rows if row.get("part") == label]
        elif kind == "partition":
            return (
                graph,
                "Partition overview; select a row to focus its partition.",
                [],
                [],
            )
    elif typ in ("edge_set", "edge_ids", "edge_sample"):
        edges = _edge_witness(graph, [chosen] if index is not None else rows)
        if result.get("operation") in ("spanning-tree-forest", "group-steiner-tree"):
            vertices = ports.get("vertices", {}).get("value", [])
    elif typ == "vertex_set":
        vertices = [chosen] if index is not None else rows
        if kind in ("vertices", "ordered"):
            edges = []
    elif kind == "path_tree":
        by_vertex = {
            (_key(r.get("source")), _key(r["vertex"])): r
            for r in rows
            if isinstance(r, dict) and "vertex" in r
        }
        chain = rows
        if index is not None:
            chain, current, seen = [], chosen, set()
            while current is not None:
                key = (_key(current.get("source")), _key(current["vertex"]))
                if key in seen:
                    raise AnalyticsError(
                        "Recorded predecessor chain contains a cycle",
                        "data_integrity",
                        409,
                    )
                seen.add(key)
                chain.append(current)
                parent = current.get("predecessor")
                current = (
                    by_vertex.get((key[0], _key(parent)))
                    if parent is not None
                    else None
                )
        if not any("predecessor" in r for r in chain):
            return (
                None,
                "Distances are available; this run did not retain predecessor witnesses.",
                [],
                [],
            )
        witnesses = [
            {"source": r["predecessor"], "target": r["vertex"]}
            for r in chain
            if r.get("predecessor") is not None
        ]
        edges = _edge_witness(
            graph, witnesses, maximize=result.get("operation") == "widest-paths"
        )
        vertices = [
            r["vertex"]
            for r in chain
            if r.get("reachable", True) and r.get("distance", 0) is not None
        ]
        note = (
            "No path was recorded to this unreachable destination."
            if index is not None and not vertices
            else (
                "Selected predecessor path."
                if index is not None
                else "Recorded predecessor forest; select a destination for one path."
            )
        )
        if vertices:
            note += (
                " Predecessors identify endpoints; parallel connections use a"
                " maximum-capacity representative."
                if result.get("operation") == "widest-paths"
                else " Predecessors identify endpoints; parallel connections use a"
                " minimum-weight representative."
            )
    elif (
        typ
        in (
            "path_set",
            "temporal_path_table",
            "edge_sequence_collection",
            "walk_sample",
            "temporal_occurrence_collection",
        )
        or kind == "path"
    ):
        if chosen is None:
            vertices, edges = [], []
        elif isinstance(chosen, dict):
            vertices = _members(chosen)
            edges = _edge_witness(
                graph, chosen.get("edges", chosen.get("edge_ids", []))
            )
            if (
                not edges
                and isinstance(chosen.get("vertices"), list)
                and len(chosen["vertices"]) > 1
            ):
                # Walks may omit edge IDs. Mark the endpoint witness explicitly.
                ids = chosen["vertices"]
                edges = _edge_witness(
                    graph,
                    [{"source": a, "target": b} for a, b in itertools.pairwise(ids)],
                )
                note = "Recorded vertex sequence; one input edge per consecutive pair."
        elif isinstance(chosen, list):
            if typ == "walk_sample":
                vertices = chosen
                edges = _edge_witness(
                    graph,
                    [{"source": a, "target": b} for a, b in itertools.pairwise(chosen)],
                )
            else:
                edges = _edge_witness(graph, chosen)
    elif kind == "instances":
        return (
            None,
            "Counts are recorded here. Enable instance listing to inspect individual occurrences.",
            [],
            [],
        )
    elif typ == "entity_ranking":
        if index is None:
            return (
                None,
                "Ranked anomaly scores; select an entity to inspect its source graph witness.",
                [],
                [],
            )
        target = chosen.get("anomaly_target")
        if target == "edge":
            edges = _edge_witness(graph, [chosen["entity"]])
        elif target == "vertex":
            vertices, edges = [chosen["entity"]], []
        else:
            selected = next(
                (
                    r
                    for r in result.get("parameters", {}).get("subgraphs", [])
                    if _key(r["id"]) == _key(chosen["entity"])
                ),
                {},
            )
            vertices = selected.get("vertices", [])
    elif index is not None:
        vertices, edges = _members(chosen), []
    elif kind in (
        "pairs",
        "mapping",
        "embedding",
        "predictions",
        "locations",
        "spectrum",
        "table",
    ):
        return (
            None,
            "Use the result-specific chart and table; select a source-backed row to inspect entities.",
            [],
            [],
        )
    if vertices is None and edges is None:
        return graph, note, [], []
    vertex_keys = {_key(v) for v in (vertices or [])}
    if edges is not None:
        vertex_keys.update(_key(e[k]) for e in edges for k in ("source", "target"))
    else:
        edges = [
            e
            for e in graph["edges"]
            if _key(e["source"]) in vertex_keys and _key(e["target"]) in vertex_keys
        ]
    kept = [v for v in graph["vertices"] if _key(v["id"]) in vertex_keys]
    focused = {"graph": copy.deepcopy(graph["graph"]), "vertices": kept, "edges": edges}
    return focused, note, [v["id"] for v in kept], [e["id"] for e in edges]


def result_view(
    service,
    workflow_id,
    step,
    port,
    *,
    index=None,
    context=False,
    vertex_limit=500,
    edge_limit=2000,
):
    record = service.get(workflow_id)
    saved = service._saved(workflow_id, step=step)["result"]
    if port not in saved.get("ports", {}):
        raise RecordNotFound("No such output port")
    index = default_index(saved["ports"][port], index)
    original = input_graph(service, record, step)
    focused, note, selected, selected_edges = focus_graph(original, saved, port, index)
    graph = original if context else focused
    metadata = {
        "profile": profile(saved.get("operation")),
        "note": note,
        "workflow_id": workflow_id,
        "revision": record["revision"],
        "step": step,
        "port": port,
        "index": index,
        "context": context,
        "item_count": len(view_items(saved["ports"][port])),
        "complete": saved["ports"][port].get("complete", False),
        "selected_vertices": selected[:vertex_limit],
        "selected_edges": selected_edges[:edge_limit],
        "selection_truncated": len(selected) > vertex_limit
        or len(selected_edges) > edge_limit,
        "source_file_ids": []
        if saved["ports"][port].get("type")
        in {"pattern_collection", "cross_graph_mapping"}
        else source_files(record, step),
    }
    metadata["enrichable"] = bool(
        focused and focused["vertices"] and metadata["source_file_ids"]
    )
    if graph is None:
        return {
            **metadata,
            "vertices": [],
            "edges": [],
            "vertex_count": 0,
            "edge_count": 0,
            "graph_available": False,
        }
    vertices = graph["vertices"][:vertex_limit]
    shown = {_key(v["id"]) for v in vertices}
    edges = [
        e
        for e in graph["edges"]
        if _key(e["source"]) in shown and _key(e["target"]) in shown
    ][:edge_limit]
    if metadata["profile"]["kind"] == "flow":
        by_id = {_key(e["id"]): e for e in (original or graph)["edges"]}
        flows = [
            r
            for r in saved.get("result", {}).get("flows", [])
            if r.get("flow", 0) > 0
            and _key(r.get("source")) in shown
            and _key(r.get("target")) in shown
        ]
        metadata["flow_rows"] = [
            {
                **by_id.get(_key(r.get("edge")), {}),
                **r,
                "id": r.get("edge", f"flow-{i}"),
            }
            for i, r in enumerate(flows[:edge_limit])
        ]
        metadata["flow_rows_truncated"] = len(flows) > edge_limit
    return {
        **metadata,
        "graph": graph["graph"],
        "graph_available": True,
        "vertices": vertices,
        "edges": edges,
        "vertex_count": len(graph["vertices"]),
        "edge_count": len(graph["edges"]),
        "vertices_truncated": len(vertices) < len(graph["vertices"]),
        "edges_truncated": len(edges) < len(graph["edges"]),
    }


def register_result_view_routes(router):
    @router.get("/workflows/{workflow_id}/steps/{step}/ports/{port}/view")
    async def view(
        workflow_id: str,
        step: str,
        port: str,
        request: Request,
        index: int | None = Query(None, ge=0),
        context: bool = False,
    ):
        return await run_in_threadpool(
            result_view,
            request.app.state.runtime.analytics,
            workflow_id,
            step,
            port,
            index=index,
            context=context,
        )
