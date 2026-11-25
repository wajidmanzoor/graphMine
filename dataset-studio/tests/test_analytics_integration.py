from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import studio
from graphmine_agent.analytics_examples import digest
from graphmine_agent.analytics_studio import FORMAT

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle():
    plan = {"version": 1, "device": "cpu", "steps": [{"id": "core", "problem": "k-core", "input": {"input": "main"}, "parameters": {"requested_k": 1}, "bindings": {}}]}
    result = {"complete": True, "workflow_hash": "a" * 64, "steps": {"core": {"status": "completed", "result": {"complete": True, "count": 9007199254740993}}}}
    provenance = {"workflow_id": "w1", "expected_revision": 3, "workflow_hash": "a" * 64, "implementation_sha256": "b" * 64, "result_sha256": digest(result)}
    review = {"id": "example-1", "status": "approved", "question": "Find the core — réseau", "plan": plan, "provenance": provenance, "inputs": {"main": {"kind": "graph", "file_sha256": "c" * 64}}, "authorship": {"target_author": None, "reviewer": {"name": "source-reviewer", "user_id": "u1"}}}
    review["content_sha256"] = digest(review)
    context = {"cards": [{"id": "k-core", "parameters": {"requested_k": {"kind": "integer"}}, "output_ports": {"count": {"type": "scalar"}}}], "aliases": ["main"], "device": "cpu"}
    output = {"status": "ready", "message": "", "plan": plan}
    row = {"id": "example-1", "schema": "AnalyticsPlanNormalized", "adapter": "workflow", "context": context, "output": output,
           "question": review["question"], "source_review": review, "authorship": review["authorship"], "evidence": {**provenance, "result": result},
           "messages": [{"role": "system", "content": "Normalized workflow contract"}, {"role": "user", "content": json.dumps({"question": review["question"], "context": context, "inputs": review["inputs"]})}, {"role": "assistant", "content": json.dumps(output)}]}
    value = {"schema_version": FORMAT, "example": row}
    value["sha256"] = digest(value)
    return value


