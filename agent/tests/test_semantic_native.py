"""Real pinned Tentō: mapping, collection and explicit mock execution, no HTTP."""

import copy
from importlib import metadata

import pytest

from graphmine_agent.errors import AnalyticsError
from graphmine_agent.semantic_collector import SemanticCollector
from graphmine_agent.semantic_engine import load_engine
from graphmine_agent.semantic_loader import key, load_graph, schema
from graphmine_agent.semantic_worker import run_worker


@pytest.fixture(scope="module")
def native_engine():
    try:
        metadata.version("graphmine-tento")
    except metadata.PackageNotFoundError:
        pytest.skip("Install the source-built semantic extra for native contract tests")
    return load_engine().module


@pytest.fixture
def rich_graph():
    return {
        "graph": {"id": "multi-label", "directed": True, "allows_self_loops": True, "allows_parallel_edges": True},
        "vertices": [
            {"id": 1, "type": "Employee", "label": "One", "attributes": {
                "neo4j_labels": ["Person", "Employee"], "text": 'one\n"quoted" Ω', "mixed": 9007199254740993,
                "all_types": True, "empty": "", "present": None, "nested": {"values": [1, "1", None, {"ok": True}]},
                "big": 2**70, "__gm_key": "original", "Name": "upper", "name": "lower", "": "empty key"}},
            {"id": "1", "type": "Person", "attributes": {
                "neo4j_labels": ["Person"], "text": "two", "mixed": "5", "all_types": 1, "empty": None,
                "nested": [None, False, 2.5], "big": 42}},
            {"id": 2, "attributes": {"text": "three", "mixed": 5, "all_types": 1.5, "empty": "null", "nested": "null"}},
            {"id": 3, "attributes": {"text": "four", "mixed": None, "all_types": "1", "nested": None}},
        ],
        "edges": [
            {"id": 1, "source": 1, "target": "1", "type": "KNOWS", "weight": 2, "attributes": {"score": 2, "mixed": "5", "empty": ""}},
            {"id": "1", "source": 1, "target": "1", "type": "KNOWS", "weight": 4, "attributes": {"score": 4, "mixed": 5, "empty": None}},
            {"id": "loop", "source": 2, "target": 2, "type": "Vertex", "attributes": {"nested": {"x": [1, "2"]}}},
        ],
    }


@pytest.fixture
def loaded(native_engine, rich_graph, tmp_path):
    db = native_engine.Database(buffer_pool_size=128 * 1024 * 1024, max_num_threads=2, backend="pybind")
    connection = native_engine.Connection(db, num_threads=2)
    try:
        graph = load_graph(connection, rich_graph, tmp_path)
        yield connection, graph
    finally:
        connection.close(); db.close()


def collect(loaded, query, **options):
    connection, graph = loaded
    result = connection.execute(query)
    try:
        return SemanticCollector(graph, **options).read(result)
    finally:
        result.close()


def test_schema_exposes_helpers_and_safe_aliases_without_losing_original_names(rich_graph):
    info = schema(rich_graph)
    assert info["mapping"] == "explicit-labels-v1" and info["vertex_table"] == "Vertex"
    assert info["labels"] == ["Employee", "Person"]
    properties = {p["source_property"]: p for p in info["vertex_properties"]}
    assert properties["mixed"]["type"] == "UNION(integer INT64, text STRING)"
    assert properties["nested"]["type"] == properties["big"]["type"] == "JSON"
    assert properties["__gm_key"]["name"] != "__gm_key"
    assert properties["Name"]["name"].casefold() != properties["name"]["name"].casefold()
    assert properties[""]["name"]
    assert next(t for t in info["relationships"] if t["source_type"] == "Vertex")["table"] != "Vertex"


def test_exact_native_values_and_explicit_label_intersection(loaded, rich_graph):
    value = collect(loaded, "MATCH(n:Vertex) RETURN graph_id(n) AS id, labels_of(n) AS labels, n.mixed AS mixed, n.all_types AS all_types, n.empty AS empty, n.nested AS nested, n.big AS big, has_property(n,'present') AS present")
    assert value["kind"] == "table"
    rows = {key(r["id"]): r for r in value["value"]["rows"]}
    for vertex in rich_graph["vertices"]:
        row, attrs = rows[key(vertex["id"])], vertex["attributes"]
        for name in ("mixed", "all_types", "empty", "nested", "big"):
            assert row[name] == attrs.get(name)
            assert type(row[name]) is type(attrs.get(name))
        assert row["present"] is ("present" in attrs)
    assert rows["1"]["labels"] == ["Employee", "Person"]
    intersection = collect(loaded, "MATCH(n:Vertex) WHERE has_label(n,'Employee') AND has_label(n,'Person') RETURN n")
    assert intersection["value"]["vertices"] == [rich_graph["vertices"][0]]
    assert len(collect(loaded, "MATCH(n:Vertex) RETURN n")["value"]["vertices"]) == 4


