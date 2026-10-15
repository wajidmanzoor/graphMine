#!/usr/bin/env python3
"""Check the installed wheel in a fresh store; never open production data."""

import argparse
import hashlib
import io
import json
import secrets
import sqlite3
import statistics
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path


def check(repository, output):
    import graphmine_agent
    from fastapi.testclient import TestClient
    from graphmine_agent.api import create_app
    from graphmine_agent.config import Settings

    installed = Path(graphmine_agent.__file__).resolve()
    assert not installed.is_relative_to(repository), (
        "Smoke check must import the installed wheel"
    )
    report = {
        "scope": "Fresh wheel installation with existing verified native artifacts; isolated account, data and CPU workflows; bounded synthetic HTTP load",
        "package": str(installed),
        "checks": {},
    }
    with tempfile.TemporaryDirectory(prefix="graphmine-installed-") as directory:
        source = Path(directory) / "source.sqlite3"
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE connections(source TEXT,target TEXT)")
            db.execute("INSERT INTO connections VALUES ('001','002')")
        configuration = Path(directory) / "connectors.json"
        configuration.write_text(
            json.dumps(
                [
                    {
                        "id": "release_source",
                        "name": "Release source",
                        "type": "sqlite",
                        "path": str(source),
                        "table": "connections",
                        "users": ["release_checker"],
                    }
                ]
            )
        )
        configuration.chmod(0o600)
        settings = replace(
            Settings.from_env(repository),
            data_root=Path(directory),
            history_directory=None,
            accounts_enabled=True,
            account_cookie_secure=False,
            backup_directory=None,
            analytics_python=Path(sys.executable).absolute(),
            analytics_gpu_uuids=(),
            graph_gpu_uuid="",
            llm_gpu_uuid="",
            llm_enabled=False,
            connectors_file=configuration,
        )
        with TestClient(create_app(settings)) as client:
            password = secrets.token_urlsafe(24)
            runtime = client.app.state.runtime
            runtime.accounts.create_user("release_checker", password, admin=True)
            login = client.post(
                "/api/auth/login",
                json={
                    "username": "release_checker",
                    "password": password,
                    "issue_token": True,
                },
                headers={"X-GraphMine-Request": "1"},
            )
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            client.cookies.clear()

            def request(method, path, expected=200, **kwargs):
                response = client.request(method, path, headers=headers, **kwargs)
                if response.status_code != expected:
                    raise AssertionError(
                        f"{method} {path}: {response.status_code}: {response.text[:500]}"
                    )
                return response

            for name in (
                "analytics-ui",
                "analytics-controls",
                "analytics-library",
                "analytics-import",
                "analytics-templates",
                "analytics-outputs",
                "analytics-editor",
                "analytics-explorer",
                "analytics-projects",
                "analytics-connectors",
                "projects",
                "project-viewer",
                "shared",
            ):
                assert client.get(f"/{name}.js").status_code == 200
            report["checks"]["packaged_assets"] = True
            sessions = [
                request("POST", "/api/sessions", 201, json={"title": title}).json()[
                    "id"
                ]
                for title in ("Original", "Reused")
            ]
            csv = b"source,target\n0,1\n1,2\n0,2\n"
            preview = request(
                "POST",
                f"/api/sessions/{sessions[0]}/files/preview",
                files={"file": ("triangle.csv", csv)},
            ).json()
            assert preview["metadata"]["vertex_count"] == 3
            assert request("GET", f"/api/sessions/{sessions[0]}/files").json() == []
            file = request(
                "POST",
                f"/api/sessions/{sessions[0]}/files",
                201,
                files={"file": ("triangle.csv", csv)},
            ).json()
            version = request(
                "POST",
                "/api/datasets",
                201,
                json={"name": "Triangle", "file_id": file["id"]},
            ).json()
            imported = request(
                "POST",
                f"/api/sessions/{sessions[1]}/datasets/{version['id']}/import",
                201,
            ).json()["file"]
            plan = {
                "version": 1,
                "device": "cpu",
                "steps": [
                    {
                        "id": "groups",
                        "operation": "maximal-cliques",
                        "input": {"input": "main"},
                        "parameters": {},
                    }
                ],
            }
            record = request(
                "POST",
                f"/api/sessions/{sessions[1]}/workflows",
                201,
                json={
                    "mode": "interactive",
                    "plan": plan,
                    "inputs": {"main": {"file_id": imported["id"], "kind": "graph"}},
                },
            ).json()
            assert record["status"] == "awaiting_review" and not runtime.analytics.tasks
            request(
                "POST",
                f"/api/workflows/{record['id']}/run",
                202,
                json={
                    "expected_revision": 1,
                    "workflow_hash": record["validation"]["workflow_hash"],
                },
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                finished = request("GET", f"/api/workflows/{record['id']}").json()
                if finished["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)
            assert finished["status"] == "completed", finished.get("error")
            result = request("GET", f"/api/workflows/{record['id']}/result").json()
            groups = result["steps"]["groups"]["result"]["ports"]["groups"]["value"]
            assert [sorted(group["vertices"]) for group in groups] == [[0, 1, 2]]
            report["checks"]["cpu_csv_reuse_and_native_workflow"] = True
            template = request(
                "POST",
                "/api/workflow-templates",
                201,
                json={
                    "name": "Clique recipe",
                    "workflow_id": record["id"],
                    "expected_revision": 1,
                },
            ).json()
            reused = request(
                "POST",
                f"/api/sessions/{sessions[1]}/workflow-templates/{template['id']}/use",
                201,
                json={"inputs": {"main": {"file_id": imported["id"], "kind": "graph"}}},
            ).json()
            assert reused["status"] == "awaiting_review" and not reused.get(
                "approved_hash"
            )
            report["checks"]["template_review"] = True
            raw = request("GET", f"/api/workflows/{record['id']}/report").content
            with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
                manifest = json.loads(bundle.read("manifest.json"))
                for name, info in manifest["files"].items():
                    assert (
                        hashlib.sha256(bundle.read(name)).hexdigest() == info["sha256"]
                    )
            report["checks"]["reproducible_report"] = True
            project = request(
                "POST", "/api/projects", 201, json={"name": "Release project"}
            ).json()
            shared = request(
                "POST",
                f"/api/projects/{project['id']}/items",
                201,
                json={"name": "Triangle snapshot", "version_id": version["id"]},
            ).json()
            link = request(
                "POST", f"/api/project-items/{shared['id']}/links", 201, json={}
            ).json()
            token = link["url"].split("#")[1]
            public = client.post("/api/shared/read", json={"token": token})
            assert (
                public.status_code == 200
                and len(public.json()["snapshot"]["data"]["vertices"]) == 3
            )
            request("DELETE", f"/api/project-links/{link['id']}", 204)
            assert (
                client.post("/api/shared/read", json={"token": token}).status_code
                == 404
            )
            report["checks"]["project_snapshot_and_revocable_link"] = True
            preview = request("POST", "/api/connectors/release_source/preview").json()
            version2 = request(
                "POST",
                "/api/connectors/release_source/import",
                201,
                json={
                    "name": "Database snapshot",
                    "expected_sha256": preview["sha256"],
                },
            ).json()
            assert (
                version2["source"]["connector_type"] == "sqlite"
                and version2["source_complete"]
            )
            report["checks"]["readonly_database_import"] = True
            request("DELETE", f"/api/sessions/{sessions[0]}", 204)
            assert len(request("GET", "/api/datasets").json()) == 2
            before = request("GET", "/api/auth/me").json()["quota"]

            def read(index):
                started = time.monotonic()
                response = client.get(
                    f"/api/files/{imported['id']}/graph-preview",
                    headers=headers if index % 5 else {},
                )
                assert response.status_code in ({200, 429} if index % 5 else {401})
                return response.status_code, time.monotonic() - started

            with ThreadPoolExecutor(max_workers=8) as pool:
                readings = list(pool.map(read, range(64)))
            after = request("GET", "/api/auth/me").json()["quota"]
            for key in ("tokens_used", "jobs_used"):
                assert before[key] == after[key]
            report["load"] = {
                "requests": len(readings),
                "concurrency": 8,
                "statuses": {
                    str(code): sum(status == code for status, _ in readings)
                    for code in {status for status, _ in readings}
                },
                "median_seconds": statistics.median(elapsed for _, elapsed in readings),
                "max_seconds": max(elapsed for _, elapsed in readings),
            }
            assert report["load"]["statuses"].get("200", 0) > 0
            report["checks"]["isolated_http_load_and_auth"] = True
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {"passed": True, "checks": list(report["checks"]), "load": report["load"]}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    check(arguments.repository.resolve(), arguments.output)