@pytest.fixture
def store(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    app = studio.Studio(data, tmp_path / "workspace", studio.Catalog(REPO), studio.Schemas(REPO / "agent"))
    info = app.create_dataset("Reviewed analytics", created_by="curator")
    studio.ACTOR.name = "curator"
    yield app.store_for(info["key"])
    studio.ACTOR.name = None


def imported(store, bundle):
    return store.import_analytics(json.dumps(bundle))["example"]


def revisions(store):
    return {e["id"]: e["revision"] for e in store.all_effective()}


def approve(store, ex):
    return store.update(ex["id"], {"review": "approved"}, ex["revision"])["example"]


def test_import_review_export_retains_source_local_authorship_and_evidence(store, bundle):
    ex = imported(store, bundle)
    assert ex["schema"] == "AnalyticsPlanNormalized" and not ex["needs_context"]
    assert ex["review"] == "unreviewed" and ex["created_by"] == "curator"
    assert not [i for i in ex["issues"] if i["level"] == "error"]
    assert store.import_analytics(json.dumps(bundle))["reused"]
    studio.ACTOR.name = "reviewer"
    ex = approve(store, ex)
    assert ex["review_proof"]["by"] == "reviewer" and ex["created_by"] == "curator"
    assert ex["review_proof"]["revision"] == ex["revision"]
    result = store.export("verified", expected_revisions=revisions(store))
    path = Path(result["path"])
    row = json.loads((path / "sft/workflow/train.jsonl").read_text())
    assert row["messages"] == bundle["example"]["messages"]
    annotation = json.loads((path / "annotations.jsonl").read_text())
    assert annotation["analytics"] == bundle
    assert annotation["review_proof"] == ex["review_proof"]
    manifest = json.loads((path / "manifest.json").read_text())
    for name, metadata in manifest["files"].items():
        assert hashlib.sha256((path / name).read_bytes()).hexdigest() == metadata["sha256"]
    base = studio.build_index(path, "reusable")
    assert base[0]["analytics"] == bundle and base[0]["schema"] == "AnalyticsPlanNormalized"
    assert base[0]["prompts"][0]["value"] == bundle["example"]["question"]
    assert base[0]["source_studio"]["created_by"] == "curator"
    assert base[0]["source_studio"]["review_proof"] == ex["review_proof"]
    info = {"key": "roundtrip", "layout": "reusable", "path": str(path.relative_to(store.data_root))}
    reopened = studio.Store(store.studio, info)
    new_review = approve(reopened, reopened.all_effective()[0])
    again = reopened.export("again", expected_revisions=revisions(reopened))
    final = json.loads((Path(again["path"]) / "annotations.jsonl").read_text())
    assert final["source_studio"]["review_proof"] == ex["review_proof"]
    assert final["review_proof"] == new_review["review_proof"]
    assert annotation["analytics"]["example"]["evidence"]["result"]["steps"]["core"]["result"]["count"] == 9007199254740993


@pytest.mark.parametrize("patch", [{"output": {"status": "unsupported", "message": "Changed", "plan": None}}, {"prompts": {"question": "A new question"}}, {"turns": [{"role": "user", "text": "different context"}]}])
def test_semantic_edits_invalidate_review_and_execution_evidence(store, bundle, patch):
    ex = approve(store, imported(store, bundle))
    ex = store.update(ex["id"], patch, ex["revision"])["example"]
    assert ex["review"] == "unreviewed" and ex["review_proof"] is None
    with pytest.raises(ValueError, match="before approving"):
        approve(store, ex)
    export = store.export("drafts", approved_only=False, expected_revisions=revisions(store))
    assert export["counts"]["skipped_invalid"] == 1
    assert not (Path(export["path"]) / "sft").exists()


def test_stale_updates_bulk_and_export_are_rejected_before_any_write(store, bundle):
    ex = imported(store, bundle); old = revisions(store)
    newer = store.update(ex["id"], {"notes": "another reviewer"}, ex["revision"])["example"]
    with pytest.raises(LookupError):
        store.update(ex["id"], {"review": "approved"}, ex["revision"])
    with pytest.raises(LookupError):
        store.bulk([ex["id"]], {"review": "approved"}, old)
    with pytest.raises(LookupError):
        store.export("stale", expected_revisions=old)
    assert not (store.home(store.current) / "exports/stale").exists()
    assert store.effective(ex["id"])["revision"] == newer["revision"]
    with pytest.raises(LookupError):
        store.update(ex["id"], {"review": "approved"})


def test_notes_preserve_review_but_revisions_survive_restart_and_revert(store, bundle):
    ex = approve(store, imported(store, bundle)); proof = ex["review_proof"]
    ex = store.update(ex["id"], {"notes": "Checked evidence"}, ex["revision"])["example"]
    assert ex["review"] == "approved" and ex["review_proof"] == proof
    reopened = studio.Store(store.studio, store.current)
    assert reopened.effective(ex["id"])["revision"] == ex["revision"]
    reopened.revert([ex["id"]], {ex["id"]: ex["revision"]})
    assert not reopened.ids()
    assert reopened.history(ex["id"])[-1]["op"] == "discard"


@pytest.mark.parametrize("field", ["result", "review", "messages", "question"])
def test_corrupted_or_inconsistent_exchange_is_never_imported(store, bundle, field):
    row = bundle["example"]
    if field == "result": row["evidence"]["result"]["complete"] = False
    if field == "review": row["source_review"]["status"] = "revoked"
    if field == "messages": row["messages"][-1]["content"] = "{}"
    if field == "question": row["question"] = "changed"
    bundle["sha256"] = digest({k: v for k, v in bundle.items() if k != "sha256"})
    with pytest.raises(ValueError): imported(store, bundle)
    assert not store.ids()


def test_approval_and_provenance_cannot_be_supplied_as_editable_metadata(store, bundle):
    ex = imported(store, bundle)
    forged = store.update(ex["id"], {"review_proof": {"by": "admin"}, "created_by": "admin", "analytics": {}}, ex["revision"])["example"]
    assert forged["created_by"] == "curator" and forged["review_proof"] is None and forged["analytics"] == bundle
    duplicate = store.duplicate_conversation(ex["group"])["examples"][0]
    assert duplicate["analytics"] == bundle and duplicate["review"] == "unreviewed"
    assert store.schemas.check("UnknownSchema", {})[1]
    assert store.schemas.check("AnalyticsAnswer", {"lead": "Result", "fact_ids": ["x"]})[1]
    with pytest.raises(ValueError):
        store.update(ex["id"], {"adapter": "../../escaped"}, forged["revision"])


def test_first_startup_creates_default_data_root(tmp_path, monkeypatch):
    import studio_engine
    from types import SimpleNamespace
    monkeypatch.setattr(studio_engine, "Engine", lambda _repo: SimpleNamespace(available=False, error="test fixture"))
    monkeypatch.setattr(studio, "ThreadingHTTPServer", lambda *_args: SimpleNamespace(serve_forever=lambda: None, server_close=lambda: None))
    # This case exercises standalone defaults, without linked GraphMine accounts.
    monkeypatch.delenv("GRAPHMINE_AGENT_DATA_ROOT", raising=False)
    repo = tmp_path / "fresh-repo"
    studio.main(["--repo", str(repo), "--workspace", str(tmp_path / "workspace")])
    assert (repo / ".graphmine-learning").is_dir()


def test_legacy_rows_require_current_review_and_revert_keeps_revision_monotonic(store):
    folder = store.data_root / "legacy"
    (folder / "sft/planner").mkdir(parents=True)
    output = {"supported": False, "confidence": 1, "explanation": "Unsupported request"}
    row = {"messages": [{"role": "system", "content": "Route the request"}, {"role": "user", "content": json.dumps({"message": "Predict the weather"})}, {"role": "assistant", "content": json.dumps(output)}]}
    (folder / "sft/planner/train.jsonl").write_text(json.dumps(row) + "\n")
    (folder / "sft-index.jsonl").write_text(json.dumps({"id": "legacy-row", "file": "sft/planner/train.jsonl", "row": 0, "row_sha256": studio.digest(row), "schema": "RouteDecision"}) + "\n")
    legacy = studio.Store(store.studio, {"key": "legacy", "layout": "reusable", "path": "legacy"})
    ex = legacy.effective("legacy-row")
    assert ex["revision"] == 0 and ex["created_by"] is None
    # A review from an older journal has no proof of the reviewed content.
    legacy.overlay[ex["id"]] = {"review": "approved"}
    skipped = legacy.export("old-review", expected_revisions=revisions(legacy))
    assert skipped["counts"]["skipped_stale_review"] == 1
    ex = approve(legacy, ex)
    ex = legacy.update(ex["id"], {"output": {**output, "confidence": .5}}, ex["revision"])["example"]
    assert ex["review"] == "unreviewed"
    legacy.revert([ex["id"]], {ex["id"]: ex["revision"]})
    restored = legacy.effective(ex["id"])
    assert restored["output"] == output and restored["revision"] > ex["revision"]
    ex = approve(legacy, restored)
    exported = legacy.export("current-review", expected_revisions=revisions(legacy))
    assert exported["counts"]["sft/planner/train.jsonl"] == 1
    assert ex["created_by"] is None
