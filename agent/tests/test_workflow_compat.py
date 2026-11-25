"""Existing workflow history remains readable across the runnable-ID migration."""

import copy
import json
import sqlite3

import pytest

from graphmine_agent.errors import AnalyticsError
from graphmine_agent.workflow_compat import saved_plan, saved_result
from test_result_index import indexed_service  # noqa: F401


def test_saved_history_reads_both_keys_and_only_new_writes_migrate(indexed_service):
    service, record, _ = indexed_service
    legacy = copy.deepcopy(record)
    legacy.update(mode="interactive", approved_hash="original-approval")
    legacy["validation"].update(workflow_hash="original-approval", implementation_sha256="old-build")
    legacy["validation"]["plan"]["steps"][0].update(operation="pagerank", parameters={"operation": "user-value"})
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE workflows SET document=? WHERE id=?", (json.dumps(legacy), record["id"]))

    for value in (service.get(record["id"]), *service.list(record["session_id"]),
                  *service.list(record["session_id"], summary=True)):
        step = value["validation"]["plan"]["steps"][0]
        assert step["problem"] == "pagerank" and "operation" not in step
        assert step["parameters"]["operation"] == "user-value"
        assert value["revision"] == legacy["revision"]
        assert value["approved_hash"] == value["validation"]["workflow_hash"] == "original-approval"
        assert value["validation"]["implementation_sha256"] == "old-build"
        assert value["mode"] == "expert"
    with sqlite3.connect(service.path) as db:
        assert json.loads(db.execute("SELECT document FROM workflows WHERE id=?", (record["id"],)).fetchone()[0]) == legacy

    service._save(legacy)
    with sqlite3.connect(service.path) as db:
        stored = json.loads(db.execute("SELECT document FROM workflows WHERE id=?", (record["id"],)).fetchone()[0])
    assert stored["validation"]["plan"]["steps"][0]["problem"] == "pagerank"
    assert "operation" not in stored["validation"]["plan"]["steps"][0]
    assert legacy["validation"]["plan"]["steps"][0]["operation"] == "pagerank"


def test_saved_results_and_existing_row_indexes_preserve_original_bytes(indexed_service):
    service, record, save = indexed_service
    row = {"vertex": "001", "score": 1, "operation": "user-property"}
    step = save([row])
    step.update(status="completed", result_sha256="original-result-hash", cache_key="original-cache-key")
    step["result"].update(operation="pagerank", problem_id="centrality")
    artifact = {"steps": {"rank": step}, "plan": {"steps": [{"id": "rank", "operation": "pagerank"}]}}
    directory = service._directory(record)
    service._write(directory / "step-rank.json", step)
    service._write(directory / "result.json", artifact)
    paths = [directory / "step-rank.json", directory / "result.json"]
    before = {p: p.read_bytes() for p in paths}
    # Build an index with the legacy envelope, as on an existing installation.
    with service._indexed(record["id"]) as index:
        old = json.loads(index.db.execute("SELECT value FROM meta WHERE key='header'").fetchone()[0])
        assert old["steps"]["rank"]["result"]["operation"] == "pagerank"
    for saved in (service._read_result(paths[1]), service.result_summary(record["id"])):
        result = saved["steps"]["rank"]["result"]
        assert result["problem"] == "pagerank" and result["topic_id"] == "centrality"
        assert "operation" not in result and "problem_id" not in result
        assert result["ports"]["output"]["value"] == [row]
        assert saved["steps"]["rank"]["result_sha256"] == "original-result-hash"
        assert saved["plan"]["steps"][0]["problem"] == "pagerank"
    assert service._read_result(paths[0])["result"]["problem"] == "pagerank"
    assert service.port_page(record["id"], "rank", "output", 0, 10)["items"] == [row]
    assert {p: p.read_bytes() for p in paths} == before


def test_conflicting_saved_ids_are_rejected_and_current_results_are_not_copied():
    with pytest.raises(AnalyticsError, match="conflicting"):
        saved_plan({"steps": [{"operation": "pagerank", "problem": "triangle-counting"}]})
    with pytest.raises(AnalyticsError, match="conflicting"):
        saved_result({"result": {"problem_id": "centrality", "topic_id": "triangles"}})
    current = {"steps": {"rank": {"result": {"problem": "pagerank", "topic_id": "centrality"}}}}
    assert saved_result(current) is current
