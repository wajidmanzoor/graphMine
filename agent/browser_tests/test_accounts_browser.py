"""Real browser login against an isolated API, without model or GPU work."""

import shutil
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn
from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.models import SessionRecord
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "browser-test-password-42"


def test_account_login_logout_and_private_workspaces(tmp_path, monkeypatch):
    snap = Path("/snap/firefox/current/usr/lib/firefox")
    firefox = (
        str(snap / "firefox")
        if (snap / "firefox").exists()
        else shutil.which("firefox")
    )
    gecko = (
        str(snap / "geckodriver")
        if (snap / "geckodriver").exists()
        else shutil.which("geckodriver")
    )
    if not firefox or not gecko:
        pytest.skip("Firefox and geckodriver are required")

    async def capabilities(_self):
        return {
            "operations": [],
            "question_planner_enabled": False,
            "device_configuration": {"gpu_configured": False},
        }

    monkeypatch.setattr(AnalyticsService, "capabilities", capabilities)
    settings = replace(
        Settings.from_env(ROOT),
        data_root=tmp_path / "data",
        accounts_enabled=True,
        account_cookie_secure=False,
        llm_enabled=False,
        graph_gpu_uuid="",
        llm_gpu_uuid="",
        graphmine_binary=tmp_path / "no-binary",
    )
    app = create_app(settings)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    driver = None
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        runtime = app.state.runtime
        alice = runtime.accounts.create_user("alice", PASSWORD, admin=True)["id"]
        runtime.accounts.create_user("bob", PASSWORD)
        runtime.accounts.settle_tokens(
            runtime.accounts.reserve_tokens(alice, 14000), 12500
        )
        with identity_scope(Principal(alice, "alice", runtime.accounts)):
            runtime.database.create_session(
                SessionRecord(domain_id="general", title="Alice private research")
            )

        options = Options()
        options.add_argument("-headless")
        options.binary_location = firefox
        driver = webdriver.Firefox(
            options=options, service=Service(executable_path=gecko)
        )
        driver.set_window_size(1400, 1000)
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        driver.get(base)
        wait = WebDriverWait(driver, 20)
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
        )
        assert (
            "provided by your administrator"
            in driver.find_element(By.CSS_SELECTOR, ".account-dialog").text
        )

        def sign_in(name, password=PASSWORD):
            field = driver.find_element(By.ID, "account-username")
            field.clear()
            field.send_keys(name)
            driver.find_element(By.ID, "account-password").send_keys(password)
            driver.find_element(By.ID, "account-sign-in").click()

        sign_in("alice", "incorrect-password")
        wait.until(lambda d: "Incorrect" in d.find_element(By.ID, "account-error").text)
        assert (
            driver.find_element(By.ID, "account-password").get_attribute("value") == ""
        )
        driver.save_screenshot(str(tmp_path / "login.png"))
        sign_in("alice")
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-name").text == "alice"
        )
        driver.find_element(By.ID, "account-settings-button").click()
        wait.until(lambda d: "50,000" in d.find_element(By.ID, "account-quota").text)
        meter = driver.find_element(By.CSS_SELECTOR, "#account-quota progress")
        assert meter.get_attribute("value") == "12500"
        assert meter.get_attribute("max") == "50000"
        assert "37,500" in driver.find_element(By.ID, "account-quota").text
        driver.save_screenshot(str(tmp_path / "usage.png"))
        driver.set_window_size(390, 844)
        assert driver.execute_script(
            "return document.querySelector('.account-settings-dialog').scrollWidth <= document.querySelector('.account-settings-dialog').clientWidth"
        )
        driver.save_screenshot(str(tmp_path / "usage-mobile.png"))
        driver.set_window_size(1400, 1000)
        driver.find_element(By.ID, "account-close-settings").click()
        wait.until(
            lambda d: (
                "Alice private research"
                in d.find_element(By.ID, "session-select").get_attribute("textContent")
            )
        )
        assert not driver.find_element(By.ID, "connection-button").is_displayed()
        assert (
            driver.execute_script("return localStorage.getItem('graphmine.apiToken')")
            is None
        )
        assert "graphmine_session" not in driver.execute_script(
            "return document.cookie"
        )
        driver.refresh()
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-name").text == "alice"
        )

        driver.find_element(By.ID, "account-settings-button").click()
        driver.find_element(By.ID, "account-manage-users").click()
        wait.until(
            lambda d: "alice" in d.find_element(By.ID, "account-admin-users").text
        )
        driver.find_element(By.ID, "account-create-toggle").click()
        driver.find_element(By.ID, "account-new-username").send_keys("carol")
        driver.find_element(By.ID, "account-new-password").send_keys(PASSWORD)
        limit = driver.find_element(By.ID, "account-new-limit")
        limit.clear()
        limit.send_keys("25000")
        driver.find_element(By.ID, "account-create-user").click()
        wait.until(
            lambda d: "carol" in d.find_element(By.ID, "account-admin-users").text
        )
        assert (
            driver.find_element(By.ID, "account-new-password").get_attribute("value")
            == ""
        )
        carol = next(
            user
            for user in runtime.accounts.list_users()
            if user["username"] == "carol"
        )
        assert carol["quota"]["token_limit"] == 25000
        runtime.accounts.settle_tokens(
            runtime.accounts.reserve_tokens(carol["id"], 1400), 900
        )
        driver.find_element(By.ID, "account-refresh-users").click()
        wait.until(
            lambda d: (
                "900 of 25,000" in d.find_element(By.ID, "account-user-detail").text
            )
        )
        limit = driver.find_element(By.ID, "account-user-token-limit")
        limit.clear()
        limit.send_keys("30000")
        driver.find_element(By.ID, "account-save-limit").click()
        wait.until(
            lambda d: (
                "limit updated" in d.find_element(By.ID, "account-admin-message").text
            )
        )
        assert runtime.accounts.usage(carol["id"])["tokens_remaining"] == 29100
        driver.save_screenshot(str(tmp_path / "administrator.png"))
        driver.set_window_size(390, 844)
        assert driver.execute_script(
            "return document.querySelector('.account-settings-content').scrollWidth <= document.querySelector('.account-settings-content').clientWidth"
        )
        driver.save_screenshot(str(tmp_path / "administrator-mobile.png"))
        driver.set_window_size(1400, 1000)
        driver.find_element(By.ID, "account-reset-tokens").click()
        wait.until(
            lambda d: (
                "Token usage reset"
                in d.find_element(By.ID, "account-admin-message").text
            )
        )
        assert runtime.accounts.usage(carol["id"])["tokens_used"] == 0
        assert runtime.accounts.usage(carol["id"])["server_tokens_used"] == 13400
        driver.find_element(By.ID, "account-tab-profile").click()

        driver.find_element(By.ID, "account-sign-out").click()
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
        )
        sign_in("bob")
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-name").text == "bob"
        )
        driver.find_element(By.ID, "account-settings-button").click()
        assert not driver.find_element(By.ID, "account-manage-users").is_displayed()
        driver.find_element(By.ID, "account-close-settings").click()
        wait.until(
            lambda d: (
                "Verification needed" in d.find_element(By.ID, "connection-state").text
            )
        )
        assert "Alice private research" not in driver.find_element(
            By.ID, "session-select"
        ).get_attribute("textContent")
        driver.save_screenshot(str(tmp_path / "workspace.png"))
        driver.set_window_size(390, 844)
        assert driver.execute_script(
            "return document.documentElement.scrollWidth <= window.innerWidth"
        )

        driver.get(base + "/classic")
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-name").text == "bob"
        )
        assert not driver.find_element(By.ID, "settings-button").is_displayed()
        driver.find_element(By.ID, "account-settings-button").click()
        assert driver.find_element(
            By.CSS_SELECTOR, "#account-quota progress"
        ).is_displayed()
        driver.find_element(By.ID, "account-tab-profile").click()
        assert (
            driver.find_element(By.ID, "account-profile-username").get_attribute(
                "value"
            )
            == "bob"
        )
        driver.find_element(By.ID, "account-current-password").send_keys(PASSWORD)
        driver.find_element(By.ID, "account-change-password").send_keys(
            PASSWORD + "-new"
        )
        driver.find_element(By.ID, "account-confirm-password").send_keys(
            PASSWORD + "-new"
        )
        driver.find_element(By.ID, "account-save-password").click()
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
        )
        wait.until(
            lambda d: "Password changed" in d.find_element(By.ID, "account-error").text
        )
        sign_in("bob", PASSWORD + "-new")
        wait.until(
            lambda d: (
                not d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
                and d.find_element(By.CSS_SELECTOR, ".account-name").text == "bob"
            )
        )
        driver.find_element(By.ID, "account-settings-button").click()
        driver.find_element(By.ID, "account-tab-profile").click()
        driver.find_element(By.ID, "account-sign-out").click()
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
        )
    finally:
        if driver:
            driver.quit()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
