"""Database work stays recoverable when its workspace or browser is closed."""

import copy
import json
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By

from test_workspace_loading import loading_browser, loading_server, wait_for  # noqa: F401


@pytest.fixture
def database_jobs(loading_server):
    state = SimpleNamespace(jobs={}, submissions=[], result_reads=0, failures=[], delayed=None, poll_count=0, history_filters=[])
    def handler(request, method):
        parsed = urlsplit(request.path); path = parsed.path
        def reply(value, status=200):
            request.respond(value, status); return True
        if method == "GET" and path == "/api/database-sources":
            return reply([{"id": "jobs-db", "name": "Database jobs fixture", "entities": [{"label": "Account"}], "relationships": []}])
        if path == "/api/database-sources/jobs-db/status":
            return reply({"connected": True, "sql": {"connected": True}, "neo4j": {"connected": True}})
        if method == "GET" and path == "/api/database-sources/jobs-db/datasets":
            return reply([{"id": "default", "name": "Accounts", "status": "ready", "schemas": [], "tables": [], "default_query": "MATCH (n) RETURN n LIMIT 10"}])
        if method == "GET" and path == "/api/database-jobs":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            state.history_filters.append(kind)
            return reply({"items": [job for job in reversed(list(state.jobs.values())) if not kind or job["kind"] == kind], "has_more": False})
        if method == "POST" and (path.endswith(("/queries", "/sync", "/retry"))):
            raw = request.rfile.read(int(request.headers.get("Content-Length", 0)))
            query = json.loads(raw) if raw else None
            if path.endswith("/retry"):
                previous = state.jobs[path.split("/")[3]]; kind, query = previous["kind"], previous["query"]
            else:
                assert request.headers.get("Prefer") == "respond-async"
                kind = "sync" if path.endswith("/sync") else "query"
            state.submissions.append({"kind": kind, "query": query, "key": request.headers.get("Idempotency-Key")})
            identifier = f"job-{len(state.submissions)}"
            job = {"id": identifier, "kind": kind, "source_id": "jobs-db", "status": "running", "cancellable": True,
                   "query": query, "progress": {"stage": "reading", "completed": 12, "total": None},
                   "created_at": "2026-10-21T12:00:00Z", "error": None}
            state.jobs[identifier] = job
            return reply({"job": job}, 202)
        if path.startswith("/api/database-jobs/"):
            identifier = path.split("/")[3]; job = state.jobs[identifier]
            if method == "DELETE":
                if not job["cancellable"]:
                    return reply({"error": {"code": "database_committing", "message": "This job is committing its result and can no longer be cancelled."}}, 409)
                job.update(status="cancelling", cancellable=False)
                return reply(job)
            if path.endswith("/result"):
                state.result_reads += 1
                if job["kind"] == "sync":
                    return reply(job.get("synchronization") or {"nodes": 3, "relationships": 2})
                return reply({"dataset": {"id": f"snapshot-{identifier}", "temporary": True}, "row_count": 1, "rows": [],
                              "vertex_count": 1, "edge_count": 0, "elapsed_ms": 100,
                              "graph": {"graph": {"directed": True}, "vertices": [{"id": identifier, "label": identifier}], "edges": []}})
            if method == "GET":
                state.poll_count += 1
                if state.failures:
                    return reply({"error": {"message": "Temporary failure"}}, state.failures.pop(0))
                value = copy.deepcopy(job)
                if state.delayed:
                    delay = state.delayed; state.delayed = None
                    delay.started.set(); delay.release.wait(10)
                return reply(value)
        return False
    loading_server.route_handler = handler
    loading_server.responses[0].release.set()
    yield state
    if state.delayed:
        state.delayed.release.set()


def click(browser, selector):
    button = browser.find_element(By.CSS_SELECTOR, selector)
    step = browser.execute_script("const pane=arguments[0].closest('.data-pane'); return pane?.hidden ? pane.getAttribute('aria-labelledby') : null;", button)
    if step:
        browser.find_element(By.ID, step).click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", button)
    button.click()


def open_source(browser, server):
    if not browser.current_url.startswith(server.url):
        browser.get(server.url)
    wait_for(browser, "window.GraphMineWorkspace?.state.caps && !GraphMineWorkspace.state.busy")
    if not browser.find_elements(By.ID, "database-workspace"):
        click(browser, "#open-database-workspace")
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
    if browser.find_element(By.ID, "data-step-query").is_displayed():
        click(browser, "#data-step-query")


