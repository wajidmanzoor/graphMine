"""Real browser acceptance for the semantic admin page, on disposable services."""

import re

from test_admin_browser import browser_app, sign_in, screenshot, pw  # noqa: F401
from test_admin_semantic import model_catalog  # noqa: F401
from test_semantic_native import native_engine  # noqa: F401


def test_semantic_configuration_and_provider_flows(browser_app, model_catalog, native_engine):
    browser, base, _, accounts = browser_app
    url, calls, _ = model_catalog
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    page.goto(base + "/admin#semantic")
    pw.expect(page.get_by_role("heading", name="Semantic engine", exact=True)).to_be_visible()
    pw.expect(page.get_by_label("Reuse saved answers")).to_be_enabled()
    pw.expect(page.get_by_role("button", name="Clear retained answers")).to_be_enabled()
    pw.expect(page.get_by_role("button", name="Test mock pipeline")).to_have_count(0)
    screenshot(page, "semantic-desktop")

    page.get_by_role("button", name="Add provider", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Provider name", exact=True).fill("Browser provider")
    dialog.get_by_label("Base URL", exact=False).fill(url)
    dialog.get_by_label("API key", exact=False).fill("synthetic-browser-key")
    dialog.get_by_role("button", name="Save provider").click()
    pw.expect(dialog).not_to_be_visible()
    provider = page.get_by_role("row").filter(has_text="Browser provider")
    provider.get_by_role("button", name="Test connection").click()
    pw.expect(provider.get_by_text(re.compile("Connected · checked"))).to_be_visible()
    assert calls[-1] == ("/v1/models", "Bearer synthetic-browser-key")

    page.get_by_role("button", name="Add model alias").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Alias", exact=False).fill("browser_test")
    dialog.get_by_label("Provider", exact=True).select_option(label="Browser provider")
    dialog.get_by_label("Model ID", exact=False).fill("fixture-model")
    dialog.get_by_role("button", name="Save alias").click()
    pw.expect(dialog).not_to_be_visible()
    pw.expect(page.get_by_role("cell", name="browser_test", exact=True)).to_be_visible()

    page.get_by_label("Model steps", exact=True).select_option("live")
    page.get_by_label("Reuse saved answers").check()
    page.get_by_label("Semantic requests at once", exact=False).fill("2")
    pw.expect(page.get_by_text(re.compile("Semantic concurrency meets or exceeds"))).to_be_visible()
    page.get_by_label("Rows per request", exact=False).fill("2")
    page.get_by_label("Default call limit", exact=False).fill("3")
    page.get_by_label("Maximum call limit", exact=False).fill("7")
    page.get_by_label("Worker timeout (seconds)", exact=False).fill("10")
    page.get_by_label("Who may run model steps", exact=True).select_option("selected")
    page.get_by_label("review-member", exact=True).check()
    page.get_by_role("button", name="Review settings…").click()
    dialog = page.get_by_role("dialog", name="Save semantic settings")
    pw.expect(dialog.get_by_text("100 → 3", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Save changes").click()
    pw.expect(dialog).not_to_be_visible()
    page.reload()
    pw.expect(page.get_by_label("Default call limit", exact=False)).to_have_value("3")
    pw.expect(page.get_by_label("review-member", exact=True)).to_be_checked()
    response = page.request.get(base + "/api/admin/semantic")
    assert "synthetic-browser-key" not in response.text()
    assert response.json()["values"]["GRAPHMINE_SEMANTIC_MAX_CALLS"] == 7
    assert response.json()["values"]["GRAPHMINE_SEMANTIC_MODE"] == "live"
    assert response.json()["values"]["GRAPHMINE_SEMANTIC_CACHE_ENABLED"] is True
    page.get_by_role("button", name="Clear retained answers").click()
    page.get_by_role("dialog", name="Clear retained answers").get_by_role("button", name="Clear answers", exact=True).click()
    pw.expect(page.get_by_role("dialog")).not_to_be_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("heading", name="Semantic engine", exact=True).scroll_into_view_if_needed()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    screenshot(page, "semantic-mobile")
    page.get_by_role("button", name="Add provider", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("API key", exact=False).fill("temporary-secret")
    page.keyboard.press("Escape")
    pw.expect(dialog).not_to_be_visible()
    pw.expect(page.locator("input[type=password]")).to_have_count(0)

    row = page.get_by_role("row").filter(has_text="browser_test")
    row.get_by_role("button", name="Remove", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Remove", exact=True).click()
    pw.expect(page.get_by_role("cell", name="browser_test", exact=True)).not_to_be_visible()
    page.get_by_role("row").filter(has_text="Browser provider").get_by_role("button", name="Remove", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Remove", exact=True).click()
    pw.expect(page.get_by_text("Browser provider", exact=True)).not_to_be_visible()
    assert errors == []
    page.close()


def test_member_cannot_open_semantic_admin_controls(browser_app):
    browser, base, _, _ = browser_app
    page = browser.new_page()
    sign_in(page, base, "review-member")
    page.goto(base + "/admin#semantic")
    pw.expect(page.get_by_role("heading", name="You need administrator access")).to_be_visible()
    pw.expect(page.get_by_role("button", name="Test mock pipeline")).not_to_be_visible()
    assert page.request.get(base + "/api/admin/semantic").status == 403
    page.close()
