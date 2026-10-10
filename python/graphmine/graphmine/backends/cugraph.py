from __future__ import annotations

import importlib.util
import os

from ..exceptions import BackendUnavailable, GraphMineError, UnsupportedOperation

OPERATIONS = frozenset(
    {
        "breadth-first-search",
        "single-source-shortest-paths",
        "many-source-shortest-paths",
        "connected-components",
        "k-core",
        "k-truss",
        "triangle-counting",
        "pagerank",
        "personalized-pagerank",
        "betweenness-centrality",
        "link-prediction",
        "induced-subgraph",
        "spanning-tree-forest",
    }
)


def installed() -> bool:
    return importlib.util.find_spec("nx_cugraph") is not None


def supports(operation: str, args: dict) -> tuple[bool, str]:
    if operation not in OPERATIONS:
        return False, "This operation has no cuGraph integration"
    if (
        operation == "connected-components"
        and args["connectivity_mode"] != "weakly_connected"
    ):
        return False, "The nx-cugraph profile supports weak connectivity only"
    if operation == "betweenness-centrality" and args["weight_mode"] != "unweighted":
        return False, "The cuGraph betweenness profile supports unweighted paths only"
    if operation == "link-prediction" and args["scoring_measure"] != "jaccard":
        return False, "The nx-cugraph similarity profile currently supports Jaccard"
    if (
        operation == "personalized-pagerank"
        and args["dangling_policy"] == "redistribute_uniformly"
    ):
        return (
            False,
            "The nx-cugraph personalized PageRank profile does not support custom dangling weights",
        )
    if operation == "triangle-counting" and (
        args["list_instances"] or args["include_per_edge_counts"]
    ):
        return (
            False,
            "The cuGraph triangle profile provides counts and per-vertex counts",
        )
    if operation == "induced-subgraph" and args["mode"] != "ego":
        return (
            False,
            "Explicit vertex-induced extraction currently uses the CPU adapter",
        )
    return True, ""


def prepare(operation: str, args: dict, graph=None) -> dict:
    supported, reason = supports(operation, args)
    if not supported:
        raise UnsupportedOperation(reason)
    if not installed():
        raise BackendUnavailable("Install graphmine[gpu] to use the cuGraph backend")
    if graph is not None and operation in {
        "single-source-shortest-paths",
        "many-source-shortest-paths",
        "spanning-tree-forest",
    }:
        weights = [edge.get("weight", 1) for edge in graph.to_canonical()["edges"]]
        if any(type(value) is int and float(value) != value for value in weights):
            raise UnsupportedOperation(
                "cuGraph float64 cannot exactly represent these integer weights; use CPU"
            )
        if (
            operation != "spanning-tree-forest"
            and weights
            and all(type(value) is int for value in weights)
            and max(abs(value) for value in weights) * max(1, graph.vertex_count - 1)
            > 2**53
        ):
            raise UnsupportedOperation(
                "Integer path costs may exceed exact float64 range; use CPU"
            )
    try:
        import cupy
        import nx_cugraph

        if cupy.cuda.runtime.getDeviceCount() < 1:
            raise BackendUnavailable("No CUDA device is visible")
        index = cupy.cuda.runtime.getDevice()
        properties = cupy.cuda.runtime.getDeviceProperties(index)
        return {
            "id": "cugraph",
            "device": "gpu",
            "library": "cuGraph"
            if operation == "spanning-tree-forest"
            else "nx-cugraph",
            "version": nx_cugraph.__version__,
            "device_index": index,
            "device_name": properties["name"].decode(),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "pci_bus_id": f"{properties['pciDomainID']:04x}:{properties['pciBusID']:02x}:{properties['pciDeviceID']:02x}",
        }
    except (ImportError, RuntimeError) as exc:
        if isinstance(exc, BackendUnavailable):
            raise
        raise BackendUnavailable(f"cuGraph could not initialize: {exc}") from exc


def spanning_forest(graph, *, maximum=False):
    """Use direct cuGraph: nx-cugraph does not currently expose MST."""
    import cudf
    import cugraph
    import networkx as nx

    result = nx.Graph(backend="networkx")
    result.add_nodes_from(graph.nodes(data=True))
    if not graph.number_of_edges():
        return result
    edges = list(graph.edges(data=True))
    frame = cudf.DataFrame(
        {
            "source": cudf.Series([u for u, _, _ in edges], dtype="int32"),
            "target": cudf.Series([v for _, v, _ in edges], dtype="int32"),
            "weight": cudf.Series(
                [(-1 if maximum else 1) * d["weight"] for _, _, d in edges],
                dtype="float64",
            ),
        }
    )
    gpu_graph = cugraph.Graph()
    gpu_graph.from_cudf_edgelist(
        frame,
        source="source",
        destination="target",
        edge_attr="weight",
        vertices=cudf.Series(list(graph), dtype="int32"),
    )
    tree = cugraph.minimum_spanning_tree(gpu_graph)
    for edge in tree.view_edge_list().to_pandas().itertuples(index=False):
        u, v = int(edge.src), int(edge.dst)
        if not graph.has_edge(u, v):
            raise GraphMineError("cuGraph spanning forest returned an unknown edge")
        result.add_edge(u, v, weight=graph[u][v]["weight"])
    return result
