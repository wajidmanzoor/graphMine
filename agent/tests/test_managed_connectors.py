import base64
import json
import socket
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from graphmine_agent import managed_connectors as managed
from graphmine_agent.analytics import AnalyticsError
from test_connectors import sources as sources  # noqa: PLC0414


def test_uploaded_sqlite_ownership_mapping_quota_and_removal(sources):
    client, _runtime, alice, bob, _, _, database = sources
    before = client.get("/api/auth/me", headers=alice).json()["quota"]
    response = client.post(
        "/api/connectors/sqlite",
        headers=alice,
        files={"file": ("ledger.sqlite3", database.read_bytes())},
    )
    assert response.status_code == 201, response.text
    connection = response.json()
    identifier = connection["id"]
    assert connection["tables"] == [
        {"name": "transfers", "columns": ["source", "target", "weight"]}
    ]
    assert (
        connection["managed"]
        and "path" not in connection
        and "headers" not in connection
    )
    after = client.get("/api/auth/me", headers=alice).json()["quota"]
    assert after["storage"]["connections"] >= database.stat().st_size
    assert after["jobs_used"] == before["jobs_used"]
    assert client.get(f"/api/connectors/{identifier}", headers=bob).status_code == 404
    assert (
        client.delete(f"/api/connectors/{identifier}", headers=bob).status_code == 404
    )
    body = {
        "type": "sqlite",
        "name": "Saved ledger",
        "table": "transfers",
        "source_column": "target",
        "target_column": "source",
        "directed": True,
    }
    assert (
        client.put(f"/api/connectors/{identifier}", headers=bob, json=body).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/connectors/{identifier}", headers=alice, json=body
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/connectors/{identifier}",
            headers=alice,
            json={**body, "source_column": "missing"},
        ).status_code
        == 422
    )
    preview = client.post(f"/api/connectors/{identifier}/preview", headers=alice).json()
    assert (
        preview["edges"][0]["source"] == "1" and preview["edges"][0]["target"] == "001"
    )
    assert preview["source_scope"] == "uploaded SQLite snapshot"
    imported = client.post(
        f"/api/connectors/{identifier}/import",
        headers=alice,
        json={"name": "Snapshot", "expected_sha256": preview["sha256"]},
    )
    assert imported.status_code == 201, imported.text
    assert (
        client.delete(f"/api/connectors/{identifier}", headers=alice).status_code == 204
    )
    assert (
        client.post(f"/api/connectors/{identifier}/preview", headers=alice).status_code
        == 404
    )
    assert len(client.get("/api/datasets", headers=alice).json()) == 1
    assert (
        client.get("/api/auth/me", headers=alice).json()["quota"]["storage"][
            "connections"
        ]
        == 0
    )


def test_invalid_or_over_quota_sqlite_upload_leaves_no_connection(sources):
    client, runtime, alice, _, _, _, database = sources
    response = client.post(
        "/api/connectors/sqlite",
        headers=alice,
        files={"file": ("bad.db", b"not sqlite")},
    )
    assert response.status_code == 422
    runtime.accounts.settings = replace(
        runtime.accounts.settings, account_storage_bytes=100
    )
    response = client.post(
        "/api/connectors/sqlite",
        headers=alice,
        files={"file": ("big.db", database.read_bytes())},
    )
    assert response.status_code == 413
    assert len(client.get("/api/connectors", headers=alice).json()) == 1


