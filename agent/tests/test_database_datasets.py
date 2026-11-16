"""Connection-scoped datasets and the preview/domain/chat boundary."""

from test_database_workspace import source as source, workspace as workspace
from test_benchmark_mappings import registry_setup


def test_dataset_list_requires_a_visible_connection(workspace):
    client = workspace.client
    response = client.get("/api/database-sources/demo/datasets")
    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == "default"
    assert response.json()[0]["tables"][0]["name"] == "accounts"
    assert client.get("/api/database-sources/another-connection/datasets").status_code == 404
    assert client.get("/api/database-sources/demo/datasets", headers={"Authorization": ""}).status_code == 401


def test_foreign_dataset_is_rejected_before_running_query(workspace):
    before = len(workspace.calls)
    response = workspace.client.post("/api/database-sources/demo/queries", json={
        "statement": "MATCH p=()-[]->() RETURN p", "dataset_id": "dataset-from-another-db",
    })
    assert response.status_code == 404
    assert len(workspace.calls) == before


def test_query_cannot_select_another_instances_dataset(workspace, tmp_path):
    workspace.runtime.settings = registry_setup(workspace.runtime.settings, tmp_path / "registry")
    before = len(workspace.calls)
    response = workspace.client.post("/api/database-sources/benchmark-yelp/queries", json={
        "statement": "MATCH p=()-[]->() RETURN p", "dataset_id": "movielens-32m",
    })
    assert response.status_code == 404
    assert len(workspace.calls) == before


def test_importing_dataset_cannot_run_queries(workspace, monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_datasets.datasets", lambda *_: [{
        "id": "yelp", "name": "Yelp", "status": "loading", "graph_label": None,
    }])
    before = len(workspace.calls)
    response = workspace.client.post("/api/database-sources/demo/queries", json={
        "statement": "MATCH (n) RETURN n LIMIT 10", "dataset_id": "yelp",
    })
    assert response.status_code == 409
    assert len(workspace.calls) == before


def test_chat_uses_selected_domain_and_rejects_unknown_domain(workspace):
    domains = workspace.runtime.catalog.domains
    chosen = next(identifier for identifier in domains if identifier != "general")
    path = f"/api/database-query-snapshots/{workspace.snapshot['dataset']['id']}/chat"
    response = workspace.client.post(path, json={"domain_id": chosen})
    assert response.status_code == 201, response.text
    assert response.json()["session"]["domain_id"] == chosen
    assert workspace.client.post(path, json={"domain_id": "missing-domain"}).status_code == 422