@pytest.mark.parametrize("width", [1440, 320])
def test_query_recovers_after_page_reload_without_executing_again(loading_browser, loading_server, database_jobs, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 1000})
    open_source(browser, loading_server)
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('12')")
    assert len(database_jobs.submissions) == 1 and database_jobs.submissions[0]["key"]
    click(browser, "#close-data-source")
    browser.refresh()
    open_source(browser, loading_server)
    click(browser, "#database-job-history > summary")
    wait_for(browser, "document.querySelector('[data-job-id=job-1]') !== null")
    click(browser, "[data-job-id=job-1] [data-job-action=open]")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('12')")
    database_jobs.jobs["job-1"].update(status="completed", cancellable=False, progress={"stage": "completed"})
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert "1 nodes" in browser.find_element(By.ID, "database-preview-count").text
    assert len(database_jobs.submissions) == 1 and database_jobs.result_reads == 1
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")


def test_cancel_waits_for_rollback_and_retry_is_explicit(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server); click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('cancel-database-job').disabled === false")
    click(browser, "#cancel-database-job")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Cancellation requested')")
    assert browser.find_element(By.ID, "preview-cypher").get_attribute("disabled")
    database_jobs.jobs["job-1"].update(status="cancelled")
    wait_for(browser, "document.getElementById('preview-cypher').disabled === false")
    assert database_jobs.result_reads == 0 and len(database_jobs.submissions) == 1
    click(browser, "#database-job-history > summary")
    wait_for(browser, "document.querySelector('[data-job-action=retry]') !== null")
    click(browser, "[data-job-action=retry]")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Reading')")
    assert len(database_jobs.submissions) == 2
    assert database_jobs.submissions[0]["key"] != database_jobs.submissions[1]["key"]
    database_jobs.jobs["job-2"].update(status="completed", cancellable=False, progress={"stage": "completed"})
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")


@pytest.mark.parametrize("failure", [503, 429])
def test_polling_recovers_from_transient_failure_without_resubmission(loading_browser, loading_server, database_jobs, failure):
    browser = loading_browser
    open_source(browser, loading_server)
    database_jobs.failures = [failure]
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('reconnecting')")
    database_jobs.jobs["job-1"].update(status="completed", cancellable=False, progress={"stage": "completed"})
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert len(database_jobs.submissions) == 1


def test_access_failure_stops_observation_without_rerunning_work(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server)
    database_jobs.failures = [403]
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Temporary failure')")
    assert browser.find_element(By.ID, "preview-cypher").is_enabled()
    assert database_jobs.poll_count == 1 and len(database_jobs.submissions) == 1


def test_closed_dialog_ignores_old_job_completion(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server)
    delay = SimpleNamespace(started=Event(), release=Event()); database_jobs.delayed = delay
    click(browser, "#preview-cypher")
    assert delay.started.wait(3)
    click(browser, "#close-data-source")
    open_source(browser, loading_server)
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('12')")
    database_jobs.jobs["job-2"].update(status="completed", cancellable=False, progress={"stage": "completed"})
    delay.release.set()
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert database_jobs.result_reads == 1 and len(database_jobs.submissions) == 2
    # Data is ready before the on-demand graph renderer finishes downloading.
    wait_for(browser, "document.querySelector('#database-query-graph canvas') !== null")


def test_sync_progress_disables_cancellation_at_commit(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server); click(browser, "#sync-database")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Graph refresh')")
    database_jobs.jobs["job-1"].update(cancellable=False, progress={"stage": "committing"})
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Committing')")
    assert not browser.find_element(By.ID, "cancel-database-job").is_enabled()
    database_jobs.jobs["job-1"].update(status="completed", progress={"stage": "completed"})
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Graph refreshed: 3 nodes')")
    assert database_jobs.submissions[0]["kind"] == "sync"


def test_job_failure_retains_inline_error_position_and_can_be_reviewed(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server); click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('12')")
    database_jobs.jobs["job-1"].update(status="failed", cancellable=False, error={"code": "cypher_syntax", "message": "Unexpected token", "details": {"line": 1, "column": 2, "offset": 1}})
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Unexpected token')")
    assert not browser.find_element(By.ID, "preview-cypher").get_attribute("disabled")
    assert "Unexpected token" in browser.find_element(By.ID, "query-inline-error").text
    assert len(database_jobs.submissions) == 1 and database_jobs.result_reads == 0


def test_submission_does_not_require_secure_context_uuid(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server)
    browser.execute_script("Object.defineProperty(window.crypto, 'randomUUID', {value: undefined, configurable: true})")
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('12')")
    assert len(database_jobs.submissions[0]["key"]) == 32
    assert all(character in "0123456789abcdef" for character in database_jobs.submissions[0]["key"])


