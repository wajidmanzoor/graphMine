from __future__ import annotations

import pytest
from graphmine_agent.results import query_path, summarize_result


def test_result_summary_is_bounded_but_keeps_counts() -> None:
    summary = summarize_result({"output": {"items": list(range(100))}}, item_limit=5)
    items = summary["output"]["items"]
    assert items["count"] == 100
    assert items["items"] == [0, 1, 2, 3, 4]
    assert items["truncated"] is True


def test_result_query_pages_arrays_and_rejects_private_paths() -> None:
    payload = {"output": {"items": list(range(10))}}
    assert query_path(payload, "output.items", offset=2, limit=3)["items"] == [2, 3, 4]
    with pytest.raises(ValueError, match="invalid result path"):
        query_path(payload, "output._private")
