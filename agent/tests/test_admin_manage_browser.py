"""Real browser writes for Capacity, cleanup, and measured perf comparisons."""

import json

from graphmine_agent.admin_performance import Performance
from test_admin_browser import browser_app, pw, screenshot, sign_in
from test_admin_manage import make_run


def test_capacity_storage_and_performance_pages(browser_app, triangle_graph, monkeypatch, tmp_path):
    browser, base, _, accounts = browser_app
    perf_root = tmp_path / "perf-repo"
    monkeypatch.setattr(Performance, "root", property(lambda self: perf_root))
    make_run(perf_root / "var/perf", "review-before", 1200)
    make_run(perf_root / "var/perf", "review-after", 800)
    page = browser.new_page(viewport={"width": 1440, "height": 1180}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    headers = {"X-GraphMine-Request": "1"}
    session = page.request.post(base + "/api/sessions", data={"domain_id": "general"}, headers=headers)
    assert session.ok, session.text()
    upload = page.request.post(base + f"/api/sessions/{session.json()['id']}/files", headers=headers,
                               multipart={"file": {"name": "triangle.json", "mimeType": "application/json", "buffer": triangle_graph}})
    assert upload.ok, upload.text()
    page.goto(base + "/admin#capacity")
    pw.expect(page.get_by_role("heading", name="Capacity settings", exact=True)).to_be_visible()
    pw.expect(page.locator(".capacity-row")).to_have_count(14)
    screenshot(page, "capacity")
    queue = page.locator("#capacity-MODEL_QUEUE_SECONDS")
    queue.fill("45")
    pw.expect(page.locator(".capacity-savebar")).to_contain_text("1 unsaved change")
    pw.expect(page.locator(".capacity-row.changed")).to_have_count(1)
    screenshot(page, "capacity-unsaved")
    page.get_by_role("button", name="Save…", exact=True).click()
    pw.expect(page.get_by_role("dialog")).to_contain_text("60 → 45")
    page.get_by_role("dialog").get_by_role("button", name="Save changes", exact=True).click()
    pw.expect(page.locator("#page-notice")).to_contain_text("Settings saved and applied")
    pw.expect(page.locator(".capacity-savebar")).not_to_be_visible()
    with accounts.database._connect() as db:
        row = db.execute('SELECT actor,"after" FROM admin_activity WHERE action=\'settings.updated\'').fetchone()
        assert row[0] == "review-admin" and json.loads(row[1])["MODEL_QUEUE_SECONDS"] == 45
    page.goto(base + "/admin#data")
    pw.expect(page.get_by_role("heading", name="Data & storage", exact=True)).to_be_visible()
    pw.expect(page.get_by_text("triangle.json", exact=True)).to_be_visible()
    assert "NaN" not in page.locator("#page-content").inner_text()
    page.get_by_role("button", name="Back up now", exact=True).click()
    pw.expect(page.locator("#page-notice")).to_contain_text("Snapshot created and verified", timeout=20000)
    screenshot(page, "data")
    with page.expect_download() as event:
        page.get_by_role("button", name="Download", exact=True).click()
    assert event.value.suggested_filename == "triangle.json"
    page.get_by_role("button", name="Delete unused files…", exact=True).click()
    pw.expect(page.get_by_role("dialog")).to_contain_text("triangle.json")
    screenshot(page, "cleanup-preview")
    with page.expect_response(lambda response: response.url.endswith("/api/admin/data/cleanup") and response.request.method == "POST") as deleted:
        page.get_by_role("dialog").get_by_role("button", name="Delete 1 files", exact=True).click()
    assert deleted.value.ok, deleted.value.text()
    pw.expect(page.locator("#page-notice")).to_contain_text("Removed 1 items")
    pw.expect(page.get_by_text("triangle.json", exact=True)).not_to_be_visible()
    page.goto(base + "/admin#performance")
    pw.expect(page.get_by_role("heading", name="Performance", exact=True)).to_be_visible()
    pw.expect(page.get_by_role("button", name="Start a test…", exact=True)).not_to_be_visible()
    pw.expect(page.get_by_text("Performance suite isn't installed.", exact=True)).to_be_visible()
    page.get_by_label("Select review-before", exact=True).check()
    page.get_by_label("Select review-after", exact=True).check()
    pw.expect(page.get_by_role("button", name="Compare selected (2)", exact=True)).to_be_enabled()
    pw.expect(page.locator(".performance-lower table")).to_contain_text("0.8 s")
    screenshot(page, "performance")
    for route in ("capacity", "data", "performance"):
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/admin#" + route)
        pw.expect(page.locator("#page-content h1")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), route
        screenshot(page, route + "-mobile")
    assert errors == []
    page.close()
