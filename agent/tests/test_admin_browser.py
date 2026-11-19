"""Playwright acceptance with a disposable server and real account/API writes."""

import json
import os
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn

from graphmine_agent.accounts import Accounts
from graphmine_agent.api import create_app
from graphmine_agent.database import Database
from graphmine_agent.models import ConversationEvent, SessionRecord
from graphmine_agent.identity import identity_scope

pw = pytest.importorskip("playwright.sync_api")
PASSWORD = "browser-only-test-password"


@pytest.fixture
def browser_app(settings, tmp_path, monkeypatch):
    auth = tmp_path / "studio-auth"
    auth.mkdir()
    (auth / "users.json").write_text(json.dumps({"version": 1, "users": {"studio-owner": {"role": "admin"}}}))
    monkeypatch.setenv("GRAPHMINE_STUDIO_AUTH_DIR", str(auth))
    configured = replace(settings, accounts_enabled=True, account_cookie_secure=False, api_token=None)
    accounts = Accounts(configured, Database(configured.database_path))
    accounts.create_user("review-admin", PASSWORD, admin=True)
    accounts.create_user("review-member", PASSWORD)
    token, member = accounts.login("review-member", PASSWORD, "127.0.0.1")
    with identity_scope(member):
        session = accounts.database.create_session(SessionRecord(domain_id="general", title="Support example"))
        for role, text in (("user", "Help me understand my saved calculation"), ("assistant", "This is the saved response")):
            accounts.database.add_event(ConversationEvent(session_id=session.id, type="workflow.chat", payload={"role": role, "turn_id": "review-turn", "message": text}))
    app = create_app(configured)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.05)
    assert server.started
    with pw.sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            server.should_exit = True
            thread.join(15)
            pytest.skip("Install Playwright Chromium to run browser acceptance")
        browser = playwright.chromium.launch(headless=True)
        yield browser, f"http://127.0.0.1:{port}", auth, accounts
        browser.close()
    server.should_exit = True
    thread.join(15)
    assert not thread.is_alive()


def sign_in(page, base, username):
    response = page.request.post(base + "/api/auth/login", data={"username": username, "password": PASSWORD}, headers={"X-GraphMine-Request": "1"})
    assert response.ok, response.text()


def screenshot(page, name):
    target = os.getenv("GRAPHMINE_ADMIN_SCREENSHOTS")
    if target:
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / (name + ".png")), full_page=True)


def test_users_dialogs_activity_support_and_responsive_shell(browser_app):
    browser, base, auth, accounts = browser_app
    page = browser.new_page(viewport={"width": 1440, "height": 1180}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    page.goto(base + "/")
    pw.expect(page.get_by_role("link", name="Admin", exact=True)).to_be_visible()
    page.get_by_role("link", name="Admin", exact=True).click()
    page.get_by_role("link", name="Users", exact=False).click()
    pw.expect(page.get_by_role("heading", name="Users", exact=True)).to_be_visible()
    pw.expect(page.get_by_role("button", name="review-member", exact=True)).to_be_visible()
    screenshot(page, "01-users")
    page.get_by_role("button", name="+ Add user").click()
    dialog = page.get_by_role("dialog")
    screenshot(page, "02-add-user")
    dialog.get_by_label("Username", exact=True).fill("browser-created")
    dialog.get_by_label("Temporary password", exact=False).fill(PASSWORD)
    dialog.get_by_label("Dataset Studio", exact=True).check()
    dialog.get_by_role("button", name="Create user", exact=True).click()
    pw.expect(page.get_by_role("button", name="browser-created", exact=True)).to_be_visible()
    assert "browser-created" in json.loads((auth / "users.json").read_text())["users"]
    page.get_by_role("button", name="browser-created", exact=True).click()
    screenshot(page, "03-edit-user")
    page.get_by_role("dialog").get_by_role("button", name="Delete…", exact=True).click()
    pw.expect(page.get_by_role("dialog", name="Delete browser-created")).to_be_visible()
    screenshot(page, "04-delete-user")
    page.get_by_role("dialog").get_by_role("button", name="Cancel", exact=True).click()
    page.get_by_role("link", name="Activity", exact=True).click()
    pw.expect(page.get_by_role("button", name="review-admin: account.created · browser-created", exact=True)).to_be_visible()
    screenshot(page, "05-activity")
    page.get_by_role("button", name="review-admin: account.created · browser-created", exact=True).click()
    pw.expect(page.get_by_role("heading", name="Before → after")).to_be_visible()
    screenshot(page, "06-admin-change")
    page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
    page.get_by_role("button", name="Question completed", exact=True).click()
    pw.expect(page.get_by_role("dialog")).not_to_contain_text("Help me understand my saved calculation")
    screenshot(page, "07-question-details")
    page.get_by_role("button", name="Open conversation (support)…").click()
    screenshot(page, "08-support-access")
    page.get_by_label("Reason for access", exact=True).fill("Investigate a reported problem")
    page.get_by_role("button", name="Open read-only", exact=True).click()
    pw.expect(page.get_by_text("Support access · read-only", exact=False)).to_be_visible()
    pw.expect(page.locator(".message").filter(has_text="Help me understand my saved calculation")).to_be_visible()
    assert page.locator("#page-content input, #page-content textarea").count() == 0
    screenshot(page, "09-support-read-only")
    page.goto(base + "/admin#users")
    page.set_viewport_size({"width": 390, "height": 844})
    pw.expect(page.get_by_role("heading", name="Users", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, "10-users-mobile")
    assert errors == []
    page.close()


def test_member_and_signed_out_cannot_open_console(browser_app):
    browser, base, _, _ = browser_app
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(base + "/admin")
    pw.expect(page.get_by_role("heading", name="You need administrator access")).to_be_visible()
    sign_in(page, base, "review-member")
    page.goto(base + "/")
    pw.expect(page.locator("#account-settings-button")).to_be_visible()
    pw.expect(page.get_by_role("link", name="Admin", exact=True)).not_to_be_visible()
    page.goto(base + "/admin")
    pw.expect(page.get_by_role("heading", name="You need administrator access")).to_be_visible()
    screenshot(page, "11-access-required")
    page.close()
