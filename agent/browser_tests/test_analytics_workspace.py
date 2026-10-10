"""Real browser → API → CPU library, with Node absent from the server PATH."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select, WebDriverWait

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def browser_evidence(request):
    package = (
        Path(os.environ.get("GRAPHMINE_BROWSER_APP_PATH", str(ROOT / "agent")))
        / "graphmine_agent"
    )

    def snapshot():
        files = list(package.rglob("*.py"))
        files += list((package / "static").glob("analytics*"))
        files += [
            package / "static/vendor/cytoscape.min.js",
            Path(__file__),
            ROOT / "catalog/python_analytics_coverage.json",
        ]
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)
        }

    before = snapshot()
    yield
    unchanged = before == snapshot()
    report = getattr(request.config.option, "xmlpath", None)
    if report:
        metadata = {
            "scope": "Firefox, actual API/library calculations, Node absent from server PATH; question-planning transport uses authored model responses, not model accuracy evidence",
            "source_files": before,
            "sources_unchanged_during_run": unchanged,
            "collected_test_count": len(request.session.items),
            "python": sys.version,
            "browser": "Firefox via geckodriver",
            "node_in_server_path": False,
        }
        Path(str(report) + ".metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    assert unchanged, "Browser/application sources changed during verification"


@pytest.fixture(scope="module")
def authored_model_transport():
    """A transport fixture tests browser routing wiring; it is not an LLM."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payload = json.loads(body["messages"][-1]["content"])
            seen.append(payload["stage"])
            if payload["stage"] == "family":
                result = {
                    "status": "selected",
                    "families": ["patterns"],
                    "message": "Count the requested shape.",
                }
            elif payload["stage"] == "operation":
                result = {
                    "status": "selected",
                    "operations": ["triangle-counting"],
                    "reroute_families": [],
                    "message": "Count triangles.",
                }
            else:
                result = {
                    "status": "ready",
                    "message": "The calculation is ready.",
                    "plan": {
                        "version": 1,
                        "device": payload["device_policy"],
                        "steps": [
                            {
                                "id": "triangles",
                                "operation": "triangle-counting",
                                "input": {"input": "main"},
                                "parameters": {},
                                "bindings": {},
                            }
                        ],
                    },
                }
            raw = json.dumps(
                {"choices": [{"message": {"content": json.dumps(result)}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture(scope="module")
def server(tmp_path_factory, authored_model_transport):
    root = tmp_path_factory.mktemp("analytics-browser-server")
    executables = root / "without-node"
    executables.mkdir()
    (executables / "python3").symlink_to(sys.executable)
    assert shutil.which("node", path=str(executables)) is None
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "PATH": str(executables),
        "GRAPHMINE_LLM_ENABLED": "true",
        "GRAPHMINE_LLM_BASE_URL": authored_model_transport[0],
        "GRAPHMINE_AGENT_DATA_ROOT": str(root / "data"),
        "GRAPHMINE_BINARY": str(root / "no-native-binary"),
        "GRAPHMINE_API_TOKEN": "analytics-browser-secret",
        "GRAPHMINE_GRAPH_GPU_UUID": "",
        "GRAPHMINE_LLM_GPU_UUID": "",
        "GRAPHMINE_ALLOWED_ORIGINS": base,
        "PYTHONPATH": str(root)
        + os.pathsep
        + os.environ.get("GRAPHMINE_BROWSER_APP_PATH", str(ROOT / "agent")),
        "GRAPHMINE_TEST_REPOSITORY_ROOT": str(ROOT),
    }
    (root / "browser_server_entry.py").write_text(
        "import os\nfrom pathlib import Path\nfrom graphmine_agent.api import create_app\nfrom graphmine_agent.config import Settings\napp=create_app(Settings.from_env(Path(os.environ['GRAPHMINE_TEST_REPOSITORY_ROOT'])))\n"
    )
    with (root / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "browser_server_entry:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if process.poll() is not None:
                    pytest.fail((root / "server.log").read_text())
                try:
                    with urlopen(base, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("Browser server did not start")
            yield base, root
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.fixture
def browser(server, tmp_path):
    firefox = Path("/snap/firefox/current/usr/lib/firefox/firefox")
    driver_path = Path("/snap/firefox/current/usr/lib/firefox/geckodriver")
    assert firefox.is_file() and driver_path.is_file(), (
        "The browser gate requires Firefox and geckodriver"
    )
    options = Options()
    options.add_argument("-headless")
    options.binary_location = str(firefox)
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", str(tmp_path))
    options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/json")
    driver = webdriver.Firefox(
        options=options, service=Service(executable_path=str(driver_path))
    )
    driver.set_window_size(1500, 1050)
    driver.set_script_timeout(30)
    driver.get(server[0])
    driver.execute_script(
        "localStorage.setItem('graphmine.apiToken','analytics-browser-secret')"
    )
    driver.refresh()
    WebDriverWait(driver, 40).until(
        lambda d: "Library ready" in d.find_element(By.ID, "connection-state").text
    )
    capture(driver, "workspace-overview.png")
    try:
        yield driver
    finally:
        driver.quit()


def typed_graph():
    ids = [0, "0", 9007199254740993, 9007199254740994, "isolated"]
    return {
        "graph": {
            "id": "typed-test",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {"id": value, "label": f"Node {i}"} for i, value in enumerate(ids)
        ],
        "edges": [
            {"id": i, "source": ids[a], "target": ids[b]}
            for i, (a, b) in enumerate([(0, 1), (1, 2), (2, 0), (2, 3)])
        ],
    }


def upload(browser, tmp_path, graph=None, kind="graph"):
    before = browser.execute_script(
        "return window.GraphMineWorkspace.state.files.length"
    )
    path = tmp_path / "typed-graph.json"
    path.write_text(json.dumps(graph or typed_graph()))
    if not browser.find_element(By.ID, "upload-kind").is_displayed():
        browser.find_element(By.CSS_SELECTOR, ".data-section details summary").click()
    Select(browser.find_element(By.ID, "upload-kind")).select_by_value(kind)
    browser.find_element(By.ID, "data-upload").send_keys(str(path))
    WebDriverWait(browser, 30).until(
        lambda d: (
            d.execute_script("return window.GraphMineWorkspace.state.files.length")
            == before + 1
            and "Your data is ready" in d.find_element(By.ID, "notice").text
        )
    )
    if kind == "graph":
        WebDriverWait(browser, 10).until(
            lambda d: d.execute_script("return !!window.GraphMineWorkspace.state.cy")
        )


def status(browser, expected):
    WebDriverWait(browser, 35).until(
        lambda d: (
            d.execute_script("return window.GraphMineWorkspace.state.record?.status")
            == expected
        )
    )


def done(browser):
    status(browser, "completed")
    WebDriverWait(browser, 15).until(
        lambda d: d.execute_script("return !!window.GraphMineWorkspace.state.port")
    )


def values(browser):
    return browser.execute_script(
        "return window.GraphMineWorkspace.state.port.value.map(r=>[typeof r.vertex,String(r.vertex),r.score])"
    )


def capture(browser, name):
    browser.execute_async_script(
        "const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(()=>done()));"
    )
    destination = Path(
        os.environ.get(
            "GRAPHMINE_BROWSER_ARTIFACTS", "/tmp/graphmine-analytics-browser"
        )
    )
    destination.mkdir(parents=True, exist_ok=True)
    browser.save_screenshot(str(destination / name))


def test_interactive_review_edit_linked_views_and_large_ids(browser, tmp_path):
    upload(browser, tmp_path)
    browser.find_element(By.CSS_SELECTOR, '[data-mode="interactive"]').click()
    browser.find_element(By.CSS_SELECTOR, '[data-family="importance"]').click()
    Select(browser.find_element(By.ID, "operation-select")).select_by_value(
        "degree-centrality"
    )
    browser.find_element(By.ID, "use-operation").click()
    status(browser, "awaiting_review")
    assert (
        browser.execute_script("return window.GraphMineWorkspace.state.result") is None
    )
    assert (
        browser.execute_script(
            "return Object.keys(window.GraphMineWorkspace.state.record.steps).length"
        )
        == 0
    )
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert values(browser) == [
        ["number", "0", 0.5],
        ["string", "0", 0.5],
        ["bigint", "9007199254740993", 0.75],
        ["bigint", "9007199254740994", 0.25],
        ["string", "isolated", 0],
    ]
    target = browser.find_element(
        By.CSS_SELECTOR, '#result-table tr[data-result-row="2"] button'
    )
    target.send_keys(Keys.ENTER)
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.cy.nodes('.chosen').map(n=>n.id())"
    ) == ["i:9007199254740993"]
    browser.find_element(By.CSS_SELECTOR, '#chart [data-result-row="1"]').click()
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.cy.nodes('.chosen').map(n=>n.id())"
    ) == ["s:0"]
    browser.execute_script("document.getElementById('evidence-panel').scrollIntoView()")
    capture(browser, "linked-results-desktop.png")
    details = browser.find_elements(By.CSS_SELECTOR, ".workflow-step .step-editor")[-1]
    details.find_element(By.TAG_NAME, "summary").click()
    Select(
        details.find_element(By.CSS_SELECTOR, '[data-parameter="normalized"]')
    ).select_by_value("false")
    details.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    WebDriverWait(browser, 15).until(
        lambda d: (
            d.execute_script("return window.GraphMineWorkspace.state.record.revision")
            == 2
        )
    )
    status(browser, "awaiting_review")
    assert (
        browser.execute_script("return window.GraphMineWorkspace.state.result") is None
    )
    assert "no new result" in browser.find_element(By.ID, "result-completeness").text
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert [r[2] for r in values(browser)] == [2, 2, 3, 1, 0]
    browser.find_element(By.ID, "download-result").click()
    WebDriverWait(browser, 10).until(
        lambda _: bool(list(tmp_path.glob("graphmine-*.json")))
    )
    exported = json.loads(next(tmp_path.glob("graphmine-*.json")).read_text())
    assert (
        exported["steps"]["analysis"]["result"]["ports"]["scores"]["value"][2]["vertex"]
        == 9007199254740993
    )
    # Use Firefox's supported narrow desktop viewport, checking its actual
    # width. This exercises the mobile breakpoint without claiming emulation
    # of a 390-pixel phone (desktop Firefox enforces a larger window minimum).
    browser.set_window_size(500, 844)
    WebDriverWait(browser, 5).until(
        lambda d: d.execute_script(
            "return innerWidth <= 760 && document.documentElement.scrollWidth <= innerWidth"
        )
    )
    browser.execute_script("document.getElementById('evidence-panel').scrollIntoView()")
    capture(browser, "linked-results-mobile.png")
    dimensions = browser.execute_script(
        """return {viewport: innerWidth, content: document.documentElement.scrollWidth,
        outside: [...document.querySelectorAll('body *')].filter(e =>
        e.getBoundingClientRect().right > innerWidth + 1).slice(0,15).map(e =>
        [e.tagName, e.id, e.className, e.getBoundingClientRect().right])};"""
    )
    assert dimensions["viewport"] <= 760, dimensions
    assert dimensions["content"] <= dimensions["viewport"], dimensions
    assert browser.execute_script("""
        const cy=window.GraphMineWorkspace.state.cy, box=cy.elements().renderedBoundingBox();
        return cy.nodes().length===5 && box.x1>=0 && box.y1>=0 && box.x2<=cy.width() && box.y2<=cy.height();
    """)


def test_expert_dependent_plan_and_incomplete_output(browser, tmp_path):
    upload(browser, tmp_path)
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "core",
                "operation": "k-core",
                "input": {"input": "main"},
                "parameters": {"requested_k": 2},
            },
            {
                "id": "sub",
                "operation": "induced-subgraph",
                "input": {"input": "main"},
                "bindings": {"vertices_or_seeds": {"step": "core", "port": "vertices"}},
            },
            {
                "id": "rank",
                "operation": "pagerank",
                "input": {"step": "sub", "port": "graph"},
            },
        ],
    }
    editor = browser.find_element(By.ID, "plan-editor")
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    assert len(browser.find_elements(By.CSS_SELECTOR, ".workflow-step")) == 3
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert [r[2] for r in values(browser)] == pytest.approx([1 / 3] * 3)
    assert "3 of 3 vertices" in browser.find_element(By.ID, "preview-scope").text
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.cy.nodes().map(n=>n.id())"
    ) == ["i:0", "s:0", "i:9007199254740993"]
    browser.execute_script("document.getElementById('workflow-panel').scrollIntoView()")
    capture(browser, "dependent-workflow.png")
    plan["steps"] = [
        {
            "id": "pairs",
            "operation": "k-cliques",
            "input": {"input": "main"},
            "parameters": {"k": 2, "mode": "enumerate", "result_limit": 1},
        }
    ]
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    WebDriverWait(browser, 15).until(
        lambda d: (
            d.execute_script("return window.GraphMineWorkspace.state.record.revision")
            == 2
        )
    )
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert "incomplete" in browser.find_element(By.ID, "result-completeness").text
    assert (
        browser.execute_script("return window.GraphMineWorkspace.state.result.complete")
        is False
    )
    assert "1 of 1 retained rows" in browser.find_element(By.ID, "table-count").text


