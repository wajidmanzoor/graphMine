"""Cross-feature acceptance with real native mocks and the CPU graph solver.

The simulated sentiment is fixture data, not a model-quality measurement.
"""

from itertools import combinations
import json
import os
import sys
import time

import pytest

from graphmine_agent.query_previews import QueryPreviews, expire_previews
from test_database_integration import analyze
from test_database_jobs import wait_job
from test_database_workspace import source, workspace  # noqa: F401
from test_semantic_native import native_engine  # noqa: F401
from test_semantic_queries import submit


def test_movie_refinement_saved_input_and_actual_densest_quality(workspace, native_engine, record_property):
    client, runtime = workspace.client, workspace.runtime
    graph = {
        "graph": {"id": "movie-review-fixture", "directed": False,
                  "allows_self_loops": False, "allows_parallel_edges": False},
        "vertices": [
            {"id": name, "type": "Movie", "attributes": {"title": name, "neo4j_labels": ["Movie"]}}
            for name in ("movie-a", "movie-b")
        ] + [
            {"id": name, "type": "Review", "attributes": {
                "text": text, "mock_sentiment": sentiment, "neo4j_labels": ["Review"]}}
            for name, text, sentiment in [
                ("r1", "Tedious and disappointing.", "negative"),
                ("r2", "The ending ruined it.", "negative"),
                ("r3", "A delightful film.", "positive"),
                ("r4", "Not worth watching.", "negative"),
            ]
        ],
        "edges": [{"id": "e" + str(i), "source": "r" + str(i), "target": movie,
                   "type": "REVIEWS", "weight": 1}
                  for i, movie in [(1, "movie-a"), (2, "movie-a"), (3, "movie-a"), (4, "movie-b")]],
    }
    previews = QueryPreviews(runtime)
    base = previews.store(graph, name="Movie reviews (synthetic)", kind="graph", complete=True,
                          source={"type": "database_query", "database_source": {"id": "demo"},
                                  "query": "MATCH p=(r:Review)-[:REVIEWS]->(m:Movie) RETURN p", "lineage": {}})
    assert client.post(f"/api/database-query-snapshots/{base['id']}/save").status_code == 200
    original = previews.get(base["id"], content=True)
    calls_before = len(workspace.calls)
    statement = """MATCH (r:Vertex)-[e:REVIEWS]->(m:Vertex)
WHERE has_label(r,'Review') AND has_label(m,'Movie')
WITH r,e,m,r.mock_sentiment AS sentiment
WHERE llm('mock','Echo {{sentiment}} {answer STRING}') = $negative
RETURN r,e,m"""
    job = submit(workspace, base_version_id=base["id"], model="mock", statement=statement,
                 parameters={"negative": '["negative"]'}, directed=False)
    wait_job(client, job["id"])
    response = client.get(f"/api/database-jobs/{job['id']}/result")
    assert response.status_code == 200, response.text
    output = response.json()["dataset"]
    derived = json.loads(previews.get(output["id"], content=True)[1])
    assert {v["id"] for v in derived["vertices"]} == {"movie-a", "movie-b", "r1", "r2", "r4"}
    assert {e["id"] for e in derived["edges"]} == {"e1", "e2", "e4"}
    assert output["source"]["simulation"] and not output["source"]["model_dependent_input"]
    assert output["source"]["settings"]["http_requests"] == 0
    assert output["source"]["parent"]["version_id"] == base["id"]
    assert client.post(f"/api/database-query-snapshots/{output['id']}/save").status_code == 200
    opened = client.post(f"/api/database-query-snapshots/{output['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    record, result = analyze(client, opened.json(), "densest-subgraph", {"solution_quality": "approximate"})
    # Independently enumerate every nonempty subset; the solver's quality is
    # established on the selected graph, not by the requested option or the mock.
    ids = {v["id"] for v in derived["vertices"]}
    def density(members):
        return sum(e["weight"] for e in derived["edges"]
                   if e["source"] in members and e["target"] in members) / len(members)
    optimum = max(density(set(group)) for n in range(1, len(ids) + 1) for group in combinations(ids, n))
    selected = set(result["ports"]["vertices"]["value"])
    assert selected == {"movie-a", "r1", "r2"}
    assert result["result"]["density"] == pytest.approx(optimum)
    assert density(selected) == pytest.approx(optimum)
    assert result["quality"] == "exact" and result["complete"] is True
    recorded = record["input_provenance"]["main"]
    assert recorded["version_id"] == output["id"] and recorded["sha256"] == output["sha256"]
    assert recorded["source"]["simulation"] and recorded["source"]["query"] == statement
    view = client.get(f"/api/workflows/{record['id']}/steps/analyze/ports/vertices/view",
                      params={"expected_revision": record["revision"]})
    assert view.status_code == 200, view.text
    assert {v["id"] for v in view.json()["vertices"]} == selected
    assert len(view.json()["edges"]) == 2
    follow = submit(workspace, "structural-followup", base_version_id=output["id"], statement="MATCH(n:Vertex) RETURN n")
    wait_job(client, follow["id"])
    inherited = client.get(f"/api/database-jobs/{follow['id']}/result").json()["dataset"]["source"]
    assert inherited["simulation"] and not inherited["steps"]
    assert inherited["parent"]["source"]["query"] == statement
    assert previews.get(base["id"], content=True) == original
    assert len(workspace.calls) == calls_before
    record_property("acceptance", json.dumps({"base": original[0], "refined": previews.get(output["id"]),
        "workflow_id": record["id"], "revision": record["revision"], "result": result,
        "independent_optimum": optimum, "input_graph": graph, "refined_graph": derived}))


@pytest.mark.parametrize("failure", ["timeout", "cancel", "crash"])
def test_real_child_failure_never_publishes_and_retry_creates_one_version(workspace, monkeypatch, tmp_path, native_engine, failure):
    from graphmine_agent import semantic_queries
    original_worker = semantic_queries.run_worker
    marker = tmp_path / "worker-pid"
    script = f"""
import json, os, pathlib, sys, time
pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))
pathlib.Path(sys.argv[-1]).with_name('result.json').write_text('{{"partial":true}}')
print(json.dumps({{'type':'progress','stage':'asking_model','usage':{{'calls':2}}}}), flush=True)
if {failure!r} == 'crash':
    sys.exit(7)
time.sleep(30)
"""
    def blocked(graph, body, **kwargs):
        kwargs["timeout"] = 0.5 if failure == "timeout" else 10
        return original_worker(graph, body, command=[sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(semantic_queries, "run_worker", blocked)
    previews = QueryPreviews(workspace.runtime)
    base = workspace.snapshot["dataset"]["id"]
    original = previews.get(base, content=True)
    job = submit(workspace)
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    if failure == "cancel":
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            running = workspace.client.get(f"/api/database-jobs/{job['id']}").json()
            if running.get("progress", {}).get("usage", {}).get("calls") == 2:
                break
            time.sleep(0.01)
        assert workspace.client.delete(f"/api/database-jobs/{job['id']}").status_code == 200
    failed = wait_job(workspace.client, job["id"], "cancelled" if failure == "cancel" else "failed")
    if failure != "cancel":
        assert failed["error"]["code"] == ("semantic_timeout" if failure == "timeout" else "semantic_worker_failed")
    assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").status_code == 409
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert previews.get(base, content=True) == original
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_previews").fetchone()[0] == 0
    monkeypatch.setattr(semantic_queries, "run_worker", original_worker)
    retry = workspace.client.post(f"/api/database-jobs/{job['id']}/retry", headers={"Idempotency-Key": "safe-retry"})
    assert retry.status_code == 202, retry.text
    retried = retry.json()["job"]
    wait_job(workspace.client, retried["id"])
    output = workspace.client.get(f"/api/database-jobs/{retried['id']}/result").json()["dataset"]
    assert output["source"]["base_version_id"] == base
    assert output["id"] != base
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_previews").fetchone()[0] == 1


def test_queued_expired_base_executes_then_releases_its_lease(workspace, native_engine):
    client, runtime = workspace.client, workspace.runtime
    client.portal.call(runtime.database_jobs.stop)
    previews = QueryPreviews(runtime)
    base, raw = previews.get(workspace.snapshot["dataset"]["id"], content=True)
    temporary = previews.store(json.loads(raw), name="queued parent", kind="graph", source=base["source"], complete=True)
    job = submit(workspace, base_version_id=temporary["id"])
    with runtime.database._connect() as db:
        db.execute("UPDATE query_previews SET expires_at=0 WHERE id=?", (temporary["id"],))
    assert expire_previews(runtime.database) == 0
    client.portal.call(runtime.database_jobs.start)
    wait_job(client, job["id"])
    output = client.get(f"/api/database-jobs/{job['id']}/result").json()["dataset"]
    assert output["source"]["base_sha256"] == temporary["sha256"]
    assert expire_previews(runtime.database) == 1
    assert previews.get(output["id"])["id"] == output["id"]
    assert client.get(f"/api/database-query-snapshots/{temporary['id']}/semantic-schema").status_code == 404