def test_original_records_and_parallel_edges_survive_collection(loaded, rich_graph):
    original = copy.deepcopy(rich_graph)
    output = collect(loaded, "MATCH()-[r:KNOWS]->() RETURN r")
    assert {key(e["id"]): e for e in output["value"]["edges"]} == {key(e["id"]): e for e in rich_graph["edges"][:2]}
    assert {key(v["id"]): v for v in output["value"]["vertices"]} == {key(v["id"]): v for v in rich_graph["vertices"][:2]}
    assert output["row_count"] == 2
    text = collect(loaded, "MATCH(n:Vertex) WHERE has_label(n,'Employee') RETURN n.text AS text")
    assert text["value"]["rows"][0]["text"] == rich_graph["vertices"][0]["attributes"]["text"]
    assert rich_graph == original


@pytest.mark.parametrize("query", [
    "MATCH p=(a)-[r:KNOWS]->(b) RETURN p",
    "MATCH p=(a)-[r:KNOWS*1..2]->(b) RETURN r",
    "MATCH(a)-[r:KNOWS]->(b) RETURN collect(a) AS nodes, collect(r) AS edges",
    "MATCH(a)-[r:KNOWS]->(b) RETURN {node:a, nested:{edges:[r]}} AS bundle",
    "MATCH(a)-[r:KNOWS]->(b) RETURN subgraph(list_concat(collect(a),collect(b)),collect(r)) AS graph",
])
def test_paths_arrays_and_nested_graph_values_use_native_types(loaded, query):
    output = collect(loaded, query)
    assert output["kind"] == "graph"
    assert {key(v["id"]) for v in output["value"]["vertices"]} == {"1", '"1"'}
    assert {key(e["id"]) for e in output["value"]["edges"]} == {"1", '"1"'}


def test_graph_looking_scalar_objects_remain_tables(loaded):
    value = collect(loaded, "RETURN {_ID:{offset:0,`table`:0}, _LABEL:'Vertex', __gm_key:'1', NODE:'value'} AS fake")
    assert value["kind"] == "table"
    assert value["value"]["rows"][0]["fake"]["NODE"] == "value"


def test_rows_create_distinct_edges_and_validate_weights_and_nodes(loaded, rich_graph):
    value = collect(loaded, "MATCH(a)-[r:KNOWS]->(b) RETURN a AS source,b AS target,r.score AS weight,'SIMILAR' AS type", projection="rows", directed=False)
    assert value["kind"] == "graph" and value["value"]["graph"]["directed"] is False
    assert len({e["id"] for e in value["value"]["edges"]}) == 2
    assert sorted(e["weight"] for e in value["value"]["edges"]) == [2, 4]
    assert all(e["type"] == "SIMILAR" for e in value["value"]["edges"])
    for query in ["RETURN 1 AS source, 2 AS target", "MATCH(n) RETURN n AS source,n AS target,'bad' AS weight", "MATCH(n) RETURN n AS source,n AS target,n AS extra"]:
        with pytest.raises(AnalyticsError, match="nodes|numeric|scalar"):
            collect(loaded, query, projection="rows")


def test_empty_results_preserve_kind_and_full_tables_outlive_samples(loaded):
    graph = collect(loaded, "MATCH(n:Vertex) WHERE false RETURN n")
    assert graph["kind"] == "graph" and graph["value"]["vertices"] == []
    table = collect(loaded, "MATCH(n:Vertex) WHERE false RETURN n.text AS text")
    assert table["kind"] == "table" and table["value"]["columns"] == ["text"]
    table = collect(loaded, "UNWIND range(1,75) AS x RETURN x")
    assert table["row_count"] == len(table["value"]["rows"]) == 75
    assert len(table["rows"]) == 50 and table["rows_truncated"] is True
    with pytest.raises(AnalyticsError, match="budget"):
        collect(loaded, "MATCH(n) RETURN n", max_bytes=20)


