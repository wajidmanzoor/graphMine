"""Browser acceptance for the live queue and local, CSP-safe Vega-Lite charts."""

import json
import sqlite3
import time
from datetime import datetime, timezone

from graphmine_agent import admin_events
from graphmine_agent.identity import identity_scope
from graphmine_agent.models import SessionRecord
from test_admin_browser import browser_app, pw, screenshot, sign_in, PASSWORD


def test_jobs_details_usage_charts_compare_export_and_mobile(browser_app):
    browser, base, _, accounts = browser_app
    _, principal = accounts.login("review-member", PASSWORD, "local")
    now = time.time()
    with identity_scope(principal):
        session = accounts.database.create_session(SessionRecord(domain_id="general", title="Private browser test"))
    for i in range(7):
        admin_events.record(accounts.database, "question", "Question completed", user_id=principal.user_id, ts=now - i * 86400 - 1,
                            duration_ms=900 + i * 100, details={"tokens": 100 + i * 20, "reasoning_tokens": 30, "stage_ms": {"route": 600 + i * 50, "analyst": 300}})
        admin_events.record(accounts.database, "calculation", "Calculation completed", user_id=principal.user_id, ts=now - i * 86400 - 1,
                            duration_ms=300 + i * 10, outcome="completed", details={"problems": ["k-core"], "datasets": ["triangle.json"]})
    admin_events.record(accounts.database, "error", "Queue full", outcome="queue_full", details={"code": "queue_full"})
    stamp = datetime.fromtimestamp(now - 10, timezone.utc).isoformat()
    record = {"id": "browser-saved-work", "session_id": session.id, "revision": 1, "mode": "expert", "status": "failed", "created_at": stamp,
              "approved_at": stamp, "started_at": stamp, "finished_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
              "validation": {"plan": {"device": "cpu", "steps": [{"id": "core", "problem": "k-core", "device": "cpu", "parameters": {"k": 2}}]}},
              "steps": {"core": {"status": "failed"}}, "error": {"code": "worker_failure", "message": "Browser acceptance error example"},
              "input_provenance": {"graph": {"file_snapshot": {"name": "triangle.json", "graph": {"vertex_count": 3, "edge_count": 3}}}}}
    with sqlite3.connect(accounts.settings.data_root / "analytics" / "workflows.sqlite3") as db:
        db.execute("INSERT INTO workflows VALUES (?,?,?)", (record["id"], session.id, json.dumps(record)))
    page = browser.new_page(viewport={"width": 1440, "height": 1180}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    page.goto(base + "/admin#jobs")
    pw.expect(page.get_by_role("heading", name="Jobs & queue", exact=True)).to_be_visible()
    page.get_by_role("button", name="Finished today", exact=True).click()
    pw.expect(page.get_by_text("k-core", exact=True)).to_be_visible()
    screenshot(page, "jobs")
    page.get_by_role("button", name="Why it failed", exact=True).click()
    pw.expect(page.get_by_role("dialog")).to_contain_text("Browser acceptance error example")
    pw.expect(page.get_by_role("dialog")).not_to_contain_text("Private browser test")
    screenshot(page, "calculation-details")
    page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
    page.goto(base + "/admin#usage")
    response = page.request.get(base + "/admin")
    assert "unsafe-eval" not in response.headers["content-security-policy"]
    pw.expect(page.locator(".usage-chart svg")).to_have_count(6, timeout=20000)
    assert "could not be rendered" not in page.locator("#page-content").inner_text()
    assert "NaN" not in page.locator("#page-content").inner_text()
    screenshot(page, "usage")
    page.get_by_role("button", name="7 days", exact=True).click()
    pw.expect(page.locator(".subtitle")).to_contain_text("Last 7 days compared")
    page.get_by_label("Compare", exact=True).uncheck()
    pw.expect(page.locator(".subtitle")).not_to_contain_text("compared")
    pw.expect(page.locator(".usage-chart svg")).to_have_count(6)
    with page.expect_download() as event:
        page.get_by_role("button", name="Export", exact=True).click()
    assert event.value.suggested_filename == "graphmine-usage.csv"
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    pw.expect(page.locator(".usage-chart svg")).to_have_count(6)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, "usage-mobile")
    assert errors == []
    page.close()