def test_normal_mode_paging_outside_preview_and_fixed_renderers(browser, tmp_path):
    Select(browser.find_element(By.ID, "graph-layout")).select_by_value("circle")
    graph = {
        "graph": {
            "id": "large-preview",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": i} for i in range(502)],
        "edges": [{"id": i, "source": 501, "target": i} for i in range(501)],
    }
    upload(browser, tmp_path, graph)
    browser.find_element(By.CSS_SELECTOR, '[data-family="importance"]').click()
    Select(browser.find_element(By.ID, "operation-select")).select_by_value(
        "degree-centrality"
    )
    browser.find_element(By.ID, "use-operation").click()
    done(browser)
    assert (
        browser.execute_script("return window.GraphMineWorkspace.state.record.mode")
        == "normal"
    )
    assert "500 of 502 vertices" in browser.find_element(By.ID, "preview-scope").text
    browser.find_element(By.CSS_SELECTOR, '#chart [data-result-row="501"]').click()
    assert (
        "outside this graph preview"
        in browser.find_element(By.ID, "selection-detail").text
    )
    browser.find_element(By.ID, "table-next").click()
    assert browser.find_element(By.ID, "table-page").text == "2 / 17"
    browser.find_element(By.ID, "table-search").send_keys("501")
    assert browser.find_element(By.ID, "table-page").text == "1 / 1"
    assert browser.execute_script("return typeof window.vega") == "undefined"
    assert browser.execute_script(
        "return Array.from(document.scripts).map(s=>s.src).every(s=>!s.includes('vega'))"
    )
    browser.find_element(By.ID, "new-session").click()
    WebDriverWait(browser, 10).until(
        lambda d: d.execute_script(
            "return window.GraphMineWorkspace.state.session===null"
        )
    )
    assert "Upload a graph" in browser.find_element(By.ID, "result-completeness").text
    assert not browser.find_element(By.ID, "download-result").is_enabled()
    assert not browser.find_elements(
        By.CSS_SELECTOR, "#result-table tr[data-result-row]"
    )


def test_pattern_input_can_bind_another_uploaded_graph(browser, tmp_path):
    upload(browser, tmp_path)
    data_id = browser.execute_script("return window.GraphMineWorkspace.state.active")
    query = {
        "graph": {
            "id": "edge-pattern",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": "u"}, {"id": "v"}],
        "edges": [{"id": "uv", "source": "u", "target": "v"}],
    }
    upload(browser, tmp_path, query)
    Select(browser.find_element(By.ID, "active-input")).select_by_value(data_id)
    browser.find_element(By.CSS_SELECTOR, '[data-family="patterns"]').click()
    Select(browser.find_element(By.ID, "operation-select")).select_by_value(
        "subgraph-isomorphism"
    )
    Select(
        browser.find_element(By.CSS_SELECTOR, '[data-binding-parameter="query_graph"]')
    ).select_by_value("data_2")
    browser.find_element(By.ID, "use-operation").click()
    done(browser)
    assert (
        browser.execute_script(
            "return window.GraphMineWorkspace.state.record.validation.plan.steps[0].bindings.query_graph.input"
        )
        == "data_2"
    )
    assert (
        browser.execute_script(
            "return window.GraphMineWorkspace.state.result.steps.analysis.result.ports.matches.value.length"
        )
        == 8
    )


def test_collection_patterns_have_independent_graph_views_and_can_feed_workflow(
    browser, tmp_path
):
    source = typed_graph()
    source["vertices"] = source["vertices"][:3]
    source["edges"] = source["edges"][:3]
    other = json.loads(json.dumps(source))
    other["graph"]["id"] = "path"
    other["edges"].pop()
    upload(
        browser,
        tmp_path,
        {"dataset_id": "observations", "graphs": [source, other]},
        kind="graph_collection",
    )
    assert "Each collection member" in browser.find_element(By.ID, "preview-scope").text
    assert browser.execute_script("return window.GraphMineWorkspace.state.cy") is None
    browser.find_element(By.CSS_SELECTOR, '[data-family="patterns"]').click()
    Select(browser.find_element(By.ID, "operation-select")).select_by_value(
        "frequent-subgraphs"
    )
    browser.find_element(By.ID, "parameter-minimum_support_fraction").send_keys("1")
    browser.find_element(By.ID, "parameter-maximum_edges").send_keys("2")
    browser.find_element(By.ID, "use-operation").click()
    done(browser)
    rows = browser.execute_script(
        "return window.GraphMineWorkspace.state.rows.map(r=>[r.vertex_count,r.edge_count,r.support_graph_count,r.support_fraction])"
    )
    assert sorted(rows) == [[2, 1, 2, 1], [3, 1, 2, 1], [3, 2, 2, 1]]
    assert (
        "vertex IDs are local to this pattern"
        in browser.find_element(By.ID, "preview-scope").text
    )
    for index in range(3):
        browser.find_element(
            By.CSS_SELECTOR, f'#result-table [data-result-row="{index}"] button'
        ).click()
        observed = browser.execute_script(
            "const s=window.GraphMineWorkspace.state;return [s.graph.vertices.length,s.graph.edges.length,s.cy.nodes().map(n=>n.id()),s.patternId===s.rows[arguments[0]].pattern_id]",
            index,
        )
        assert observed[:2] == rows[index][:2]
        assert observed[2] == [f"i:{i}" for i in range(rows[index][0])]
        assert observed[3]
        selected = browser.find_elements(
            By.CSS_SELECTOR, '#result-table tr[aria-selected="true"]'
        )
        assert len(selected) == 1 and selected[0].get_attribute(
            "data-result-row"
        ) == str(index)
    capture(browser, "frequent-pattern-graph.png")
    # A fixed selector supplies a graph to another registered calculation.
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    plan = browser.execute_script(
        "return window.GraphMineWorkspace.state.record.validation.plan"
    )
    selected_index = next(i for i, row in enumerate(rows) if row[:2] == [3, 2])
    plan["steps"].append(
        {
            "id": "degree",
            "operation": "degree-centrality",
            "input": {
                "step": plan["steps"][0]["id"],
                "port": "patterns",
                "select": {"kind": "pattern_graph", "index": selected_index},
            },
        }
    )
    editor = browser.find_element(By.ID, "plan-editor")
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert sorted(row[2] for row in values(browser)) == [0.5, 0.5, 1]
    assert "3 of 3 vertices" in browser.find_element(By.ID, "preview-scope").text


def test_mni_pattern_images_and_count_only_output(browser, tmp_path):
    source = typed_graph()
    source["vertices"] = source["vertices"][:3]
    source["edges"] = source["edges"][:3]
    for vertex in source["vertices"]:
        vertex["label"] = "same"
    upload(browser, tmp_path, source)
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "mni",
                "operation": "single-graph-frequent-subgraphs",
                "input": {"input": "main"},
                "parameters": {
                    "minimum_image_support": 3,
                    "max_pattern_edges": 3,
                    "match_mode": "induced",
                    "output_mode": "patterns",
                    "include_images": True,
                },
            },
        ],
    }
    editor = browser.find_element(By.ID, "plan-editor")
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.rows.map(r=>r.minimum_image_support)"
    ) == [3, 3, 3]
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.rows[0].images[0].host_vertices.map(v=>[typeof v,String(v)])"
    ) == [["number", "0"], ["string", "0"], ["bigint", "9007199254740993"]]
    plan["steps"][0]["parameters"].update(output_mode="count", include_images=False)
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert [
        option.get_attribute("value")
        for option in browser.find_elements(By.CSS_SELECTOR, "#result-port option")
    ] == ["count"]
    assert browser.find_element(By.CSS_SELECTOR, "#metrics strong").text == "3"
    assert "Canonical pattern" not in browser.find_element(By.ID, "preview-scope").text


