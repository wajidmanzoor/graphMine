import csv
import hashlib
import io
import json
import zipfile

import pytest
import test_workflow_templates as template_fixtures
from graphmine_agent.analytics_answers import suggested_questions
from test_accounts import PASSWORD, login

recipes = template_fixtures.recipes


def test_report_is_reproducible_complete_and_escaped(recipes):
    client, runtime, alice, bob, _, file, record, saved = recipes
    directory = runtime.analytics._directory(record)
    graph = runtime.graph_store.read_graph(file["id"], record["session_id"])
    runtime.analytics._write(
        directory / "inputs.json", {"main": {"kind": "graph", "data": graph}}
    )
    saved["steps"]["core"]["result"]["ports"]["unsafe"] = {
        "type": "scalar",
        "value": '<script>alert("secret")</script>',
        "complete": True,
    }
    runtime.analytics._write(directory / "result.json", saved)
    response = client.get("/api/workflows/original/report", headers=alice)
    assert response.status_code == 200, response.text
    assert (
        response.content
        == client.get("/api/workflows/original/report", headers=alice).content
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for path, info in manifest["files"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == info["sha256"]
        assert json.loads(archive.read("inputs.json"))["main"]["data"] == graph
        assert json.loads(archive.read("result.json")) == saved
        report = archive.read("report.html").decode()
        assert "<script>" not in report and "&lt;script&gt;" in report
        request = json.loads(archive.read("request.json"))
        assert request["expected_hash"] == record["validation"]["workflow_hash"]
    assert client.get("/api/workflows/original/report", headers=bob).status_code == 404


def test_csv_download_keeps_all_rows_and_neutralizes_text_formulas(recipes):
    client, runtime, alice, bob, _, _, record, _ = recipes
    rows = [{"vertex": i, "score": i} for i in range(2100)] + [
        {"vertex": "=1+1", "score": -5},
        {"vertex": 9007199254740993, "score": 3},
    ]
    runtime.analytics._write(
        runtime.analytics._directory(record) / "step-core.json",
        {
            "result": {
                "ports": {
                    "scores": {
                        "type": "vertex_scores",
                        "value": rows,
                        "complete": False,
                    }
                }
            }
        },
    )
    path = "/api/workflows/original/steps/core/ports/scores/csv"
    response = client.get(path, headers=alice)
    assert response.status_code == 200
    output = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(output) == 2102 and output[-2] == {"vertex": "'=1+1", "score": "-5"}
    assert output[-1]["vertex"] == "9007199254740993"
    assert client.get(path, headers=bob).status_code == 404


def test_followups_reflect_output_and_completeness():
    saved = {
        "steps": {
            "groups": {
                "result": {
                    "ports": {"groups": {"type": "vertex_groups", "complete": False}}
                }
            }
        }
    }
    assert suggested_questions(saved) == [
        "How many groups were found?",
        "Show the largest group.",
        "Is this result complete?",
    ]


def test_admin_activity_is_private_paginated_and_contains_no_credentials(recipes):
    client, runtime, alice, _, _, _, _, _ = recipes
    runtime.accounts.create_user("operator", PASSWORD, admin=True)
    admin = login(client, "operator")
    prefix = "/api/auth/admin/users/alice"
    assert (
        client.post(
            prefix + "/token-limit", headers=admin, json={"daily_token_limit": 40}
        ).status_code
        == 200
    )
    assert client.post(prefix + "/reset-tokens", headers=admin).status_code == 200
    assert client.post(prefix + "/disable", headers=admin).status_code == 204
    assert client.post(prefix + "/enable", headers=admin).status_code == 204
    password = "replacement-password-76"
    assert (
        client.post(
            prefix + "/reset-password", headers=admin, json={"password": password}
        ).status_code
        == 204
    )
    alice = login(client, "alice", password)
    assert client.get("/api/auth/admin/activity", headers=alice).status_code == 403
    first = client.get("/api/auth/admin/activity?limit=3", headers=admin).json()
    second = client.get(
        f"/api/auth/admin/activity?before={first[-1]['sequence']}&limit=3",
        headers=admin,
    ).json()
    assert not {row["sequence"] for row in first} & {row["sequence"] for row in second}
    assert first[0]["action"] == "password.reset" and first[0]["actor"] == "operator"
    text = json.dumps(first + second)
    assert password not in text and PASSWORD not in text and "Bearer" not in text


def test_audit_failure_rolls_back_account_change(recipes, monkeypatch):
    _, runtime, _, _, _, _, _, _ = recipes
    before = next(
        row["daily_token_limit"]
        for row in runtime.accounts.list_users()
        if row["username"] == "alice"
    )

    def failed(*_args, **_kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(runtime.accounts, "_audit", failed)
    with pytest.raises(RuntimeError):
        runtime.accounts.set_token_limit("alice", 123)
    after = next(
        row["daily_token_limit"]
        for row in runtime.accounts.list_users()
        if row["username"] == "alice"
    )
    assert after == before