@pytest.mark.parametrize("corruption", ["duplicate_vertex", "duplicate_edge", "missing_endpoint", "nonfinite"])
def test_invalid_source_graph_fails_before_native_load(rich_graph, corruption):
    if corruption == "duplicate_vertex":
        rich_graph["vertices"].append(rich_graph["vertices"][0])
    elif corruption == "duplicate_edge":
        rich_graph["edges"].append(rich_graph["edges"][0])
    elif corruption == "missing_endpoint":
        rich_graph["edges"][0]["target"] = "missing"
    else:
        rich_graph["vertices"][0]["attributes"]["bad"] = float("nan")
    with pytest.raises(AnalyticsError) as error:
        schema(rich_graph)
    assert error.value.code == "semantic_mapping"


@pytest.mark.parametrize("query", [
    "MATCH(n) RETURN llm('mock','Echo {{n.text}} {answer STRING}') AS answer",
    "MATCH(n) RETURN llm_score('mock','Score {{n.text}}',0,5) AS score",
    "MATCH(n) RETURN llm_agg(n.text,'mock','Summarize {answer STRING}') AS answer",
    "MATCH p=(a)-[:KNOWS]->(b) RETURN llm_path_agg(p,'mock','Summarize {answer STRING}') AS answer",
    "MATCH(a)-[r:KNOWS]->(b) RETURN llm_sg_agg(a,r,'mock','Summarize {answer STRING}') AS answer",
    "MATCH(n) RETURN llm_sg_agg(n,'mock','Summarize {answer STRING}') AS answer",
])
def test_all_model_operators_run_only_as_explicit_mocks(native_engine, rich_graph, query, tmp_path):
    events = []
    output = run_worker(rich_graph, {"statement": query, "model": "mock", "projection": "elements", "call_limit": 10}, temporary_root=tmp_path, progress=events.append)
    stages = [event["stage"] for event in events]
    assert "matched" not in stages
    assert stages.index("loaded") < stages.index("asking_model") < stages.index("building_graph")
    assert output["kind"] == "table" and output["row_count"] >= 1
    assert output["usage"]["calls"] > 0
    assert output["effective_settings"]["http_requests"] == 0
    assert output["effective_settings"]["query_wide_call_limit_supported"] is False
    assert output["effective_settings"]["answers_retained"] == 0
    assert list(tmp_path.iterdir()) == []


def test_native_syntax_errors_do_not_echo_private_values(native_engine, rich_graph):
    with pytest.raises(AnalyticsError) as error:
        run_worker(rich_graph, {"statement": "RETURN no_such_variable AS private_marker", "model": "mock", "projection": "elements", "call_limit": 10})
    assert error.value.code == "semantic_syntax"
    assert "private_marker" not in str(error.value) and "no_such_variable" not in str(error.value)


def test_call_limit_failure_retains_usage_without_a_partial_result(native_engine, tmp_path):
    graph = {"graph": {"id": "many", "directed": True}, "vertices": [{"id": i, "attributes": {"text": str(i)}} for i in range(40)], "edges": []}
    with pytest.raises(AnalyticsError) as error:
        run_worker(graph, {"statement": "MATCH(n) RETURN n,llm('mock','Echo {{n.text}} {answer STRING}') AS answer", "model": "mock", "projection": "elements", "call_limit": 1}, temporary_root=tmp_path)
    assert error.value.code == "semantic_call_limit"
    # This pin reserves the whole batch set first; no call is dispatched when
    # three batches would exceed a one-call limit. Selected rows are not answers.
    assert error.value.details["usage"]["calls"] == 0
    assert error.value.details["usage"]["llm_rows"] == 40
    assert list(tmp_path.iterdir()) == []


def test_per_expression_mock_limit_is_not_presented_as_a_total_budget(native_engine, rich_graph):
    query = "MATCH(n) RETURN llm('mock','One {{n.text}} {answer STRING}') AS first, llm('mock','Two {{n.text}} {answer STRING}') AS second"
    output = run_worker(rich_graph, {"statement": query, "model": "mock", "projection": "elements", "call_limit": 1})
    assert output["usage"]["calls"] == 2
    assert output["effective_settings"]["call_limit_scope"] == "per_expression"
    assert output["effective_settings"]["query_wide_call_limit_supported"] is False
