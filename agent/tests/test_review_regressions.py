"""Regressions for count-only answers, bounded payloads and concurrent admission."""

import asyncio
import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graphmine_agent.account_api import account_io
from graphmine_agent.analytics_answers import build_facts, suggested_questions
from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
from graphmine_agent.api import create_app
from graphmine_agent.result_index import build_workflow, open_index
from graphmine_agent.web_assets import WebAssets


def test_count_only_answer_never_claims_zero_groups_or_offers_empty_group():
    saved = {"steps": {"count": {"status": "completed", "result": {
        "problem": "triangle-counting", "quality": "exact", "complete": True,
        "ports": {"count": {"type": "scalar", "value": 1, "complete": True},
                  "groups": {"type": "vertex_groups", "value": [], "complete": False}},
    }}}}
    facts = build_facts(saved, {}, {})
    assert any("count is 1" in fact["statement"] for fact in facts)
    assert not any("found no" in fact["statement"] for fact in facts)
    assert any("did not retain" in fact["statement"] for fact in facts)
    assert "Show the largest group." not in suggested_questions(saved)
    saved["steps"]["count"]["result"]["ports"]["groups"]["complete"] = True
    assert any("found no groups" in fact["statement"] for fact in build_facts(saved, {}, {}))


def test_summary_does_not_retain_unpaged_native_collections(tmp_path):
    rows = [{"group": i, "vertices": [i, i + 1, i + 2]} for i in range(10000)]
    saved = {"steps": {"groups": {"status": "completed", "result": {
        "result": {"groups": rows, "nested": {"instances": rows}, "count": 10000},
        "ports": {"groups": {"type": "vertex_groups", "value": rows, "complete": True}},
    }}}}
    with open_index(tmp_path / "rows.db", lambda: "unchanged", lambda db: build_workflow(db, saved)) as index:
        summary = index.summary(1)
        assert len(json.dumps(summary)) < 2000
        result = summary["steps"]["groups"]["result"]
        assert result["result"] == {"count": 10000} and result["raw_result_truncated"]
        assert result["ports"]["groups"]["total_items"] == 10000
        assert index.page(json.dumps(["groups", "groups"], separators=(",", ":")), 9999, 1)["items"] == rows[-1:]
    assert len(saved["steps"]["groups"]["result"]["result"]["groups"]) == 10000


@pytest.mark.asyncio
async def test_sqlite_lock_wait_keeps_event_loop_responsive(tmp_path):
    path = tmp_path / "locks.db"
    blocker = sqlite3.connect(path)
    blocker.execute("CREATE TABLE leases (id TEXT)")
    blocker.execute("BEGIN IMMEDIATE")
    started = threading.Event()

    def acquire():
        with sqlite3.connect(path, timeout=5) as connection:
            started.set()
            connection.execute("INSERT INTO leases VALUES ('lease')")
        return "lease"

    task = asyncio.create_task(account_io(acquire))
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait), 2)
        await asyncio.wait_for(asyncio.sleep(0.02), 0.5)
        assert not task.done()
    finally:
        blocker.rollback()
        blocker.close()
    assert await task == "lease"


@pytest.mark.asyncio
async def test_cancelled_admission_releases_a_lease_acquired_by_the_thread():
    started, finish = threading.Event(), threading.Event()
    released = []

    def acquire():
        started.set()
        assert finish.wait(3)
        return "lease"

    task = asyncio.create_task(account_io(acquire, on_cancel=released.append))
    await asyncio.wait_for(asyncio.to_thread(started.wait), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()  # Cleanup must also survive repeated cancellation.
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released == ["lease"]


def test_direct_plan_is_narrow_and_device_verified(settings):
    planner = AnalyticsPlanner(settings, None, None)
    body = PlanningRequest(message="Count triangles", device="cpu", inputs={"main": {"file_id": "input"}})
    inputs, cards = {"main": {"kind": "graph"}}, [{"id": "triangle-counting"}]
    assert planner.direct_plan(body, inputs, cards)["steps"][0]["parameters"] == {"mode": "count"}
    assert planner.direct_plan(body, inputs, []) is None
    for message in ["Do not count triangles", "Count triangles around Alice", "Count triangles and rank vertices", "Count triangles in the selected group"]:
        assert planner.direct_plan(body.model_copy(update={"message": message}), inputs, cards) is None
    assert planner.direct_plan(body.model_copy(update={"previous_workflow_id": "earlier"}), inputs, cards) is None
    assert planner.direct_plan(body, {**inputs, "second": {"kind": "graph"}}, cards) is None
    assert AnalyticsPlanner(replace(settings, analytics_direct_plans=False), None, None).direct_plan(body, inputs, cards) is None


def test_assets_and_backend_identity_stay_frozen_until_restart(tmp_path):
    (tmp_path / "x.js").write_text("window.example = 1;")
    for name in ("analytics.html", "index.html"):
        (tmp_path / name).write_text('<head><script src="/x.js" defer></script></head>')
    assets = WebAssets(tmp_path)
    original = dict(assets.bundles)
    (tmp_path / "x.js").write_text("window.example = 2;")
    assert assets.bundles == original
    assert WebAssets(tmp_path).build_id != assets.build_id
    assert assets.build_id in assets.pages["analytics.html"]


def test_compression_caching_security_and_public_build(settings):
    with TestClient(create_app(replace(settings, accounts_enabled=True))) as client:
        build = client.get("/api/build")
        assert build.status_code == 200
        page = client.get("/")
        assert build.json()["build_id"] in page.text
        assert page.headers["content-encoding"] == "gzip"
        assert page.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        import re
        scripts = re.findall(r'<script src="([^"]+)"', page.text)
        assert len(scripts) == 1
        asset = client.get(scripts[0])
        assert "immutable" in asset.headers["cache-control"]
        assert asset.headers["content-encoding"] == "gzip"
        assert client.get(scripts[0], headers={"If-None-Match": asset.headers["etag"]}).status_code == 304
        denied = client.get("/api/sessions")
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "private, no-store"