@pytest.mark.parametrize("kind", ["rest", "neo4j"])
def test_user_http_connection_roundtrip_and_credentials(sources, kind):
    client, runtime, alice, bob, _, _, _ = sources
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization"), None))
            body = {"rows": [{"source": "001", "target": 9007199254740993}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("Authorization"), body))
            self.send_response(202)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "data": {
                            "fields": [
                                "source",
                                "target",
                                "relationship",
                                "relationship_id",
                            ],
                            "values": [["node-a", "node-b", "KNOWS", "edge-1"]],
                        },
                        "queryType": "r",
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        body = {"type": kind, "name": "Private source", "url": origin}
        if kind == "rest":
            body.update(bearer_token="private-api-token", rows_field="rows")
        else:
            body.update(
                username="reader",
                password="private-database-password",
                node_label="Person') DELETE n //",
            )
        # Network access requires an explicit server origin for local services.
        assert (
            client.post("/api/connectors", headers=alice, json=body).status_code == 422
        )
        assert seen == []
        runtime.settings = replace(
            runtime.settings, connector_allowed_origins=(origin,)
        )
        response = client.post("/api/connectors", headers=alice, json=body)
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        assert response.json()["has_credentials"]
        assert (
            "private-api-token" not in response.text
            and "private-database-password" not in response.text
        )
        assert (
            client.get(f"/api/connectors/{identifier}", headers=bob).status_code == 404
        )
        for verb in ("get",):
            detail = getattr(client, verb)(
                f"/api/connectors/{identifier}", headers=alice
            )
            assert (
                "Authorization" not in detail.text
                and "private-api-token" not in detail.text
            )
        preview = client.post(f"/api/connectors/{identifier}/preview", headers=alice)
        assert preview.status_code == 200, preview.text
        imported = client.post(
            f"/api/connectors/{identifier}/import",
            headers=alice,
            json={"name": "Imported", "expected_sha256": preview.json()["sha256"]},
        )
        assert imported.status_code == 201, imported.text
        assert (
            "private-api-token" not in imported.text
            and "private-database-password" not in imported.text
        )
        if kind == "rest":
            assert all(row[1] == "Bearer private-api-token" for row in seen)
            assert preview.json()["vertices"][1]["id"] == 9007199254740993
        else:
            expected = (
                "Basic "
                + base64.b64encode(b"reader:private-database-password").decode()
            )
            assert all(
                row[1] == expected and row[0] == "/db/neo4j/query/v2" for row in seen
            )
            assert seen[0][2]["accessMode"] == "Read"
            assert "DELETE" not in seen[0][2]["statement"]
            assert seen[0][2]["parameters"]["label"] == body["node_label"]
            assert "isolated nodes" in preview.json()["source_scope"]
        # Blank credentials retain the existing secret for the same server.
        body.pop("bearer_token", None)
        body.pop("password", None)
        body["name"] = "Renamed"
        assert client.put(
            f"/api/connectors/{identifier}", headers=alice, json=body
        ).json()["has_credentials"]
        # Disabling the origin after creation also blocks future network reads.
        runtime.settings = replace(runtime.settings, connector_allowed_origins=())
        count = len(seen)
        assert (
            client.post(
                f"/api/connectors/{identifier}/preview", headers=alice
            ).status_code
            == 422
        )
        assert len(seen) == count
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_dns_address_pinning_and_private_address_rejection(settings, monkeypatch):
    def resolve(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(managed.socket, "getaddrinfo", resolve)
    url, host, server_name = managed.network_target(
        settings, "https://api.example.com:8443/graph?version=2"
    )
    assert str(url) == "https://93.184.216.34:8443/graph?version=2"
    assert host == "api.example.com:8443" and server_name == "api.example.com"
    for address in (
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
    ):
        monkeypatch.setattr(
            managed.socket,
            "getaddrinfo",
            lambda *_a, current=address, **_k: (
                resolve()
                + [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (current, 443))]
            ),
        )
        with pytest.raises(AnalyticsError, match="private or reserved"):
            managed.network_target(settings, "https://api.example.com/graph")


def test_connection_api_rejects_paths_queries_and_credential_urls(sources):
    client, _, alice, _, _, _, _ = sources
    for body in (
        {"name": "Host files", "type": "sqlite", "path": "/etc/passwd"},
        {
            "name": "Write",
            "type": "neo4j",
            "url": "https://db.example.com",
            "query": "MATCH (n) DELETE n",
        },
        {
            "name": "Embedded credentials",
            "type": "rest",
            "url": "https://user:secret@example.com",
        },
    ):
        assert (
            client.post("/api/connectors", headers=alice, json=body).status_code == 422
        )
