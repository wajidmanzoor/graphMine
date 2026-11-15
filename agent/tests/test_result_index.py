"""Indexed reads retain full result semantics without reparsing warm artifacts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from graphmine_agent.analytics import AnalyticsError, AnalyticsService, _matches, _sort_key
from graphmine_agent.database import RecordNotFound
from graphmine_agent.result_index import add_port, open_index


@pytest.fixture
def indexed_service(settings, database, graph_store, session):
    service = AnalyticsService(settings, database, graph_store, None)
    record = {"id": "indexed", "session_id": session.id, "revision": 1, "status": "completed",
              "steps": {"rank": {"status": "completed"}}, "validation": {"plan": {"steps": [{"id": "rank"}]}}}
    service._save(record)
    def save(rows, kind="vertex_scores"):
        step = {"result": {"ports": {"output": {"type": kind, "complete": False, "value": rows}}}}
        service._write(service._directory(record) / "step-rank.json", step)
        service._write(service._directory(record) / "result.json", {"steps": {"rank": step}})
        return step
    return service, record, save


def test_warm_pages_summaries_and_memberships_never_parse_sources(indexed_service, monkeypatch):
    service, _, save = indexed_service
    rows = [{"group": i, "vertices": [i, "001", 9007199254740993]} for i in range(10_000)]
    save(rows, "vertex_groups")
    assert service.port_page("indexed", "rank", "output", 9998, 2)["positions"] == [9998, 9999]
    assert service.result_summary("indexed", limit=2)["steps"]["rank"]["result"]["ports"]["output"]["total_items"] == 10000
    def no_source(*_args, **_kwargs):
        raise AssertionError("A warm page must not parse the source artifact")
    original_open = Path.open
    def checked_open(path, *args, **kwargs):
        if path.suffix == ".json":
            no_source()
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", checked_open)
    monkeypatch.setattr(service, "_read_result", no_source)
    assert service.port_page("indexed", "rank", "output", 0, 3, sort="group", descending=True)["positions"] == [9999, 9998, 9997]
    assert service.port_page("indexed", "rank", "output", 0, 3, member='"001"', min_size=2, max_size=3)["matched_items"] == 10000
    assert service.group_memberships("indexed", "rank", "output", ["001", 0, 9007199254740993])["memberships"] == [
        {"vertex": "001", "groups": 10000}, {"vertex": 0, "groups": 1}, {"vertex": 9007199254740993, "groups": 10000}]
    assert len(service.result_summary("indexed", limit=1)["steps"]["rank"]["result"]["ports"]["output"]["value"]) == 1
    assert not service.result_cache  # A page did not populate the full-result cache.


@pytest.mark.parametrize("descending", [False, True])
def test_typed_sort_search_missing_values_and_stable_ties(indexed_service, descending):
    service, _, save = indexed_service
    rows = [{"key": value, "label": "Straße"} for value in [None, 9007199254740993, 9007199254740992, 10**40, -10**40, 1.5, 1, 1, True, False, "1", {"x": 1}, [1]]]
    rows.append({"absent": True}); save(rows)
    present = [i for i, row in enumerate(rows) if row.get("key") is not None]
    expected = sorted(present, key=lambda i: _sort_key(rows[i]["key"]), reverse=descending) + [0, len(rows)-1]
    actual = []
    for offset in range(0, len(rows), 3):
        actual += service.port_page("indexed", "rank", "output", offset, 3, sort="key", descending=descending)["positions"]
    assert actual == expected
    for search in ['key:9007199254740993', 'key:"1"', 'key:true', 'key:null', 'STRASSE', 'key:{"x":1}', 'missing:null']:
        assert service.port_page("indexed", "rank", "output", 0, 100, search=search)["items"] == [row for row in rows if _matches(row, search)]
    assert service.port_page("indexed", "rank", "output", 0, 100, sort="unknown")["items"] == rows


def test_source_changes_revisions_missing_files_and_corrupt_indexes(indexed_service):
    service, record, save = indexed_service
    save([{"score": 1}])
    assert service.port_page("indexed", "rank", "output", 0, 1)["items"] == [{"score": 1}]
    path = service._directory(record) / "step-rank.json"
    path.with_suffix(".rows.sqlite3").write_bytes(b"broken cache")
    assert service.port_page("indexed", "rank", "output", 0, 1)["items"] == [{"score": 1}]
    save([{"score": 2}])  # Same size, new artifact generation.
    assert service.port_page("indexed", "rank", "output", 0, 1)["items"] == [{"score": 2}]
    record["revision"] = 2; service._save(record)
    with pytest.raises(AnalyticsError, match="revision changed"):
        service.port_page("indexed", "rank", "output", 0, 1, expected_revision=1)
    record["revision"] = 1; service._save(record); path.unlink()
    with pytest.raises(RecordNotFound):
        service.port_page("indexed", "rank", "output", 0, 1)


@pytest.mark.parametrize("value,kind,items", [([], "vertex_scores", []), (42, "scalar", [42]),
    ({"z": [[3, 4]], "a": [[1, 2]]}, "motif_instances", [{"pattern": "a", "vertices": [1, 2]}, {"pattern": "z", "vertices": [3, 4]}])])
def test_empty_scalar_and_instance_ports(indexed_service, value, kind, items):
    service, _, save = indexed_service; save(value, kind)
    assert service.port_page("indexed", "rank", "output", 0, 10)["items"] == items
    summary = service.result_summary("indexed")["steps"]["rank"]["result"]["ports"]["output"]
    assert summary["value"] == (value if kind == "scalar" else items)
    assert not summary.get("value_truncated")


def test_concurrent_readers_build_once_and_failed_build_is_not_published(tmp_path):
    path = tmp_path / "rows.sqlite3"; builds = []
    def build(db):
        builds.append(1); add_port(db, "rows", {"value": [{"score": i} for i in range(1000)]})
        return {}
    def read(_):
        with open_index(path, lambda: "stable", build) as index:
            return index.page("rows", 995, 5)["positions"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read, range(16))) == [[995, 996, 997, 998, 999]] * 16
    assert len(builds) == 1
    def fail(db):
        raise ValueError("interrupted construction")
    with pytest.raises(ValueError):
        with open_index(path, lambda: "next", fail):
            pass
    assert read(None) == [995, 996, 997, 998, 999]
    assert not list(tmp_path.glob("*.tmp"))


def test_source_changed_during_read_is_rejected(tmp_path):
    token = ["first"]
    with pytest.raises(AnalyticsError, match="changed during"):
        with open_index(tmp_path / "rows.sqlite3", lambda: token[0], lambda _: {}) as index:
            token[0] = "second"


def test_oversized_source_is_rejected_before_reading(indexed_service, monkeypatch):
    service, _, save = indexed_service
    save([{"score": 1}])
    monkeypatch.setattr(service, "settings", replace(service.settings, max_result_bytes=2))
    with pytest.raises(AnalyticsError, match="byte budget"):
        service.port_page("indexed", "rank", "output", 0, 1)


def test_sort_and_exact_query_plans_use_persistent_indexes(tmp_path):
    with open_index(tmp_path / "rows.sqlite3", lambda: "same", lambda db: (add_port(db, "p", {"value": [{"v": i} for i in range(100)]}) or {})) as index:
        for direction, name in (("ASC", "field_asc"), ("DESC", "field_desc")):
            plans = index.db.execute(f"EXPLAIN QUERY PLAN SELECT position FROM fields WHERE port=? AND name=? AND rank IS NOT NULL ORDER BY rank {direction},position LIMIT 10", ("p", "v")).fetchall()
            assert name in str(plans) and "TEMP B-TREE" not in str(plans)
        plans = index.db.execute("EXPLAIN QUERY PLAN SELECT position FROM fields WHERE port=? AND name=? AND exact=?", ("p", "v", "99")).fetchall()
        assert "field_exact" in str(plans)
