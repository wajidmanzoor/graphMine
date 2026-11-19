"""Capture an isolated saved-result replay; never points at production by default."""
import argparse
import io
import json
from pathlib import Path
import time
import zipfile

from playwright.sync_api import sync_playwright


def ready(page, workflow=None):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if page.evaluate("id => Boolean(window.GraphMineWorkspace?.state.resultView && !GraphMineWorkspace.state.resultViewPending && (!id || GraphMineWorkspace.state.resultView.workflow_id === id))", workflow):
            return
        page.wait_for_timeout(100)
    raise AssertionError(page.locator("body").inner_text()[:3000])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18743")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.cases.read_text())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True, reduced_motion="reduce")
        context.add_init_script("localStorage.setItem('graphmine.apiToken','results-acceptance-test')")
        page = context.new_page()
        errors, observations = [], {}
        page.on("pageerror", lambda error: errors.append(str(error)))
        for name, case in cases.items():
            page.goto(f"{args.url}/#workspace/{case['session']}/results/{case['workflow']}")
            ready(page, case["workflow"])
            page.wait_for_timeout(600)
            page.locator("#results-view").screenshot(path=str(args.output / (name + "-default.png")))
            if name == "bicliques":
                for mode in ("matrix", "small_multiples", "graph"):
                    page.select_option("#view-as", mode)
                    page.wait_for_timeout(500)
                    page.locator("#results-view").screenshot(path=str(args.output / ("bicliques-" + mode + ".png")))
                if page.locator("#result-download-menu").count():
                    page.locator("#result-download-menu > summary").click()
                else:
                    page.locator("#result-actions-panel").evaluate("element => element.open = true")
                page.locator("#results-view").screenshot(path=str(args.output / "download-controls.png"))
                response = page.request.get(f"{args.url}/api/workflows/{case['workflow']}/report?expected_revision=1", headers={"Authorization": "Bearer results-acceptance-test"})
                if response.ok:
                    archive = zipfile.ZipFile(io.BytesIO(response.body()))
                    for info in archive.infolist():
                        target = args.output / "report" / info.filename
                        if target.resolve().is_relative_to((args.output / "report").resolve()):
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(archive.read(info))
                else:
                    observations["report_error"] = response.status
            observations[name] = page.evaluate("() => ({zoom: GraphMineWorkspace.state.cy?.zoom(), nodes: GraphMineWorkspace.state.cy?.nodes().length, selected: GraphMineWorkspace.state.selected.size, scope: document.querySelector('#result-view-mode')?.value})")
            print(name, observations[name], flush=True)
        report = args.output / "report/report.html"
        if report.exists():
            page.goto(report.resolve().as_uri())
            page.screenshot(path=str(args.output / "report-first-screen.png"))
        (args.output / "observations.json").write_text(json.dumps({"views": observations, "browser_errors": errors}, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
