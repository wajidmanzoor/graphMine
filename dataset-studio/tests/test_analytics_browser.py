"""Real Studio HTTP/authentication and Firefox; all datasets are temporary."""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

import studio
from studio_auth import Auth
from test_analytics_integration import bundle, store  # noqa: F401


@pytest.fixture
def web(store, tmp_path):
    auth = Auth(tmp_path / "auth")
    auth.create_user("alice", "Studio-example-password-2026", role="admin")
    auth.create_user("bob", "Studio-example-password-2026")
    handler = type("TestHandler", (studio.Handler,), {"studio": store.studio, "auth": auth})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    value = SimpleNamespace(url=base, auth=auth, store=store, token=auth.login("alice", "Studio-example-password-2026"))
    yield value
    server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.fixture
def browser(web, tmp_path):
    options = Options(); options.binary_location = "/snap/firefox/current/usr/lib/firefox/firefox"
    options.add_argument("-headless")
    options.enable_bidi = True
    driver = webdriver.Firefox(options=options, service=Service(executable_path="/snap/firefox/current/usr/lib/firefox/geckodriver", log_output=str(tmp_path / "gecko.log")))
    driver.set_window_size(1440, 1000)
    driver.get(web.url + "/login.html")
    driver.add_cookie({"name": studio.COOKIE, "value": web.token, "path": "/"})
    driver.get(web.url)
    WebDriverWait(driver, 10).until(lambda d: d.find_element(By.ID, "account-name").text == "alice")
    yield driver
    driver.quit()


def test_http_revision_and_private_dataset_boundaries(web, bundle):
    with httpx.Client(base_url=web.url, cookies={studio.COOKIE: web.token}) as client:
        response = client.post("/api/import-analytics", json={"content": json.dumps(bundle)})
        assert response.status_code == 200, response.text
        ex = response.json()["example"]
        assert ex["created_by"] == "alice"
        assert client.post("/api/update", json={"id": ex["id"], "patch": {"review": "approved"}}).status_code == 409
        body = {"id": ex["id"], "patch": {"review": "approved"}, "expected_revision": ex["revision"]}
        response = client.post("/api/update", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["example"]["review_proof"]["by"] == "alice"
        assert client.post("/api/update", json=body).status_code == 409
        assert client.post("/api/export", json={"name": "missing-revisions"}).status_code == 409
    with httpx.Client(base_url=web.url) as client:
        assert client.post("/api/import-analytics", json={"content": json.dumps(bundle)}).status_code == 401
        client.cookies.set(studio.COOKIE, web.auth.login("bob", "Studio-example-password-2026"))
        assert client.get("/api/examples").status_code == 409
        assert client.post("/api/import-analytics", json={"content": json.dumps(bundle)}).status_code == 409
    assert len(web.store.ids()) == 1


@pytest.mark.parametrize("width", [1440, 320])
def test_import_review_export_and_exact_identifiers(browser, web, bundle, tmp_path, width):
    driver = browser
    # Firefox has a minimum outer window width; set the actual viewport through responsive sizing.
    driver.browsing_context.set_viewport(context=driver.current_window_handle, viewport={"width": width, "height": 1000})
    path = tmp_path / "reviewed.json"; path.write_text(json.dumps(bundle))
    driver.find_element(By.ID, "import-analytics-file").send_keys(str(path))
    wait = WebDriverWait(driver, 10)
    try:
        wait.until(lambda d: "Awaiting local review" in d.find_element(By.ID, "detail-body").text)
    except Exception:
        pytest.fail(driver.find_element(By.ID, "toast").get_attribute("textContent") + "\n" + driver.find_element(By.TAG_NAME, "body").text[-1200:])
    assert "source-reviewer" in driver.find_element(By.ID, "detail-body").text
    exact = driver.execute_script("const script=document.createElement('script'); script.textContent='window.__studioExact=String(S.examples[0].analytics.example.evidence.result.steps.core.result.count)'; document.head.append(script); script.remove(); return window.__studioExact")
    assert exact == "9007199254740993"
    button = driver.find_element(By.CSS_SELECTOR, '[data-review="approved"]')
    driver.execute_script("arguments[0].scrollIntoView({block:'center'})", button); button.click()
    wait.until(lambda d: "Reviewed revision" in d.find_element(By.ID, "detail-body").text)
    assert web.store.all_effective()[0]["review"] == "approved"
    driver.execute_script("openExport()")
    name = driver.find_element(By.ID, "export-name"); name.clear(); name.send_keys(f"browser-{width}")
    driver.find_element(By.ID, "export-submit").click()
    wait.until(lambda d: "Exported." in d.find_element(By.ID, "export-result").text)
    exported = web.store.home(web.store.current) / f"exports/browser-{width}"
    assert (exported / "sft/workflow/train.jsonl").is_file()
    assert json.loads((exported / "annotations.jsonl").read_text())["review_proof"]["by"] == "alice"
    driver.execute_script("document.querySelector('#export-dialog').close()")
    driver.execute_script("document.querySelector('#detail').scrollTop=0")
    driver.save_screenshot(f"/tmp/graphmine-studio-{width}.png")
    assert driver.execute_script("return document.documentElement.scrollWidth <= innerWidth+1")
    assert driver.execute_script("const pane=document.querySelector('#detail-body'); return pane.scrollWidth <= pane.clientWidth+1")
    assert driver.execute_script("return innerWidth") == width


def test_export_dialog_rejects_changes_after_it_was_opened(browser, web, bundle, tmp_path):
    path = tmp_path / "reviewed.json"; path.write_text(json.dumps(bundle))
    browser.find_element(By.ID, "import-analytics-file").send_keys(str(path))
    wait = WebDriverWait(browser, 10)
    wait.until(lambda d: "Awaiting local review" in d.find_element(By.ID, "detail-body").text)
    browser.execute_script("openExport()")
    ex = web.store.all_effective()[0]
    web.store.update(ex["id"], {"notes": "changed from a second tab"}, ex["revision"])
    browser.find_element(By.ID, "export-submit").click()
    wait.until(lambda d: "changed in another view" in d.find_element(By.ID, "toast").text)
    assert not (web.store.home(web.store.current) / "exports").exists()
