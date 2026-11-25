"""Semantic, ownership, boundedness and reproducibility contracts for views."""
import ast
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.models import ChartTemplateRequest, TemplateNarrative, ViewSpec
from graphmine_agent.result_views import PROFILES, result_view
from graphmine_agent.view_actions import CompareRequest, ExpandRequest, LabelRequest, PathRequest, ProjectionRequest, ViewRequest, compare, expand, labels, meta_graph, project_embedding, shortest_connection
from graphmine_agent.view_contracts import TYPE_ROLES, catalog_roles
from graphmine_agent.view_data import group_memberships, saved_view_manifest
from graphmine_agent.view_profile import MEMBERSHIP_BUDGET, fingerprint, graph_facts, profile_result, rows_for
from graphmine_agent.view_rules import DEFAULTS, choose_view
from graphmine_agent.view_semantics import semantic_data


def graph():
    return {"graph": {"id": "input", "directed": True}, "vertices": [{"id": v, "label": name} for v, name in [(0, "Number zero"), ("0", "Text zero"), (9007199254740993, "Large ID"), (2, "Destination")]], "edges": [{"id": "a", "source": 0, "target": "0", "weight": 10}, {"id": "parallel", "source": 0, "target": "0", "weight": 1}, {"id": "b", "source": "0", "target": 2, "weight": 3}]}


class Service:
    def __init__(self, root, output=None):
        self.root = root
        self.g = graph()
        self.output = output or {"problem": "densest-subgraph", "ports": {"out": {"type": "vertex_set", "value": [0, "0"], "complete": True}}}
        self.records = {"w": {"id": "w", "session_id": "s", "revision": 1, "validation": {"plan": {"steps": [{"id": "analysis", "problem": self.output["problem"], "input": {"input": "main"}, "parameters": {}}]}, "order": ["analysis"]}}}

    def get(self, key):
        if key not in self.records:
            from graphmine_agent.database import RecordNotFound
            raise RecordNotFound("Private result not available")
        return self.records[key]

    def _saved(self, key, **_):
        self.get(key)
        return {"result": self.output}

    def _directory(self, record):
        self.root.mkdir(exist_ok=True)
        return self.root

    def _read_result(self, path):
        return {"main": {"kind": "graph", "data": self.g}} if path.name == "inputs.json" else json.loads(path.read_text())

    def _write(self, path, value):
        path.write_text(json.dumps(value, allow_nan=False))


def request(cls=ViewRequest, **kwargs):
    return cls(expected_revision=1, **kwargs)