def test_graph_comparison_exact_cost_and_edit_script_views(browser, tmp_path):
    a = typed_graph()
    a["vertices"] = a["vertices"][:3]
    a["edges"] = a["edges"][:2]
    for row in a["vertices"]:
        row["label"] = "A"
    for row in a["edges"]:
        row["type"] = "x"
    b = json.loads(json.dumps(a))
    b["graph"]["id"] = "target"
    b["vertices"].append({"id": 9007199254740994, "label": "A"})
    b["edges"].append(
        {"id": "new", "source": 9007199254740993, "target": 9007199254740994}
    )
    for edge, category in zip(b["edges"], ["y", "x", "y"], strict=True):
        edge["type"] = category
    upload(browser, tmp_path, a)
    upload(browser, tmp_path, b)
    first_input = browser.execute_script(
        "return window.GraphMineWorkspace.state.files[0].id"
    )
    Select(browser.find_element(By.ID, "active-input")).select_by_value(first_input)
    WebDriverWait(browser, 10).until(
        lambda d: (
            d.execute_script(
                "return window.GraphMineWorkspace.state.graph?.vertices.length"
            )
            == 3
        )
    )
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "compare",
                "operation": "graph-edit-distance",
                "input": {"input": "main"},
                "bindings": {"other_graph": {"input": "data_2"}},
                "parameters": {
                    "edit_costs": {"edge_substitution": 1e-200, "edge_insertion": 0}
                },
            },
        ],
    }
    editor = browser.find_element(By.ID, "plan-editor")
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert browser.find_element(By.CSS_SELECTOR, "#metrics strong").text == "≈ 1"
    assert "Display rounded" in browser.find_element(By.ID, "metrics").text
    assert browser.execute_script(
        "const v=window.GraphMineWorkspace.state.port.value;return [typeof v.numerator,String(v.numerator),String(v.denominator)]"
    ) == ["bigint", str(10**200 + 1), str(10**200)]
    browser.execute_script(
        "document.getElementById('result-controls').scrollIntoView()"
    )
    capture(browser, "graph-edit-cost.png")
    Select(browser.find_element(By.ID, "result-port")).select_by_value("edits")
    WebDriverWait(browser, 10).until(
        lambda d: (
            d.execute_script("return window.GraphMineWorkspace.state.port.type")
            == "table"
        )
    )
    assert "vertex_insertion" in browser.find_element(By.ID, "result-table").text
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.rows.some(r=>r.vertex_record && typeof r.vertex_record.id==='bigint')"
    )
    browser.execute_script(
        "document.getElementById('result-controls').scrollIntoView()"
    )
    capture(browser, "graph-edit-script.png")
    plan["steps"] = [
        {
            "id": "common",
            "operation": "maximum-common-subgraph",
            "input": {"input": "main"},
            "bindings": {"other_graph": {"input": "data_2"}},
        },
        {
            "id": "degree",
            "operation": "degree-centrality",
            "input": {"step": "common", "port": "graph"},
        },
    ]
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert "2 of 2 vertices" in browser.find_element(By.ID, "preview-scope").text
    assert len(values(browser)) == 2
    assert browser.execute_script(
        "return window.GraphMineWorkspace.state.cy.nodes().map(n=>n.id()).every(k=>['i:0','s:0','i:9007199254740993'].includes(k))"
    )


