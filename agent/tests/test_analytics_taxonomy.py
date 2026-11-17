"""Catalog isolation and bounded routing; authored replies are not accuracy tests."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from graphmine_agent._families import FAMILIES, PROBLEMS
from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
from graphmine_agent.analytics_taxonomy import candidate_operations, family_context, problem_context, problem_schema

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "agent/evaluation/family_routing_cases.json").read_text())["cases"]
CARDS = [{"id": operation, "family": family, "problem_id": identifier,
          "title": problem["title"], "description": problem["description"],
          "quality": "exact", "input_kind": "graph", "parameters": {}, "output_ports": {}}
         for family, problems in PROBLEMS.items() for identifier, problem in problems.items()
         for operation in problem["operation_ids"]]


class Replay(AnalyticsPlanner):
    def __init__(self, replies):
        super().__init__(None, None, None)
        self.replies, self.calls, self.trace = list(replies), [], []

    async def _generate(self, stage, payload, schema, catalog=None):
        self.calls.append((stage, deepcopy(payload), deepcopy(catalog), deepcopy(schema)))
        assert self.replies, "Unexpected extra model call"
        return self.replies.pop(0)

    async def remember(self, stage, decision):
        self.trace.append({"stage": stage, **decision})

    async def route(self, question):
        return await self._route_problems(PlanningRequest(message=question),
            {"question": question, "removed_operations": [], "operation_hints": {}}, CARDS, CARDS,
            facts=[], targets=None, input_facts=[], lookups=[], sources=[], remember=self.remember)


def selected(family, identifiers=None, *, dependencies=False):
    return {"status": "selected", "message": "The requested problem fits.",
            "requires_cross_family_steps": dependencies,
            "candidates": [{"problem_id": identifier, "reason": "It matches the requested result."}
                           for identifier in (identifiers or list(PROBLEMS[family])[:1])]}


def test_routing_cases_cover_every_family_at_least_three_times():
    counts = Counter(case["family"] for case in CASES)
    assert set(counts) == {family["id"] for family in FAMILIES}
    assert min(counts.values()) >= 3


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_family_then_only_its_problems_then_candidate_operations(case):
    family = case["family"]
    operation = next(iter(case["operations"]), next(iter(PROBLEMS[family].values()))["operation_ids"][0])
    problem = next(identifier for identifier, row in PROBLEMS[family].items() if operation in row["operation_ids"])
    planner = Replay([{"family_id": family, "reason": "Authored family decision."},
                      selected(family, [problem]),
                      {"intent": "calculate", "operations": [operation], "message": "Authored operation decision."}])
    decision, candidates = await planner.route(case["question"])
    assert [call[0] for call in planner.calls] == ["family", "problem", "route"]
    assert planner.calls[0][1] == {"question": case["question"]}
    assert planner.calls[0][2] == json.loads((ROOT / "catalog/family.json").read_text())
    assert all(set(row) == {"title", "description", "deciding_question"} for row in planner.calls[0][2].values())
    assert planner.calls[1][1] == {"question": case["question"], "family_id": family}
    assert planner.calls[1][2] == json.loads((ROOT / "catalog/problems.json").read_text())[family]
    offered = {op["id"] for row in planner.calls[2][2] for op in row["operations"]}
    assert offered == set(PROBLEMS[family][problem]["operation_ids"]) == set(candidates)
    assert decision["operations"] == [operation]


async def test_two_problem_candidates_are_ranked_alternatives_not_two_executions():
    family = next(row["family"] for row in CARDS if row["id"] == "maximum-clique")
    identifiers = [row["problem_id"] for row in CARDS if row["id"] in ("maximal-cliques", "maximum-clique")]
    planner = Replay([{"family_id": family, "reason": "Complete groups."}, selected(family, identifiers),
                      {"intent": "calculate", "operations": ["maximum-clique"], "message": "Largest complete group."}])
    decision, candidates = await planner.route("Find the largest complete group.")
    assert decision["operations"] == ["maximum-clique"]
    assert set(candidates) == {"maximal-cliques", "maximum-clique"}
    assert [row["problem_id"] for row in planner.calls[2][1]["candidate_problems"]] == identifiers


@pytest.mark.parametrize("invalid", ["duplicate", "foreign", "three"])
def test_invalid_problem_shortlists_fail(invalid):
    family = FAMILIES[3]["id"]
    identifiers = list(PROBLEMS[family])
    decision = selected(family, identifiers[:2])
    if invalid == "duplicate":
        decision["candidates"][1]["problem_id"] = decision["candidates"][0]["problem_id"]
        with pytest.raises(ValueError, match="distinct"):
            candidate_operations(family, decision)
    else:
        if invalid == "foreign":
            decision["candidates"][0]["problem_id"] = next(iter(PROBLEMS[FAMILIES[0]["id"]]))
        else:
            decision["candidates"].append({"problem_id": identifiers[2], "reason": "Third candidate."})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(decision, problem_schema(family))


async def test_wrong_family_gets_one_reroute_and_no_unbounded_retry():
    first, second = [row["id"] for row in FAMILIES[:2]]
    planner = Replay([{"family_id": first, "reason": "First attempt."},
                      {"status": "reroute", "message": "No matching problem."},
                      {"family_id": second, "reason": "Second attempt."},
                      {"status": "reroute", "message": "Still no matching problem."}])
    decision, candidates = await planner.route("An unclear request.")
    assert decision["intent"] == "needs_information" and candidates == []
    assert len(planner.calls) == 4 and not planner.replies
    assert first not in planner.calls[2][3]["properties"]["family_id"]["enum"]
    assert [row["status"] for row in planner.trace if row["stage"] == "family_reroute"] == ["retry", "exhausted"]


async def test_cross_family_dependency_is_available_only_after_problem_selection():
    card = next(row for row in CARDS if row["id"] == "triangle-counting")
    family = card["family"]
    planner = Replay([{"family_id": family, "reason": "The final result is a count."},
                      selected(family, [card["problem_id"]], dependencies=True),
                      {"intent": "calculate", "operations": ["query-subgraph", "triangle-counting"],
                       "message": "Extract the requested graph, then count its triangles."}])
    decision, candidates = await planner.route("Extract this neighbourhood, then count its triangles.")
    assert planner.calls[0][2] == family_context()
    assert planner.calls[1][2] == problem_context(family)
    assert decision["operations"] == ["query-subgraph", "triangle-counting"]
    assert "query-subgraph" in candidates and "pagerank" not in candidates


async def test_followup_keeps_bounded_conversation_without_sending_plans_or_data_to_selection():
    card = next(row for row in CARDS if row["id"] == "triangle-counting")
    planner = Replay([{"family_id": card["family"], "reason": "Previous question's subject."},
                      selected(card["family"], [card["problem_id"]]),
                      {"intent": "calculate", "operations": [card["id"]], "message": "Repeat the count."}])
    history = [{"role": "user", "message": "Count triangles. " + "x" * 2000}] * 8
    payload = {"question": "Do that again.", "conversation": history,
               "previous_plan": {"steps": ["private-plan-marker"]},
               "inputs": {"main": {"vertices_sample": ["private-data-marker"]}},
               "removed_operations": [], "operation_hints": {}}
    await planner._route_problems(PlanningRequest(message=payload["question"]), payload, CARDS, CARDS,
        facts=[], targets=None, input_facts=[], lookups=[], sources=[], remember=planner.remember)
    for call in planner.calls[:2]:
        assert len(call[1]["conversation"]) == 4
        assert max(len(row["message"]) for row in call[1]["conversation"]) == 1000
        assert "private-plan-marker" not in json.dumps(call[1])
        assert "private-data-marker" not in json.dumps(call[1])


def test_returned_catalog_copies_cannot_mutate_later_requests():
    family = FAMILIES[0]["id"]
    context = family_context()
    context[family]["title"] = "Changed"
    problems = problem_context(family)
    problems.clear()
    assert family_context()[family]["title"] != "Changed"
    assert problem_context(family)


def test_algorithm_catalog_keeps_repeated_backend_ids_distinct_per_operation():
    catalog = json.loads((ROOT / "catalog/algo.json").read_text())
    problems = {identifier: row for group in PROBLEMS.values() for identifier, row in group.items()}
    assert set(catalog) == set(problems)
    observed = set()
    for identifier, implementations in catalog.items():
        pairs = [(row["operation_id"], row["backend_id"]) for row in implementations.values()]
        assert len(pairs) == len(set(pairs))
        assert {operation for operation, _backend in pairs} == set(problems[identifier]["operation_ids"])
        observed.update(operation for operation, _backend in pairs)
        assert all("compiled" not in row and "verified" not in row for row in implementations.values())
    assert observed == {row["id"] for row in CARDS}
    centrality = next(row["problem_id"] for row in CARDS if row["id"] == "degree-centrality")
    assert {row["operation_id"] for row in catalog[centrality].values() if row["backend_id"] == "cpp"} == {
        "degree-centrality", "betweenness-centrality", "pagerank"}
