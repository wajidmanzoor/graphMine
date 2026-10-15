import json
import sqlite3
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from graphmine_agent import connectors
from graphmine_agent.api import create_app
from test_accounts import PASSWORD, login


@pytest.fixture
def sources(settings, tmp_path):
    database = tmp_path / "private-source.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE transfers(source,target,weight)")
        db.executemany(
            "INSERT INTO transfers VALUES (?,?,?)",
            [("001", "1", 2), ("1", 1, 3), (1, 9007199254740993, 4)],
        )
    config = tmp_path / "private-connectors.json"
    entries = [
        {
            "id": "ledger",
            "name": "Transfers",
            "type": "sqlite",
            "path": str(database),
            "table": "transfers",
            "users": ["alice"],
        }
    ]
    config.write_text(json.dumps(entries))
    config.chmod(0o600)
    with TestClient(
        create_app(replace(settings, accounts_enabled=True, connectors_file=config))
    ) as client:
        runtime = client.app.state.runtime
        for user in ("alice", "bob"):
            runtime.accounts.create_user(user, PASSWORD)
        yield (
            client,
            runtime,
            login(client),
            login(client, "bob"),
            config,
            entries,
            database,
        )


def test_database_import_is_readonly_lossless_private_and_versioned(sources):
    client, _, alice, bob, _, _, database = sources
    before = database.read_bytes()
    assert client.get("/api/connectors", headers=bob).json() == []
    inventory = client.get("/api/connectors", headers=alice).json()
    assert inventory == [{"id": "ledger", "name": "Transfers", "type": "sqlite"}]
    assert client.post("/api/connectors/ledger/preview", headers=bob).status_code == 404
    preview = client.post("/api/connectors/ledger/preview", headers=alice).json()
    assert [v["id"] for v in preview["vertices"]] == ["001", "1", 1, 9007199254740993]
    assert preview["source_complete"] and database.read_bytes() == before
    body = {"name": "Imported ledger", "expected_sha256": preview["sha256"]}
    response = client.post("/api/connectors/ledger/import", headers=alice, json=body)
    assert response.status_code == 201, response.text
    first = response.json()
    assert (
        "private-source" not in json.dumps(first)
        and first["source"]["connector_type"] == "sqlite"
    )
    second = client.post(
        "/api/connectors/ledger/import",
        headers=alice,
        json={**body, "dataset_id": first["dataset_id"]},
    ).json()
    assert second["version"] == 2 and first["sha256"] == second["sha256"]
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO transfers VALUES (5,6,7)")
    assert (
        client.post(
            "/api/connectors/ledger/import", headers=alice, json=body
        ).status_code
        == 409
    )
    assert len(client.get("/api/datasets", headers=alice).json()) == 2


def test_connector_limits_and_private_configuration_fail_closed(sources, monkeypatch):
    client, _, alice, _, config, _, _ = sources
    monkeypatch.setattr(connectors, "MAX_ROWS", 1)
    response = client.post("/api/connectors/ledger/preview", headers=alice)
    assert response.status_code == 422 and "partial" in response.text
    assert client.get("/api/datasets", headers=alice).json() == []
    config.chmod(0o644)
    response = client.get("/api/connectors", headers=alice)
    assert response.status_code == 503 and str(config) not in response.text


def test_connector_access_is_rechecked_after_reading(sources, monkeypatch):
    client, _, alice, _, config, entries, _ = sources
    preview = client.post("/api/connectors/ledger/preview", headers=alice).json()
    original = connectors.fetch

    def revoked(runtime, source):
        value = original(runtime, source)
        entries[0]["users"] = ["bob"]
        config.write_text(json.dumps(entries))
        return value

    monkeypatch.setattr(connectors, "fetch", revoked)
    response = client.post(
        "/api/connectors/ledger/import",
        headers=alice,
        json={"name": "Revoked", "expected_sha256": preview["sha256"]},
    )
    assert response.status_code == 404
    assert client.get("/api/datasets", headers=alice).json() == []


@pytest.mark.parametrize("mode", ["rows", "csv", "redirect", "incomplete", "oversized"])
def test_rest_import_bounds_auth_and_response_scope(sources, mode):
    client, runtime, alice, _, config, entries, _ = sources
    seen = []
    accepts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            accepts.append(self.headers.get("Accept"))
            value = (
                b"source,target\n001,1\n"
                if mode == "csv"
                else json.dumps(
                    {
                        "rows": [{"source": "001", "target": "1"}],
                        **({"next": "/page2"} if mode == "incomplete" else {}),
                    }
                ).encode()
            )
            if mode == "oversized":
                value = b"x" * 2048
            self.send_response(302 if mode == "redirect" else 200)
            self.send_header("Content-Length", str(len(value)))
            if mode == "redirect":
                self.send_header("Location", "/private")
            self.end_headers()
            self.wfile.write(value)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        entries.append(
            {
                "id": "remote",
                "name": "Remote source",
                "type": "rest",
                "users": ["alice"],
                "url": f"http://127.0.0.1:{server.server_port}/source",
                "headers": {"Authorization": "Bearer connector-fixture-secret"},
                "format": "csv" if mode == "csv" else "json_rows",
                "rows_field": "rows",
            }
        )
        config.write_text(json.dumps(entries))
        if mode == "oversized":
            runtime.settings = replace(runtime.settings, analytics_max_input_bytes=1024)
        response = client.post("/api/connectors/remote/preview", headers=alice)
        if mode in {"redirect", "incomplete", "oversized"}:
            assert response.status_code in {422, 502}, response.text
            assert client.get("/api/datasets", headers=alice).json() == []
            assert len(seen) == 1
        else:
            assert response.status_code == 200, response.text
            preview = response.json()
            assert preview["source_complete"] is False
            response = client.post(
                "/api/connectors/remote/import",
                headers=alice,
                json={"name": "Remote snapshot", "expected_sha256": preview["sha256"]},
            )
            assert response.status_code == 201, response.text
            assert not response.json()["source_complete"]
            assert (
                "connector-fixture-secret" not in response.text
                and "127.0.0.1" not in response.text
            )
        assert all(auth == "Bearer connector-fixture-secret" for _, auth in seen)
        assert accepts == ["text/csv" if mode == "csv" else "application/json"] * len(
            seen
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
