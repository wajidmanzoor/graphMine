"""Critical load gates and failure propagation, independent of a live store."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import common
import load_dataset
from cypher import check_batches, statements


def test_statement_boundaries_preserve_quoted_text_and_comments():
    text = '''// introductory ; comment
CREATE INDEX x FOR (n:X) ON (n.id);
CALL apoc.periodic.iterate("RETURN ';' AS s", "CREATE (:X {s:s})", {});
/* another ; comment */ RETURN `semi;colon`, 'it\\'s;fine'; // trailing
'''
    parsed = list(statements(text))
    assert len(parsed) == 3
    assert "RETURN ';' AS s" in parsed[1]
    assert parsed[2].endswith("'it\\'s;fine'")


def test_distinct_publisher_blocks_do_not_require_added_semicolons():
    marker = "// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html\n"
    assert list(statements(marker + "RETURN 1\n\n" + marker + "RETURN 2")) == [
        marker + "RETURN 1", marker + "RETURN 2"]


@pytest.mark.parametrize("failure", [
    {"failedBatches": 1}, {"failedOperations": 9},
    {"errorMessages": {"batch failed": 1}}, {"failedParams": {"0": [1]}},
    {"wasTerminated": True}, {"nested": [{"failedBatches": 2}]},
])
def test_failed_apoc_batches_are_never_treated_as_success(failure):
    with pytest.raises(ValueError, match="APOC reported"):
        check_batches(failure)
    check_batches({"failedBatches": 0, "failedOperations": 0, "errorMessages": {},
                   "failedParams": {}, "wasTerminated": False, "total": 100})


class Session:
    def __init__(self, nodes=0, relationships=0):
        self.nodes, self.relationships = nodes, relationships
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def run(self, text):
        self.statements.append(text)
        assert text.startswith("MATCH")
        value = self.relationships if "-[r]" in text else self.nodes
        return type("Result", (), {"single": lambda _: {"n": value}})()


def setup_loader(monkeypatch, tmp_path, session):
    monkeypatch.setenv("TMUX", "test")
    monkeypatch.setattr(common, "INSTANCE_ROOT", tmp_path)
    monkeypatch.setattr(common, "verify_inputs", lambda _: None)
    monkeypatch.setattr(common, "load_hashes", lambda _: {"load/001.cypher": "hash"})
    monkeypatch.setattr(common, "password", lambda _: "private-test-password")
    monkeypatch.setattr(load_dataset, "audit", lambda _: {"import_mode": "cypher", "page_sha256": "page"})
    driver = type("Driver", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None,
                                 "session": lambda *a, **kw: session})()
    monkeypatch.setattr(common, "driver", lambda _: driver)
    root = tmp_path / "yelp"
    root.mkdir()
    (root / "instance-check.json").write_text('{"nodes":0,"relationships":0}')
    return root


def test_nonempty_database_is_rejected_before_any_load_or_status_write(tmp_path, monkeypatch):
    session = Session(nodes=1)
    root = setup_loader(monkeypatch, tmp_path, session)
    monkeypatch.setattr(load_dataset, "execute_scripts", lambda *a: pytest.fail("no writes allowed"))
    with pytest.raises(ValueError, match="non-empty"):
        load_dataset.load("yelp")
    assert not (root / "status.json").exists()


def test_partial_failure_is_recorded_without_publishing_ready(tmp_path, monkeypatch):
    root = setup_loader(monkeypatch, tmp_path, Session())
    stops = []
    def stop(args, **kwargs):
        stops.append(args)
        return type("Result", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(load_dataset.subprocess, "run", stop)
    def fail(*args):
        raise ValueError("APOC failed private-test-password")
    monkeypatch.setattr(load_dataset, "execute_scripts", fail)
    with pytest.raises(ValueError):
        load_dataset.load("yelp")
    record = json.loads((root / "status.json").read_text())
    assert record["status"] == "failed"
    assert record["phase"] == "load_failed"
    assert record["service_stopped_after_failure"] is True
    assert stops == [["systemctl", "--user", "stop", "graphmine-neo4j-yelp.service"]]
    assert "private-test-password" not in (root / "status.json").read_text()


def test_successful_load_still_requires_verification(tmp_path, monkeypatch):
    root = setup_loader(monkeypatch, tmp_path, Session())
    monkeypatch.setattr(load_dataset, "execute_scripts", lambda *a: None)
    monkeypatch.setattr(load_dataset, "wait_indexes", lambda *a: [{"state": "ONLINE"}])
    monkeypatch.setattr(common, "graph_counts", lambda *a: {"total_nodes": 100})
    load_dataset.load("yelp")
    record = json.loads((root / "status.json").read_text())
    assert record["status"] == "loading"
    assert record["phase"] == "awaiting_verification"
    assert record["counts"]["total_nodes"] == 100


def test_loader_requires_persistent_session(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    with pytest.raises(ValueError, match="inside tmux"):
        load_dataset.load("yelp")
