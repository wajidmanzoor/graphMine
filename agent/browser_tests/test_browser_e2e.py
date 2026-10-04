from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

selenium = pytest.importorskip("selenium")
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import (
    Select,
    WebDriverWait,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _fake_binary(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            from pathlib import Path
            import sys

            if len(sys.argv) > 1 and sys.argv[1] == "list":
                print(json.dumps({
                    "operation_count": 13,
                    "library_version": "1.0.0",
                    "validated_backend_count": 26,
                    "compiled_backend_count": 1,
                    "operations": [{
                        "id": "maximal-cliques",
                        "backends": [{"id": "rdmce", "compiled": True, "validated": True}],
                    }],
                }))
                raise SystemExit(0)
            if len(sys.argv) > 2 and sys.argv[1] == "run":
                output = Path(sys.argv[sys.argv.index("--output") + 1])
                payload = {
                    "ok": True,
                    "provenance": {"backend": "rdmce", "browser_test": True},
                    "warnings": [],
                    "statistics": {"end_to_end_ms": 1.0, "backend_ms": 0.5},
                    "output": {
                        "cliques": [[0, 1, 2]],
                        "returned_count": 1,
                        "complete": True,
                    },
                }
                graph = json.loads(Path(sys.argv[sys.argv.index("--graph") + 1]).read_text())
                if len(graph["vertices"]) > 500:
                    payload["output"]["cliques"] = [[500, 501, 502, 503], [600, 601, 602]]
                    payload["output"]["returned_count"] = 2
                output.write_text(json.dumps(payload), encoding="utf-8")
                raise SystemExit(0)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _wait_for_server(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"agent stopped early\nstdout={stdout}\nstderr={stderr}")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("timed out waiting for browser-test server")


@pytest.mark.parametrize("rich_graph", [False, True])
def test_complete_browser_upload_chat_result_and_followup(
    tmp_path: Path, rich_graph: bool
) -> None:
    snap_firefox = Path("/snap/firefox/current/usr/lib/firefox/firefox")
    snap_geckodriver = Path("/snap/firefox/current/usr/lib/firefox/geckodriver")
    firefox = str(snap_firefox) if snap_firefox.is_file() else shutil.which("firefox")
    geckodriver = (
        str(snap_geckodriver)
        if snap_geckodriver.is_file()
        else shutil.which("geckodriver")
    )
    if not firefox or not geckodriver:
        pytest.skip("Firefox and geckodriver are required for the browser gate")

    binary = tmp_path / "graphmine"
    _fake_binary(binary)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    environment = dict(os.environ)
    environment.update(
        {
            "GRAPHMINE_LLM_ENABLED": "false",
            "GRAPHMINE_AGENT_DATA_ROOT": str(tmp_path / "data"),
            "GRAPHMINE_BINARY": str(binary),
            "GRAPHMINE_API_TOKEN": "browser-test-secret",
            "GRAPHMINE_ALLOWED_ORIGINS": base,
            "GRAPHMINE_API_HOST": "127.0.0.1",
            "GRAPHMINE_API_PORT": str(port),
            "GRAPHMINE_BACKEND_POLICY": str(tmp_path / "missing-policy.json"),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "graphmine_agent",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    driver: webdriver.Firefox | None = None
    try:
        _wait_for_server(base, process)
        options = Options()
        options.add_argument("-headless")
        options.binary_location = firefox
        driver = webdriver.Firefox(
            options=options, service=Service(executable_path=geckodriver)
        )
        driver.set_window_size(1440, 1000)
        wait = WebDriverWait(driver, 20)
        driver.get(base)
        driver.execute_script(
            "localStorage.setItem('graphmine.apiToken', 'browser-test-secret');"
        )
        driver.refresh()

        wait.until(
            conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, ".domain-card[data-domain='general']")
            )
        ).click()
        wait.until(conditions.visibility_of_element_located((By.ID, "workspace-view")))

        file_input = driver.find_element(By.ID, "file-input")
        input_path = REPOSITORY_ROOT / "library" / "examples" / "data" / "triangle.json"
        if rich_graph:
            input_path = tmp_path / "rich-teams.json"
            members = [[500, 501, 502, 503], [600, 601, 602]]
            pairs = [(a, b) for group in members for a in group for b in group if a < b]
            pairs.append((503, 600))  # A bridge must not stretch compound labels away.
            input_path.write_text(
                json.dumps(
                    {
                        "graph": {
                            "id": "rich",
                            "directed": False,
                            "allows_self_loops": False,
                            "allows_parallel_edges": False,
                        },
                        "vertices": [
                            {
                                "id": i,
                                "label": f"Employee {i}",
                                "type": "employee",
                                "attributes": {
                                    "department": "Engineering"
                                    if i < 600
                                    else "Support",
                                    "tenure": i % 10 + 1,
                                },
                            }
                            for i in range(650)
                        ],
                        "edges": [
                            {"id": i, "source": a, "target": b}
                            for i, (a, b) in enumerate(pairs)
                        ],
                    }
                ),
                encoding="utf-8",
            )
        file_input.send_keys(str(input_path))
        wait.until(
            conditions.text_to_be_present_in_element(
                (By.ID, "file-list"), input_path.name
            )
        )

        driver.find_element(By.ID, "chat-input").send_keys(
            "Enumerate every maximal clique in this graph."
        )
        driver.find_element(By.ID, "send-button").click()
        wait.until(conditions.presence_of_element_located((By.CLASS_NAME, "plan-card")))
        wait.until(
            conditions.text_to_be_present_in_element((By.ID, "job-state"), "Complete")
        )
        assert not driver.find_element(By.ID, "results-view").is_displayed()
        assert driver.find_element(By.ID, "activity-list").text
        wait.until(
            conditions.element_to_be_clickable((By.CLASS_NAME, "result-link"))
        ).click()
        wait.until(conditions.visibility_of_element_located((By.ID, "result-content")))
        assert not driver.find_element(By.ID, "workspace-view").is_displayed()
        wait.until(conditions.presence_of_element_located((By.CLASS_NAME, "viz-card")))

        driver.find_element(By.ID, "raw-toggle").click()
        wait.until(
            conditions.text_to_be_present_in_element((By.ID, "raw-result"), '"cliques"')
        )

        message_count = len(driver.find_elements(By.CSS_SELECTOR, "#messages .message"))
        driver.find_element(By.ID, "back-to-chat").click()
        driver.find_element(By.ID, "chat-input").send_keys(
            "Explain what this result means without running another computation."
        )
        driver.find_element(By.ID, "send-button").click()
        wait.until(
            lambda browser: (
                len(browser.find_elements(By.CSS_SELECTOR, "#messages .message"))
                >= message_count + 2
            )
        )
        driver.find_element(By.ID, "results-page-link").click()
        wait.until(conditions.visibility_of_element_located((By.ID, "result-content")))
        assert "Server ready" in driver.find_element(By.ID, "server-status").text
        assert '"backend": "rdmce"' in driver.find_element(By.ID, "raw-result").text
        wait.until(
            lambda browser: browser.execute_script(
                "return !!document.querySelector('.answer-network')?.graphmineNetwork"
            )
        )
        expected_nodes = 7 if rich_graph else 3
        assert (
            len(driver.find_elements(By.CSS_SELECTOR, ".network-accessible li"))
            == expected_nodes
        )
        assert driver.execute_script(
            "return document.querySelector('.answer-network').graphmineNetwork.nodes().every(n => Number.isFinite(n.position().x) && Number.isFinite(n.position().y))"
        )
        if rich_graph:
            assert (
                Select(
                    driver.find_element(By.CLASS_NAME, "color-selector")
                ).first_selected_option.get_attribute("value")
                == "attributes.department"
            )
            table = driver.find_element(
                By.CSS_SELECTOR, '.viz-card[data-view-id="groups"] table'
            )
            assert "Department" in table.text and "Employee 500" in table.text
            assert '"attributes"' not in table.text
            assert driver.execute_script(
                "const cy = document.querySelector('.answer-network').graphmineNetwork; return cy.nodes().filter(n => !!n.data('original')).every(n => n.numericStyle('font-size') * cy.zoom() >= 10)"
            )
            assert "Employee 602" in driver.find_element(
                By.CLASS_NAME, "network-accessible"
            ).get_attribute("textContent")
            Select(
                driver.find_element(By.CLASS_NAME, "group-selector")
            ).select_by_value("1")
            assert (
                len(driver.find_elements(By.CSS_SELECTOR, ".network-accessible li"))
                == 3
            )
            assert "Employee 500" not in driver.find_element(
                By.CLASS_NAME, "network-accessible"
            ).get_attribute("textContent")
            Select(
                driver.find_element(By.CLASS_NAME, "group-selector")
            ).select_by_value("all")
            Select(
                driver.find_element(By.CLASS_NAME, "color-selector")
            ).select_by_value("attributes.department")
            assert (
                "Engineering"
                in driver.find_element(By.CLASS_NAME, "network-legend").text
            )
            assert (
                "Support" in driver.find_element(By.CLASS_NAME, "network-legend").text
            )
            driver.execute_script(
                "document.querySelector('.answer-network').graphmineNetwork.nodes().filter(n => !!n.data('original'))[0].emit('tap')"
            )
            assert (
                "department"
                in driver.find_element(By.CLASS_NAME, "entity-details").text
            )

        followup = driver.find_element(By.CSS_SELECTOR, ".followup-actions button")
        driver.execute_script(
            "window.scrollCalls = []; Element.prototype.scrollIntoView = function() { window.scrollCalls.push(this.dataset.viewId); }; "
        )
        driver.execute_script("arguments[0].click()", followup)
        assert driver.execute_script("return window.scrollCalls") == ["members"]

        # Feedback targets this result; commands persist without producing a job.
        driver.find_element(By.ID, "result-feedback").click()
        driver.find_element(By.ID, "feedback-note").send_keys(
            "Please explain these groups in simpler language."
        )
        driver.find_element(By.ID, "feedback-expected").send_keys(
            "Use the uploaded names in the explanation."
        )
        driver.find_element(By.ID, "save-feedback").click()
        wait.until(
            conditions.invisibility_of_element_located((By.ID, "feedback-dialog"))
        )
        driver.find_element(By.ID, "back-to-chat").click()
        driver.find_element(By.ID, "chat-input").send_keys(
            r"\feedback Useful groups | Explain why they were selected"
        )
        driver.find_element(By.ID, "send-button").click()
        wait.until(
            conditions.text_to_be_present_in_element(
                (By.ID, "feedback-count"), "2 saved annotations"
            )
        )
        session_hash = driver.current_url.split("#", 1)[1]
        driver.refresh()
        wait.until(
            conditions.text_to_be_present_in_element(
                (By.ID, "feedback-count"), "2 saved annotations"
            )
        )
        assert input_path.name in driver.find_element(By.ID, "file-list").text
        assert "Useful groups" in driver.find_element(By.ID, "messages").text
        assert driver.find_element(By.ID, "activity-list").text
        if os.environ.get("GRAPHMINE_BROWSER_ARTIFACT_DIR"):
            artifacts = Path(os.environ["GRAPHMINE_BROWSER_ARTIFACT_DIR"])
            artifacts.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(
                str(artifacts / ("rich-chat.png" if rich_graph else "simple-chat.png"))
            )
            driver.set_window_size(390, 844)
            driver.save_screenshot(
                str(
                    artifacts
                    / (
                        "rich-mobile-chat.png"
                        if rich_graph
                        else "simple-mobile-chat.png"
                    )
                )
            )
            assert driver.execute_script(
                "return document.documentElement.scrollWidth <= window.innerWidth + 1"
            )
            driver.set_window_size(1440, 1000)

        # A new session must not inherit files, chat, activity, or result links.
        driver.find_element(By.ID, "new-session").click()
        wait.until(
            conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, ".domain-card[data-domain='general']")
            )
        ).click()
        wait.until(lambda _: driver.current_url.split("#", 1)[1] != session_hash)
        wait.until(lambda _: not driver.find_element(By.ID, "file-list").text)
        assert "Useful groups" not in driver.find_element(By.ID, "messages").text
        assert not driver.find_elements(By.CLASS_NAME, "result-link")
        driver.get(base + "#" + session_hash)
        wait.until(
            conditions.text_to_be_present_in_element(
                (By.ID, "feedback-count"), "2 saved annotations"
            )
        )

        # Verify the same visualization is actually usable without a server/CDN.
        def get(path):
            with urlopen(
                Request(
                    base + path, headers={"Authorization": "Bearer browser-test-secret"}
                ),
                timeout=5,
            ) as response:
                return response.read()

        session_id = session_hash.split("/")[1]
        result_id = json.loads(get(f"/api/jobs?session_id={session_id}"))[-1][
            "result_id"
        ]
        annotations = json.loads(get(f"/api/sessions/{session_id}/feedback"))
        assert len(annotations) == 2 and annotations[0]["result_id"] == result_id
        assert len(json.loads(get(f"/api/jobs?session_id={session_id}"))) == 1
        report = tmp_path / "answer.html"
        report.write_bytes(get(f"/api/results/{result_id}/report"))
        driver.get(report.as_uri())
        wait.until(
            lambda browser: browser.execute_script(
                "return !!document.querySelector('.answer-network')?.graphmineNetwork"
            )
        )
        assert (
            len(driver.find_elements(By.CSS_SELECTOR, ".network-accessible li"))
            == expected_nodes
        )
        assert "Offline report" in driver.find_element(By.ID, "server-status").text
        assert not driver.execute_script(
            "return performance.getEntriesByType('resource').some(item => item.name.startsWith('http'))"
        )
        if os.environ.get("GRAPHMINE_BROWSER_ARTIFACT_DIR"):
            artifacts = Path(os.environ["GRAPHMINE_BROWSER_ARTIFACT_DIR"])
            artifacts.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(
                str(
                    artifacts
                    / ("rich-answer.png" if rich_graph else "simple-answer.png")
                )
            )
    finally:
        if driver is not None:
            driver.quit()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
