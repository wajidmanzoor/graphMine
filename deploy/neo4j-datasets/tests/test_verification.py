"""Verification must never publish an unchecked or altered graph."""

from datetime import date, datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from verify_dataset import count_differences, publish, query_checks_passed, run_statement, selected_queries, typed_parameters


def test_count_explanations_must_match_actual_counts_and_the_source_record():
    expected = {"nodes": {"User": 3}, "relationships": {"FRIEND": 2}}
    actual = {"nodes": {"User": 2}, "relationships": {"FRIEND": 2, "EXTRA": 1}}
    note = {"kind": "nodes", "name": "User", "expected": 3, "actual": 2,
            "reason": "One source row is absent.", "evidence": "source-receipt.json"}
    differences = count_differences(expected, actual, [note], note["reason"])
    assert differences[0]["explained"] is True
    assert differences[1]["explained"] is False
    assert not count_differences(expected, actual, [note], "unrelated documentation")[0]["explained"]
    note["actual"] = 1
    assert not count_differences(expected, actual, [note], note["reason"])[0]["explained"]


@pytest.mark.parametrize("report,state", [({"passed": False}, {"status": "ready"}),
                                         ({"passed": True}, {"status": "loading"})])
def test_registry_rejects_unverified_state(report, state):
    with pytest.raises(ValueError, match="passed verification"):
        publish("yelp", report, state)


def test_representative_checks_require_every_selected_query_and_never_count_untested_queries():
    selected = {"Q01", "Q08"}
    records = [{"id": "Q01", "status": "passed"}, {"id": "Q08", "status": "not_run"}]
    assert not query_checks_passed(records, selected)
    records[1]["status"] = "skipped_write"
    assert not query_checks_passed(records, selected)
    records[1]["status"] = "passed"
    records.append({"id": "Q20", "status": "not_run"})
    assert query_checks_passed(records, selected)
    records.append({"id": "Q08", "status": "failed"})
    assert not query_checks_passed(records, selected)


def test_representative_selection_matches_archived_sources():
    from source_pages import audit
    for slug in ("yelp", "movielens-32m", "movielens-genome", "ontime", "ldbc-snb"):
        manifest = audit(slug)
        assert len(selected_queries(slug, manifest)) == 4
        assert selected_queries(slug, manifest) < selected_queries(slug, manifest, all_queries=True)


def test_typed_parameters_preserve_temporal_types():
    result = typed_parameters({"birthday": {"type": "date", "value": "1990-01-02"},
                               "startDate": {"type": "datetime", "value": "2010-01-01T00:00:00+00:00"},
                               "limit": 20, "languages": ["en"]})
    assert result["birthday"] == date(1990, 1, 2)
    assert isinstance(result["startDate"], datetime)
    assert result["limit"] == 20


def test_write_query_is_explained_but_never_executed():
    calls = []
    class Transaction:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def rollback(self): calls.append("rollback")
        def run(self, text, params):
            calls.append(text)
            assert text.startswith("EXPLAIN ")
            return type("Result", (), {"consume": lambda _: type("Summary", (), {"query_type": "rw"})()})()
    session = type("Session", (), {"begin_transaction": lambda *a, **kw: Transaction()})()
    result = run_statement(session, "MATCH (n) SET n.changed = true", {}, 10)
    assert result["status"] == "skipped_write"
    assert calls == ["EXPLAIN MATCH (n) SET n.changed = true", "rollback"]
