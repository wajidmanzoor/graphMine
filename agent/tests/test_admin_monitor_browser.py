"""Phase 2 pages use the disposable API and expose measured/unavailable states."""

from test_admin_browser import browser_app, pw, screenshot, sign_in


def test_monitor_pages_and_live_model_settings(browser_app):
    browser, base, _, _ = browser_app
    page = browser.new_page(viewport={"width": 1440, "height": 1180}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    for name in ("overview", "health", "model"):
        page.goto(base + "/admin#" + name)
        pw.expect(page.get_by_role("heading", name=name.title(), exact=True)).to_be_visible(timeout=20000)
        pw.expect(page.locator(".metric,.monitor-card").first).to_be_visible()
        assert "NaN" not in page.locator("#page-content").inner_text()
        screenshot(page, name)
        if name == "health":
            page.get_by_role("button", name="Run self-test", exact=True).click()
            dialog = page.get_by_role("dialog", name="Run self-test", exact=True)
            pw.expect(dialog.get_by_text("No self-test has run yet.", exact=True)).to_be_visible()
            screenshot(page, "selftest-dialog")
            dialog.get_by_role("button", name="Close", exact=True).last.click()
    page.get_by_label("Idle for", exact=True).select_option("60")
    page.get_by_label("Route", exact=True).uncheck()
    page.get_by_role("button", name="Save model settings", exact=True).click()
    pw.expect(page.get_by_text("Saved. New calls use these settings.", exact=True)).to_be_visible()
    page.reload()
    pw.expect(page.get_by_label("Idle for", exact=True)).to_have_value("60")
    pw.expect(page.get_by_label("Route", exact=True)).not_to_be_checked()
    page.goto(base + "/admin#activity?kind=admin_change")
    pw.expect(page.get_by_role("button", name="review-admin: settings.updated · model", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/admin#overview")
    pw.expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible(timeout=20000)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, "overview-mobile")
    assert errors == []
    page.close()
