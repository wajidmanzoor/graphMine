"""The bulk adaptation must never touch another store or discard a failed attempt."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import common
import ldbc_bulk


def test_bulk_arguments_retain_exact_groups_and_strict_bad_entry_policy(tmp_path):
    # Shape mirrors the published eight node / 23 edge groups, without host data.
    groups = []
    for i in range(31):
        name = f"Group{i}"
        group = {"kind": "nodes" if i < 8 else "rels", "labels_or_type": "Message:Comment" if i == 0 else name,
                 "subdirectory": "dynamic", "entity": name, "parts": ["original.csv.gz"]}
        header = tmp_path / f"import/headers/dynamic/{name}.csv"
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text("id:ID\n")
        part = tmp_path / f"import/csv/initial_snapshot/dynamic/{name}/part-000.csv"
        part.parent.mkdir(parents=True)
        part.write_text("1\n")
        groups.append(group)
    args = ldbc_bulk.arguments(tmp_path, {"bulk": {"plan": {"groups": groups}}})
    assert args[4] == "neo4j"
    assert "--bad-tolerance=0" in args
    assert "--delimiter=|" in args and "--array-delimiter=;" in args
    assert any(a.startswith("--nodes=Message:Comment=") for a in args)
    assert sum(a.startswith("--nodes=") for a in args) == 8
    assert sum(a.startswith("--relationships=") for a in args) == 23
    assert not any(a.startswith(("--overwrite-destination", "--skip-bad", "--schema", "--temp-path")) for a in args)


def test_bulk_refuses_config_pointing_at_another_database(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "INSTANCE_ROOT", tmp_path)
    root = tmp_path / "ldbc-snb"
    (root / "conf").mkdir(parents=True)
    (root / "conf/neo4j.conf").write_text("server.directories.data=/some/other/store\n")
    with pytest.raises(ValueError, match="dedicated directory"):
        ldbc_bulk.bootstrap_paths(root)


def test_failed_bulk_import_preserves_attempt_and_restores_only_empty_target(tmp_path, monkeypatch):
    instances = tmp_path / "instances"
    monkeypatch.setattr(common, "INSTANCE_ROOT", instances)
    code = tmp_path / "code"
    code.mkdir()
    monkeypatch.setattr(common, "SOURCE_ROOT", code)
    previous = ["yelp", "movielens-32m", "movielens-genome"]
    (code / "registry.json").write_text(json.dumps({"datasets": [{"id": slug} for slug in previous]}))
    for slug in previous:
        common.write_json(instances / slug / "status.json", {"status": "ready"})
    ontime = instances / "ontime/status.json"
    common.write_json(ontime, {"status": "loading", "phase": "loading"})
    ontime_before = ontime.read_bytes()
    root = instances / "ldbc-snb"
    (root / "conf").mkdir(parents=True)
    (root / "conf/neo4j.conf").write_text(
        f"server.directories.data={root / 'data'}\nserver.directories.transaction.logs.root={root / 'transactions'}\n")
    paths = {"database": root / "data/databases/neo4j", "transactions": root / "transactions/neo4j"}
    for path in paths.values():
        path.mkdir(parents=True)
        (path / "empty-bootstrap-marker").write_text("preserve")
    system = root / "data/databases/system"
    system.mkdir()
    (system / "system-marker").write_text("untouched")
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def session(self, **_): return self
        def run(self, *_): return SimpleNamespace(single=lambda: {"n": 0})
    monkeypatch.setattr(common, "driver", lambda _: Connection())
    monkeypatch.setattr(ldbc_bulk, "arguments", lambda *a: ["test-import-command"])
    monkeypatch.setattr(ldbc_bulk, "wait_running", lambda: None)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == "systemd-run":
            for path in paths.values():
                path.mkdir(parents=True)
                (path / "partial-import").write_text("failed but preserved")
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(ldbc_bulk.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="bulk import failed"):
        ldbc_bulk.import_snapshot({}, {"status": "loading"})
    for name, path in paths.items():
        assert (path / "empty-bootstrap-marker").read_text() == "preserve"
        assert (root / "failed-bulk-store" / name / "partial-import").exists()
    assert (system / "system-marker").read_text() == "untouched"
    assert ontime.read_bytes() == ontime_before
    service_calls = [args for args in calls if args[0] == "systemctl"]
    assert service_calls == [["systemctl", "--user", action, "graphmine-neo4j-ldbc-snb.service"] for action in ["stop", "start"]]


@pytest.mark.parametrize("missing", ["yelp", "movielens-32m", "movielens-genome"])
def test_parallel_import_still_requires_the_completed_datasets(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(common, "SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(common, "INSTANCE_ROOT", tmp_path / "instances")
    previous = {"yelp", "movielens-32m", "movielens-genome"} - {missing}
    (tmp_path / "registry.json").write_text(json.dumps({"datasets": [{"id": slug} for slug in previous]}))
    monkeypatch.setattr(common, "driver", lambda _: pytest.fail("No database may be opened before the prerequisite gate"))
    with pytest.raises(ValueError, match="Yelp and both MovieLens"):
        ldbc_bulk.import_snapshot({}, {"status": "loading"})