def test_all_native_types_and_82_problems_have_roles_and_25_profile_defaults():
    root = Path(__file__).resolve().parents[2]
    types = set(re.findall(r'port\("([a-z_]+)"\)', (root / "library/runtime/registry.cpp").read_text()))
    assert types <= TYPE_ROLES.keys()
    source = ast.parse((root / "python/graphmine/graphmine/ports.py").read_text())
    ports = ast.literal_eval(next(n.value for n in source.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OUTPUT_PORTS" for t in n.targets)))
    assert len(PROFILES) == 82 and len({p["kind"] for p in PROFILES.values()}) == 25
    for problem, declared in ports.items():
        assert catalog_roles(problem, declared).keys() == declared.keys()
        assert all(catalog_roles(problem, declared).values())


@pytest.mark.parametrize("kind", sorted({p["kind"] for p in PROFILES.values()}))
def test_every_profile_emits_valid_explicit_defaults(kind):
    p = {"kind": kind, "title": kind}
    facts = profile_result("example", {"type": "vertex_set", "value": [0, "0"]}, graph(), graph())
    value = {"vertices": graph()["vertices"], "edges": graph()["edges"], "vertex_count": 4, "edge_count": 3, "graph_available": True, "complete": True}
    spec = ViewSpec.model_validate(choose_view(p, facts, value))
    assert spec.view == DEFAULTS[kind][0]
    assert spec.layout.name == DEFAULTS[kind][1]
    assert spec.rules_applied[0] == "profile_" + kind
    assert spec.nodes["label"].field == "display_name"
    assert spec.edges["arrows"].value is True


def test_typed_names_and_revisions_and_access(tmp_path):
    service = Service(tmp_path)
    result = labels(service, "w", "analysis", "out", request(LabelRequest, vertices=[0, "0", 9007199254740993]))
    assert [r["label"] for r in result["labels"]] == ["Number zero", "Text zero", "Large ID"]
    with pytest.raises(AnalyticsError, match="revision"):
        labels(service, "w", "analysis", "out", LabelRequest(expected_revision=2, vertices=[0]))
    from graphmine_agent.database import RecordNotFound
    with pytest.raises(RecordNotFound):
        labels(service, "other-owner", "analysis", "out", request(LabelRequest, vertices=[0]))


def test_neighbor_cap_and_direction(tmp_path):
    service = Service(tmp_path)
    service.g = {"graph": {"directed": True}, "vertices": [{"id": i} for i in range(100)], "edges": [{"id": i, "source": 0, "target": i} for i in range(1, 100)]}
    value = expand(service, "w", "analysis", "out", request(ExpandRequest, vertices=[0], visible=[0]))
    assert len(value["vertices"]) == 50 and value["remaining"] == 49
    assert not expand(service, "w", "analysis", "out", request(ExpandRequest, vertices=[0], direction="in"))["vertices"]


def test_connection_is_explicit_shortest_hops_preserves_direction_and_one_parallel_record(tmp_path):
    service = Service(tmp_path)
    before = deepcopy(service.g)
    result = shortest_connection(service, "w", "analysis", "out", request(PathRequest, source=0, target=2))
    assert [v["id"] for v in result["vertices"]] == [0, "0", 2]
    assert [e["id"] for e in result["edges"]] == ["a", "b"]
    assert result["provenance"]["weights_used"] is False
    assert not shortest_connection(service, "w", "analysis", "out", request(PathRequest, source=2, target=0))["found"]
    assert service.g == before


def test_overlapping_groups_do_not_become_meta_edges(tmp_path):
    service = Service(tmp_path, {"problem": "overlapping-communities", "ports": {"out": {"type": "vertex_groups", "value": [{"group": 0, "vertices": [0, "0"]}, {"group": 1, "vertices": ["0", 2]}], "complete": True}}})
    with pytest.raises(AnalyticsError, match="overlap"):
        meta_graph(service, "w", "analysis", "out", request())
    service.output["ports"]["out"]["value"][1]["vertices"] = [2]
    value = meta_graph(service, "w", "analysis", "out", request())
    assert sum(e["weight"] for e in value["edges"]) == 3


def test_global_membership_budget_and_partial_statistics():
    port = {"type": "vertex_groups", "value": [{"group": i, "vertices": list(range(20000))} for i in range(8)]}
    facts = profile_result("overlapping-communities", port)
    assert not facts["statistics_complete"] and not facts["groups"]["statistics_complete"]
    assert facts["budget"]["scanned_memberships"] == MEMBERSHIP_BUDGET
    with pytest.raises(ValueError, match="budget"):
        group_memberships(port, port["value"])


def test_density_ignores_loops_and_parallel_counts_and_omits_partial_density():
    g = graph()
    assert graph_facts(g)["density"] == pytest.approx(2 / 12)
    g["edges"] *= 7000
    assert graph_facts(g)["density"] is None


def test_eigenvector_orientation_is_vertex_by_eigenpair():
    rows, total = rows_for({"type": "eigenpairs", "value": {"eigenvalues": [1, 2], "eigenvectors": [[.1, .2], [.3, .4], [.5, .6]]}})
    assert total == 2 and rows[1]["eigenvector"] == [.2, .4, .6]


def test_current_rules_repair_historical_views_without_changing_recorded_provenance(tmp_path):
    service = Service(tmp_path)
    record = service.get("w")
    manifest = saved_view_manifest(service, record, "analysis", {"result": service.output})
    manifest["ports"]["out"]["spec"]["rules_version"] = "historical-v1"
    service._write(tmp_path / "step-analysis.views.json", manifest)
    value = result_view(service, "w", "analysis", "out", expected_revision=1)
    assert value["view_spec"]["rules_version"] != "historical-v1"
    assert value["view_spec"]["provenance"]["recorded_rules_version"] == "historical-v1"
    assert json.loads((tmp_path / "step-analysis.views.json").read_text()) == manifest
    assert value["view_spec"]["provenance"]["input_fingerprint"] == fingerprint(service.g)


def test_projection_is_explicit_cached_finite_and_separate(tmp_path, monkeypatch):
    output = {"problem": "node-embedding", "ports": {"out": {"type": "vertex_embeddings", "value": [{"vertex": v, "values": x} for v, x in [(0, [1, 2, 3]), ("0", [2, 1, 0]), (2, [0, 0, 1])]], "complete": True}}}
    service = Service(tmp_path, output)
    before = deepcopy(output)
    value = project_embedding(service, "w", "analysis", "out", request(ProjectionRequest))
    assert value["points"][1]["entity"] == "0" and value["provenance"]["changes_result"] is False
    import sklearn.decomposition
    monkeypatch.setattr(sklearn.decomposition, "PCA", lambda **kwargs: pytest.fail("cached projection reran"))
    assert project_embedding(service, "w", "analysis", "out", request(ProjectionRequest)) == value
    assert service.output == before


def test_confusion_uses_only_declared_truth_and_actual_predictions():
    port = {"type": "vertex_predictions", "value": [{"vertex": 0, "prediction": "a"}, {"vertex": "0", "prediction": "b"}, {"vertex": 2, "prediction": "a"}]}
    saved = {"problem": "node-learning", "parameters": {"task": "classification", "training_labels": {"rows": [{"vertex": 0, "value": "a"}]}, "split": {"test_labels": [{"vertex": "0", "value": "a"}]}}, "ports": {"out": port}}
    result = semantic_data(saved, port, graph(), graph()["vertices"], {})
    assert sum(r["count"] for r in result["confusion"]) == 2
    assert result["prediction_errors"] == ["0"]


def test_diagnostic_only_output_never_becomes_a_count():
    facts = profile_result("unknown", {"type": "model_state", "value": {"iterations": 20}})
    spec = choose_view({"kind": "table", "title": "Diagnostics"}, facts, {"graph_available": False})
    assert spec["view"] == "table" and "count_only" not in spec["rules_applied"]


GOLDENS = sorted((Path(__file__).parent / "fixtures/view-goldens").glob("*.json"))


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_sanitized_saved_analysis_golden(path, tmp_path):
    fixture = json.loads(path.read_text())
    service = Service(tmp_path, fixture["result"])
    service.g = fixture["input"]
    service.records["fixture"] = {**service.records["w"], "id": "fixture"}
    for port, expected in fixture["expected"].items():
        view = result_view(service, "fixture", "analysis", port, expected_revision=1)
        assert view["view_spec"] == expected["spec"]
        assert view["profile_facts"] == expected["facts"]


def test_seventeen_saved_analysis_fixtures_have_no_source_identifiers():
    assert len(GOLDENS) == 17
    for path in GOLDENS:
        text = path.read_text()
        assert "neo4j:" not in text and "postgresql://" not in text


def test_route_uses_predecessors_not_input_row_order():
    rows = [{"vertex": 2, "predecessor": "0", "distance": 4}, {"vertex": 0, "predecessor": None, "distance": 0}, {"vertex": "0", "predecessor": 0, "distance": 1}]
    port = {"type": "vertex_scores", "value": rows}
    value = semantic_data({"problem": "single-source-shortest-paths"}, port, graph(), [], {}, index=0)
    assert [r["vertex"] for r in value["route"]] == [0, "0", 2]


def test_flow_scalar_keeps_its_recorded_flow_witness(tmp_path):
    service = Service(tmp_path, {"problem": "max-flow-min-cut", "ports": {"out": {"type": "scalar", "value": 3, "complete": True}}, "result": {"flows": [{"edge": "a", "source": 0, "target": "0", "flow": 3}]}})
    view = result_view(service, "w", "analysis", "out", expected_revision=1)
    assert view["view_spec"]["view"] == "graph"
    assert view["edges"][0]["view"]["flow"] == 3


CASES = json.loads((Path(__file__).parent / "fixtures/native-profile-cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["kind"])
def test_native_shaped_profiles_preserve_evidence_and_offer_the_intended_view(case, tmp_path):
    service = Service(tmp_path, deepcopy(case["result"]))
    service.g = deepcopy(case["input"])
    before = deepcopy((service.g, service.output))
    view = result_view(service, "w", "analysis", "out", expected_revision=1)
    assert view["profile"]["kind"] == case["kind"]
    assert view["view_spec"]["view"] == case["primary"]
    assert view["view_spec"]["provenance"]["input_fingerprint"] == fingerprint(service.g)
    assert view["view_spec"]["provenance"]["result_fingerprint"] == fingerprint(service.output)
    assert (service.g, service.output) == before
    if case["kind"] == "pairs":
        assert not view["edges"] and "predicted_edges" not in view["view_spec"]["alternates"]
    if case["kind"] == "mapping":
        assert not view["graph_available"] and len(view["chart_data"]["mapping_graphs"]) == 2
    if case["kind"] == "intervals":
        assert view["chart_data"]["rows"][1]["death"] is None


def test_saved_context_rechecks_ids_revision_and_namespace(tmp_path):
    from graphmine_agent.view_actions import ContextRequest, restore_context, merge_context
    service = Service(tmp_path)
    base = result_view(service, "w", "analysis", "out")
    context = restore_context(service, "w", "analysis", "out", request(ContextRequest, vertices=[2], edges=["b"]))
    restored = merge_context(base, context)
    assert next(v for v in restored["vertices"] if v["id"] == 2)["view"]["result"] is False
    assert next(e for e in restored["edges"] if e["id"] == "b")["view"]["edge_role"] == "context"
    with pytest.raises(AnalyticsError, match="outside"):
        restore_context(service, "w", "analysis", "out", request(ContextRequest, vertices=["foreign"]))
    with pytest.raises(AnalyticsError, match="revision"):
        restore_context(service, "w", "analysis", "out", ContextRequest(expected_revision=2))


def test_nested_chart_payload_and_vector_signals_are_bounded():
    from graphmine_agent.view_data import chart_rows
    rows, truncated = chart_rows([{"vertices": list(range(50000))} for _ in range(2000)])
    assert truncated and len(json.dumps(rows)) < 1000000
    facts = profile_result("graph-signal-denoising", {"type": "vertex_signal", "value": [{"vertex": 0, "value": [-1, 999]}, {"vertex": "0", "value": [2, -999]}]})
    assert facts["scores"]["field"] == "value[0]" and facts["scores"]["minimum"] == -1


def test_edge_anomaly_ids_never_color_same_named_vertices(tmp_path):
    service = Service(tmp_path, {"problem": "graph-anomalies", "ports": {"out": {"type": "entity_ranking", "value": [{"entity": "0", "anomaly_target": "edge", "score": 4}], "complete": True}}})
    service.g["edges"][0]["id"] = "0"
    view = result_view(service, "w", "analysis", "out", context=True)
    assert view["profile_facts"]["field_roles"]["entity"]["namespace"] == "input_edge"
    assert all(v["view"]["score"] is None for v in view["vertices"])
    assert view["edges"][0]["view"]["score"] == 4
    assert view["view_spec"]["edges"]["width"]["field"] == "score"
    assert view["view_spec"]["nodes"]["size"]["field"] == "degree"


def test_compare_excludes_generated_namespaces_and_counts_real_membership_transitions(tmp_path):
    output = {"problem": "community-detection", "ports": {"out": {"type": "vertex_partition", "value": [{"vertex": 0, "part": 1}, {"vertex": "0", "part": 2}], "complete": True}}}
    service = Service(tmp_path, output)
    service.records["right"] = {**deepcopy(service.records["w"]), "id": "right"}
    right = deepcopy(output)
    right["ports"]["out"]["value"][1]["part"] = 1
    service._saved = lambda key, **kwargs: {"result": right if key == "right" else output}
    value = compare(service, "w", "analysis", "out", request(CompareRequest, workflow_id="right", revision=1, step="analysis", port="out"))
    assert value["same_input"] and value["comparable_entities"]
    assert {tuple(r.values()) for r in value["membership_transitions"]} == {(1, 1, 1), (2, 1, 1)}
    right["problem"] = "graph-coarsening"
    with pytest.raises(AnalyticsError):
        compare(service, "w", "analysis", "out", request(CompareRequest, workflow_id="right", revision=1, step="analysis", port="out"))
    value = compare(service, "w", "analysis", "out", request(CompareRequest, workflow_id="right", revision=1, step="analysis", port="out", allow_different_inputs=True))
    assert value["diff"] is None and not value["comparable_entities"]
