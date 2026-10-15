"""Group summaries and filters use full retained outputs and typed member IDs."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.analytics import AnalyticsError, AnalyticsService
from graphmine_agent.api import create_app


@pytest.fixture
def groups_service(monkeypatch):
    rows = [{"group": i, "vertices": [i + 10]} for i in range(500)]
    rows += [
        {"group": 900, "vertices": [1, 2, 3]},
        {"group": 901, "vertices": ["1", 2]},
        {"group": 902, "vertices": [1, 2]},
        {"group": 903, "vertices": ["001", 9007199254740993]},
    ]
    result = {
        "ports": {
            "groups": {"type": "vertex_groups", "value": rows, "complete": False},
            "scores": {"type": "vertex_scores", "value": [{"vertex": 1, "score": 2}]},
        }
    }
    service = object.__new__(AnalyticsService)
    monkeypatch.setattr(
        service,
        "_saved",
        lambda _id, step=None: (
            {"result": result} if step else {"steps": {"mine": {"result": result}}}
        ),
    )
    return service, result


def test_summary_counts_full_groups_without_mutating_cached_result(groups_service):
    service, result = groups_service
    before = deepcopy(result)
    summary = service.result_summary("saved", limit=2)
    groups = summary["steps"]["mine"]["result"]["ports"]["groups"]
    assert len(groups["value"]) == 2
    assert groups["value_truncated"] and not groups["complete"]
    assert groups["group_summary"] == {
        "groups": 504,
        "unique_members": 506,
        "shared_members": 2,
        "smallest": 1,
        "largest": 3,
    }
    assert result == before


@pytest.mark.parametrize(
    ("member", "positions"),
    [("1", [500, 502]), ('"1"', [501]), ("001", [503]), ("9007199254740993", [503])],
)
def test_member_search_reaches_beyond_preview_and_preserves_ids(
    groups_service, member, positions
):
    service, result = groups_service
    page = service.port_page("saved", "mine", "groups", 0, 10, member=member)
    assert page["positions"] == positions
    assert page["items"] == [result["ports"]["groups"]["value"][i] for i in positions]
    assert page["total_items"] == 504
    assert not page["complete"]


def test_size_member_search_sort_and_paging_combine(groups_service):
    service, _ = groups_service
    page = service.port_page(
        "saved",
        "mine",
        "groups",
        1,
        1,
        member="2",
        min_size=2,
        max_size=2,
        sort="group",
        descending=True,
    )
    assert page["matched_items"] == 2
    assert page["positions"] == [501]
    assert not page["has_more"]
    assert (
        service.port_page("saved", "mine", "groups", 0, 10, min_size=4)["items"] == []
    )


def test_memberships_cover_all_groups_and_preserve_typed_ids(groups_service):
    service, result = groups_service
    result["ports"]["groups"]["value"][500]["vertices"].append(1)
    before = deepcopy(result)
    response = service.group_memberships(
        "saved", "mine", "groups", [1, "1", 2, 3, 9007199254740993, 0, 1]
    )
    assert response == {
        "scope": "retained_groups",
        "total_groups": 504,
        "complete": False,
        "memberships": [
            {"vertex": 1, "groups": 2},
            {"vertex": "1", "groups": 1},
            {"vertex": 2, "groups": 3},
            {"vertex": 3, "groups": 1},
            {"vertex": 9007199254740993, "groups": 1},
            {"vertex": 0, "groups": 0},
        ],
    }
    assert result == before
    with pytest.raises(AnalyticsError, match="group output"):
        service.group_memberships("saved", "mine", "scores", [1])


@pytest.mark.parametrize("member", ["true", "null", "[]", "{}", "1.5"])
def test_invalid_member_ids_are_rejected(groups_service, member):
    with pytest.raises(AnalyticsError, match="integer or text"):
        groups_service[0].port_page("saved", "mine", "groups", 0, 10, member=member)


def test_invalid_size_range_and_non_group_outputs_are_rejected(groups_service):
    service, _ = groups_service
    with pytest.raises(AnalyticsError, match="Minimum size"):
        service.port_page("saved", "mine", "groups", 0, 10, min_size=3, max_size=2)
    with pytest.raises(AnalyticsError, match="group output"):
        service.port_page("saved", "mine", "scores", 0, 10, member="1")


def test_http_group_filters_validate_and_preserve_original_positions(
    settings, groups_service
):
    headers = {"Authorization": "Bearer test-secret"}
    with TestClient(create_app(settings)) as client:
        session = client.post(
            "/api/sessions", headers=headers, json={"domain_id": "general"}
        ).json()
        service = client.app.state.runtime.analytics
        record = {
            "id": "saved-groups",
            "session_id": session["id"],
            "revision": 1,
            "status": "completed",
            "steps": {"mine": {"status": "completed"}},
            "validation": {"plan": {"steps": [{"id": "mine"}]}},
        }
        service._save(record)
        service._write(
            service._directory(record) / "step-mine.json", {"result": groups_service[1]}
        )
        path = "/api/workflows/saved-groups/steps/mine/ports/groups"
        page = client.get(
            path,
            headers=headers,
            params={"member": '"1"', "min_size": 2, "max_size": 2},
        )
        assert page.status_code == 200, page.text
        assert page.json()["positions"] == [501]
        for params in (
            {"min_size": -1},
            {"max_size": "1.5"},
            {"member": "true"},
            {"min_size": 3, "max_size": 2},
        ):
            assert client.get(path, headers=headers, params=params).status_code == 422
        memberships = client.post(
            path + "/memberships", headers=headers, json={"vertices": [1, "1", 2]}
        )
        assert memberships.status_code == 200, memberships.text
        assert memberships.json()["memberships"] == [
            {"vertex": 1, "groups": 2},
            {"vertex": "1", "groups": 1},
            {"vertex": 2, "groups": 3},
        ]
        for vertices in ([], [True], [1.0], [None], [{}], list(range(501))):
            assert (
                client.post(
                    path + "/memberships", headers=headers, json={"vertices": vertices}
                ).status_code
                == 422
            )