def test_lossless_json_rejects_invalid_values_and_preserves_export(browser):
    result = browser.execute_script("""
      const w=window.AnalyticsWire;
      const input='{"v":[0,"0",9007199254740993,9007199254740994],"__proto__":{"p":true}}';
      const value=w.parse(input);
      return [w.stringify(value),value.v.map(w.idKey),Object.getPrototypeOf(value)===null,({}).p===undefined];
    """)
    assert json.loads(result[0])["v"] == [0, "0", 9007199254740993, 9007199254740994]
    assert result[1] == ["i:0", "s:0", "i:9007199254740993", "i:9007199254740994"]
    assert result[2:] == [True, True]
    rejected = browser.execute_script(
        """return ['[1,]','{"x":1,}','01','1e999','undefined','[NaN]','\\u00a0{}'].every(x=>{try{window.AnalyticsWire.parse(x);return false}catch{return true}})"""
    )
    assert rejected


def test_force_layout_displays_computed_coordinates_with_explicit_projection(
    browser, tmp_path
):
    upload(browser, tmp_path)
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    coordinates = [[0, 0, 0], [1, 0, 1], [0, 2, 3], [-1, 0, 1], [3, 3, 0]]
    ids = [v["id"] for v in typed_graph()["vertices"]]
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "drawing",
                "operation": "force-directed-layout",
                "input": {"input": "main"},
                "parameters": {
                    "iterations": 0,
                    "dimensions": 3,
                    "initial_positions": [
                        {"vertex": v, "value": p}
                        for v, p in zip(ids, coordinates, strict=True)
                    ],
                },
            }
        ],
    }
    editor = browser.find_element(By.ID, "plan-editor")
    editor.clear()
    editor.send_keys(json.dumps(plan))
    browser.find_element(By.ID, "save-editor").click()
    status(browser, "ready")
    browser.find_element(By.ID, "approve-plan").click()
    done(browser)
    assert (
        Select(
            browser.find_element(By.ID, "graph-layout")
        ).first_selected_option.get_attribute("value")
        == "computed"
    )
    assert "XY projection of 3D" in browser.find_element(By.ID, "preview-scope").text
    stored = browser.execute_script(
        "return window.GraphMineWorkspace.state.port.value.map(r=>r.coordinates)"
    )
    assert stored == coordinates
    displayed = browser.execute_script(
        "return window.GraphMineWorkspace.state.cy.nodes().map(n=>[n.position('x'),n.position('y')])"
    )
    for actual, expected in zip(displayed, coordinates, strict=True):
        assert actual == pytest.approx([expected[0] / 3 * 200, expected[1] / 3 * 200])
    Select(browser.find_element(By.ID, "graph-layout")).select_by_value("circle")
    assert "for display only" in browser.find_element(By.ID, "preview-scope").text


def test_question_uses_family_then_operation_then_real_calculation(
    browser, tmp_path, authored_model_transport
):
    upload(browser, tmp_path)
    Select(browser.find_element(By.ID, "device")).select_by_value("cpu")
    start = len(authored_model_transport[1])
    browser.find_element(By.ID, "question").send_keys(
        "How many three-way connections are in this data?"
    )
    browser.find_element(By.ID, "plan-question").click()
    done(browser)
    assert authored_model_transport[1][start:] == ["family", "operation", "plan"]
    assert (
        "Family: Patterns & events" in browser.find_element(By.ID, "routing-trace").text
    )
    assert (
        browser.execute_script("return window.GraphMineWorkspace.state.port.value") == 1
    )
    assert (
        browser.execute_script(
            "return window.GraphMineWorkspace.state.result.steps.triangles.result.backend.device"
        )
        == "cpu"
    )