def sync_summary(*, unchanged=False):
    return {"nodes": 3, "relationships": 2, "sync_mode": "incremental", "source_read_mode": "complete_snapshot",
            "changes": {"nodes": {"created": 0 if unchanged else 1, "updated": 0 if unchanged else 1, "deleted": 0 if unchanged else 1, "unchanged": 3 if unchanged else 1},
                        "relationships": {"created": 0 if unchanged else 1, "updated": 0 if unchanged else 1, "deleted": 0 if unchanged else 1, "unchanged": 2 if unchanged else 0, "recreated": 0 if unchanged else 1}},
            "schema_change": {"changed": not unchanged, "revision": 2}, "finished_at": "2026-10-22T12:00:00Z", "mapped_content_sha256": "a" * 64}


@pytest.mark.parametrize("width", [1440, 320])
def test_sync_change_summary_and_history_survive_reload_without_new_work(loading_browser, loading_server, database_jobs, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 1000})
    open_source(browser, loading_server); click(browser, "#sync-database")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Graph refresh')")
    database_jobs.jobs["job-1"].update(status="completed", cancellable=False, progress={"stage": "completed"}, synchronization=sync_summary())
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('2 added')")
    summary = browser.find_element(By.ID, "database-sync-summary")
    assert "Mapping revision 2 applied" in summary.text and "Saved analyses keep their original inputs" in summary.text
    assert "complete mapped SQL snapshot" in summary.text and "1 updated relationships changed endpoints or type" in summary.text
    assert [item.text for item in summary.find_elements(By.CSS_SELECTOR, "[data-sync-kind=nodes] dd")] == ["1", "1", "1", "1"]
    assert [item.text for item in summary.find_elements(By.CSS_SELECTOR, "[data-sync-kind=relationships] dd")] == ["1", "1", "1", "0"]
    click(browser, "#database-sync-summary details > summary")
    assert "a" * 64 in summary.text
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", summary)
    browser.save_screenshot(f"/tmp/graphmine-sync-summary-{width}.png")
    database_jobs.jobs["query-history"] = {**database_jobs.jobs["job-1"], "id": "query-history", "kind": "query", "synchronization": None}
    browser.refresh(); open_source(browser, loading_server); click(browser, "#database-job-history > summary")
    browser.execute_script("const filter=document.getElementById('database-job-kind'); filter.value='sync'; filter.dispatchEvent(new Event('change')); ")
    wait_for(browser, "document.querySelectorAll('[data-job-id]').length === 1 && document.querySelector('[data-job-id=job-1]') !== null")
    assert database_jobs.history_filters[-1] == "sync"
    assert browser.find_element(By.CSS_SELECTOR, "[data-job-id=job-1] [data-job-action=open]").text == "View changes"
    click(browser, "[data-job-id=job-1] [data-job-action=open]")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('2 added')")
    assert not browser.find_element(By.ID, "database-sync-summary").get_attribute("hidden")
    assert len(database_jobs.submissions) == 1 and database_jobs.result_reads == 2


def test_no_change_sync_and_schema_failure_are_distinct_in_history(loading_browser, loading_server, database_jobs):
    browser = loading_browser
    open_source(browser, loading_server); click(browser, "#sync-database")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Graph refresh')")
    database_jobs.jobs["job-1"].update(status="completed", cancellable=False, progress={"stage": "completed"}, synchronization=sync_summary(unchanged=True))
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('0 added · 0 updated · 0 removed · 5 unchanged')")
    assert browser.find_element(By.CSS_SELECTOR, "[data-sync-kind=nodes] [data-sync-change=updated]").text == "0"
    assert not browser.find_elements(By.CSS_SELECTOR, ".sync-mapping-change")
    click(browser, "#sync-database")
    wait_for(browser, "document.getElementById('database-job-status').textContent.includes('Reading')")
    database_jobs.jobs["job-2"].update(status="failed", cancellable=False, error={"code": "database_schema", "message": "Mapped SQL columns changed. Review the table mapping."})
    click(browser, "#refresh-database-job")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Mapped SQL columns changed')")
    assert browser.find_element(By.ID, "database-sync-summary").get_attribute("hidden")
    click(browser, "#database-job-history > summary")
    wait_for(browser, "document.querySelector('[data-job-id=job-2] [data-job-action=retry]') !== null")
    assert "Mapped SQL columns changed" in browser.find_element(By.CSS_SELECTOR, "[data-job-id=job-2]").text
    assert len(database_jobs.submissions) == 2 and database_jobs.result_reads == 1
