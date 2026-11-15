import json
from dataclasses import replace

from fastapi.testclient import TestClient
from graphmine_agent.api import create_app


def test_local_catalog_schema_auth_and_file_scope(settings, tmp_path):
    root = tmp_path / "benchmarks"
    schema = root / "yelp" / "schemas"
    schema.mkdir(parents=True)
    (schema / "neo4j-0.png").write_bytes(b"\x89PNG\r\n\x1a\nschema")
    (schema / "neo4j-loading-and-queries.txt").write_text("MATCH (n) RETURN n LIMIT 10")
    (schema / "manifest.json").write_text(json.dumps({
        "schemas": [{"platform": "neo4j", "file": "neo4j-0.png", "page": "https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html"}]
    }))
    (root / "yelp" / "dataverse-metadata.json").write_text(json.dumps({"data": {"latestVersion": {"files": [{}]}}}))
    raw = root / "yelp" / "raw"
    raw.mkdir()
    (raw / "edges.csv").write_bytes(b"a,b\n1,2\n")
    (raw / "edges.csv.verified.json").write_text(json.dumps({"size_bytes": 8, "sha256": "checked"}))
    configured = replace(settings, benchmark_datasets_root=root)
    with TestClient(create_app(configured)) as client:
        assert client.get("/api/benchmark-datasets").status_code == 401
        client.headers["Authorization"] = "Bearer test-secret"
        entries = client.get("/api/benchmark-datasets").json()
        assert len(entries) == 1
        assert entries[0]["status"] == "downloaded"
        assert entries[0]["downloaded_files"] == 1
        image = client.get(entries[0]["schemas"][0]["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        commands = client.get(entries[0]["schemas"][0]["definition_url"])
        assert commands.status_code == 200 and "attachment" in commands.headers["content-disposition"]
        assert client.get("/api/benchmark-datasets/yelp/schemas/manifest.json").status_code == 404
        assert client.get("/api/benchmark-datasets/unknown/schemas/neo4j-0.png").status_code == 404
        (raw / "edges.csv").write_bytes(b"truncated")
        assert client.get("/api/benchmark-datasets").json()[0]["status"] == "downloading"


def test_catalog_without_config_is_empty(settings):
    with TestClient(create_app(replace(settings, benchmark_datasets_root=None))) as client:
        client.headers["Authorization"] = "Bearer test-secret"
        assert client.get("/api/benchmark-datasets").json() == []
