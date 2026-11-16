"""Read-only dataset schema respects properties and authorization."""

from test_database_workspace import source, workspace  # noqa: F401


def test_schema_exposes_graph_properties_and_requires_access(workspace):
    client = workspace.client
    path = "/api/database-sources/demo/schema"
    response = client.get(path)
    assert response.status_code == 200, response.text
    schema = response.json()
    assert [p["name"] for p in schema["entities"][0]["properties"]] == ["name"]
    assert [p["name"] for p in schema["relationships"][0]["properties"]] == ["amount"]
    assert schema["relationships"][0]["source_entity"] == "accounts"
    assert client.get(path, params={"dataset_id": "unrelated-dataset"}).status_code == 404
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/database-sources/private/schema").status_code == 404

