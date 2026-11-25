"""Choice ranking and edited plans are checked independently of model wording."""

from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from graphmine_agent.accounts import _collect_stream
from graphmine_agent.analytics_options import (
    candidate_menu, catalog_signature, load_calibration, make_cards, match_score,
    problem_logprob, rank_candidates, sampling_contract, validate_edits,
    semantic_key, SCORE_VERSION,
)


def card(op="pagerank", **parameters):
    return {"id": op, "family": "ranking", "title": op, "description": "Rank graph vertices.",
        "quality": "exact", "input_kind": "graph", "parameters": parameters,
        "requirements": {"input_kind": "graph", "direction": "either", "weights": "optional", "unit_weight_mode": True, "needs": []}}


PROFILE = {"input_kind": "graph", "directed": True, "vertices_count": 10, "edges_count": 20}


def samples(menu, counts):
    return [{"decision": {"problem": menu[index]["problem"], "parameter_choice": menu[index]["id"], "interpretation": "Rank the people."},
             "problem_logprob": {"sum": -.02, "tokens": 2, "mean": -.01}}
            for index, count in enumerate(counts) for _ in range(count)]


def test_menu_filters_ineligible_preserves_defaults_and_never_exposes_vertex_ids():
    cards = [card(sources={"kind": "array", "required": True}, damping={"kind": "number", "default": .85}),
             {**card("wrong"), "input_kind": "hypergraph", "requirements": {**card()["requirements"], "input_kind": "hypergraph"}}]
    menu = candidate_menu(cards, {"main": PROFILE}, "Rank Ann", [{"input": "main", "id": "secret-vertex-id", "matched": "Ann", "label": "Ann"}])
    assert len(menu) == 1 and menu[0]["parameters"] == {"sources": ["secret-vertex-id"], "damping": .85}
    schema, prompt = sampling_contract(menu, cards)
    assert "secret-vertex-id" not in json.dumps([schema, prompt])
    assert "wrong" not in json.dumps(prompt)


def test_rank_uses_votes_problem_likelihood_and_missing_penalty():
    assert match_score(4, [{"mean": -.1}], 0) > match_score(3, [{"mean": -.1}], 0)
    assert match_score(4, [{"mean": -.1}], 0) > match_score(4, [{"mean": -2}], 0)
    assert match_score(4, [{"mean": -.1}], 0) > match_score(4, [{"mean": -.1}], 1)
    assert match_score(0, [], 0) == 0


def test_high_requires_calibration_and_actual_logprobs():
    menu = candidate_menu([card(), card("degree-centrality")], {"main": PROFILE}, "Rank people")
    votes = samples(menu, [5, 0])
    assert rank_candidates(menu, votes)[0]["match"] == "Medium"
    assert rank_candidates(menu, votes, {"high": {"threshold": .9}})[0]["match"] == "High"
    for sample in votes:
        sample["problem_logprob"] = None
    assert rank_candidates(menu, votes, {"high": {"threshold": .5}})[0]["match"] != "High"


def test_unsampled_runner_does_not_become_a_second_card():
    cards = [card(mode={"kind": "string", "default": "rank", "choices": ["rank", "score"]}), card("degree-centrality")]
    menu = candidate_menu(cards, {"main": PROFILE}, "Rank people")
    ranked = rank_candidates(menu, samples(menu, [5, 0, 0]), {"high": {"threshold": .9}})
    options = make_cards(ranked, cards, {"main": PROFILE}, "Who is important?")
    assert len(options) == 1 and options[0]["preselected"]
    assert ranked[1]["match"] == "Low" and ranked[1]["score"] == 0
    assert options[0]["parameters"]["mode"] == "rank"
    assert all(option["cost_hint"] and option["difference"] and option["interpretation"] for option in options)


def test_one_problem_with_one_compatible_calculation_does_not_need_an_unrelated_alternative():
    cards = [card()]
    menu = candidate_menu(cards, {"main": PROFILE}, "Compute PageRank.")
    ranked = rank_candidates(menu, samples(menu, [5]), {"high": {"threshold": .9}})
    options = make_cards(ranked, cards, {"main": PROFILE}, "Compute PageRank.")
    assert len(options) == 1
    assert options[0]["problems"] == [cards[0]["id"]]
    assert options[0]["parameters"] == menu[0]["parameters"]
    assert options[0]["preselected"]


def test_supported_different_objective_remains_a_second_choice():
    cards = [card(), card("degree-centrality")]
    menu = candidate_menu(cards, {"main": PROFILE}, "Rank important people")
    ranked = rank_candidates(menu, samples(menu, [3, 2]))
    options = make_cards(ranked, cards, {"main": PROFILE}, "Rank important people")
    assert len(options) == 2
    assert [o["problems"] for o in options] == [["pagerank"], ["degree-centrality"]]
    assert all(o["match"] == "Medium" for o in options)


def test_a_low_match_with_high_token_likelihood_cannot_displace_a_supported_choice():
    cards = [card(op) for op in ["pagerank", "degree-centrality", "other-a", "other-b"]]
    menu = candidate_menu(cards, {"main": PROFILE}, "Rank people")
    votes = samples(menu, [1, 2, 1, 1])
    for sample in votes[1:]:
        sample["problem_logprob"]["mean"] = -1
    ranked = rank_candidates(menu, votes)
    assert ranked[0]["match"] == "Low" and ranked[0]["problem"] == "pagerank"
    options = make_cards(ranked, cards, {"main": PROFILE}, "Rank people")
    assert len(options) == 1 and options[0]["problems"] == ["degree-centrality"]


def density_card():
    return card("densest-subgraph", clique_order={"kind": "integer", "default": 2},
                minimum_vertices={"kind": "integer", "default": 1},
                weight_mode={"kind": "string", "default": "unweighted", "choices": ["unweighted", "edge_weight"]},
                solution_quality={"kind": "string", "default": "exact", "choices": ["exact", "approximate"]})


def test_densest_subgraph_has_one_exact_recommendation_and_retains_weighted_objective():
    cards = [density_card()]
    menu = candidate_menu(cards, {"main": PROFILE}, "find the densest subgraph")
    assert len(menu) == 2
    assert {c["parameters"]["weight_mode"] for c in menu} == {"unweighted", "edge_weight"}
    assert all(c["parameters"]["solution_quality"] == "exact" for c in menu)
    options = make_cards(rank_candidates(menu, samples(menu, [5, 0])), cards, {"main": PROFILE}, "find the densest subgraph")
    assert len(options) == 1 and options[0]["quality"] == "exact"
    assert options[0]["quality_guarantees"]["densest-subgraph"]["by_request"]["approximate"] == "exact"
    # An explicit weaker request and an old saved card remain legal requests.
    validate_edits(options[0], {**options[0]["parameters"], "solution_quality": "approximate"})
    requested = candidate_menu(cards, {"main": PROFILE}, "find the densest subgraph",
                               selected=["densest-subgraph"], supplied={"solution_quality": "approximate"})
    assert requested[0]["parameters"]["solution_quality"] == "approximate"
    chosen = make_cards(rank_candidates(requested, samples(requested, [5, 0])), cards, {"main": PROFILE}, "find the densest subgraph")[0]
    assert chosen["quality"] == "exact" and chosen["parameters"]["solution_quality"] == "approximate"


def test_real_quality_variants_and_input_size_objectives_are_not_merged():
    community = {**card("community-detection", solution_quality={"kind": "string", "default": "heuristic", "choices": ["exact", "heuristic"]}), "quality": "parameter_dependent"}
    menu = candidate_menu([community], {"main": PROFILE}, "Find communities")
    options = make_cards(rank_candidates(menu, samples(menu, [3, 2])), [community], {"main": PROFILE}, "Find communities")
    assert len(options) == 2 and {o["quality"] for o in options} == {"heuristic", "exact"}
    c = density_card()
    first = {"problem": c["id"], "input": "main", "parameters": {}}
    original = semantic_key(first, [c])
    assert original != semantic_key({**first, "input": "other"}, [c])
    assert original != semantic_key({**first, "parameters": {"clique_order": 3}}, [c])
    assert original != semantic_key({**first, "parameters": {"minimum_vertices": 5}}, [c])
    assert original == semantic_key({**first, "parameters": {"solution_quality": "approximate"}}, [c])


def test_merge_identical_choices_and_reject_invented_choices():
    menu = candidate_menu([card(), card("degree-centrality")], {"main": PROFILE}, "Rank people")
    votes = samples(menu, [3, 2])
    votes[0]["decision"]["parameter_choice"] = "invented"
    ranked = rank_candidates(menu, votes)
    assert sum(row["match_evidence"]["votes"] for row in ranked) == 4
    assert len(ranked) == 2


def test_multi_problem_options_preserve_parameters_quality_and_eligibility():
    cards = [card("extract", k={"kind": "integer", "default": 3}),
             {**card("community"), "quality": "heuristic"}]
    menu = candidate_menu(cards, {"main": PROFILE}, "Extract and group", selected=["extract", "community"], supplied={"extract": {"k": 5}, "community": {}})
    assert all("extract" not in row["parameters"] for row in menu if not row.get("problems"))
    chain = next(row for row in menu if row.get("problems"))
    assert chain["parameters"] == {"extract": {"k": 5}, "community": {}}
    votes = samples([chain], [5])
    options = make_cards(rank_candidates(menu, votes), cards, {"main": PROFILE}, "Extract and group")
    assert options[0]["quality"] == "mixed"
    assert options[0]["problem_qualities"] == {"extract": "exact", "community": "heuristic"}
    assert options[0]["title"] == "extract → community"
    cards[1]["requirements"]["input_kind"] = "hypergraph"
    assert not any(row.get("problems") for row in candidate_menu(cards, {"main": PROFILE}, "Extract and group", selected=["extract", "community"]))


def test_edited_parameters_are_schema_checked_and_cannot_add_arguments():
    cards = [card(damping={"kind": "number", "default": .85, "minimum": 0, "maximum": 1}), card("degree-centrality")]
    menu = candidate_menu(cards, {"main": PROFILE}, "Rank people")
    option = make_cards(rank_candidates(menu, samples(menu, [5, 0])), cards, {"main": PROFILE}, "Rank people")[0]
    validate_edits(option, {"damping": .5})
    with pytest.raises(ValueError, match="Invalid edited parameter"):
        validate_edits(option, {"damping": 9})
    with pytest.raises(ValueError, match="Invalid edited parameter"):
        validate_edits(option, {"source": "invented"})
    old = {"problems": ["pagerank"], "parameters": {"damping": .85}}
    with pytest.raises(ValueError, match="match"):
        validate_edits(old, {"damping": .5})


def test_problem_probability_handles_split_utf8_tokens_and_ignores_prose():
    text = '{"interpretation":"Ann é", "problem":"page' + 'rank"}'
    raw = text.encode(); start = raw.index(b"pagerank")
    parts = [raw[:start], b"page", b"rank", raw[start + 8:]]
    choice = {"message": {"content": text}, "logprobs": {"content": [
        {"bytes": list(part), "logprob": probability} for part, probability in zip(parts, [-100, -.2, -.4, -100])]}}
    result = problem_logprob(choice)
    assert result["sum"] == pytest.approx(-.6) and result["tokens"] == 2
    choice["logprobs"]["content"].append({"token": "<|im_end|>", "logprob": -100})
    assert problem_logprob(choice) == result
    choice["logprobs"]["content"].pop()
    choice["logprobs"]["content"].pop()
    assert problem_logprob(choice) is None


async def test_stream_keeps_five_choices_separate_and_preserves_logprobs():
    chunks = []
    for fragment in ['{"problem":"', 'pagerank"}']:
        for index in reversed(range(5)):
            chunks.append({"choices": [{"index": index, "delta": {"content": fragment},
                "logprobs": {"content": [{"token": fragment, "bytes": list(fragment.encode()), "logprob": -.1}]},
                "finish_reason": "stop" if fragment.endswith("}") else None}]})
    chunks.append({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    response = httpx.Response(200, content="\n".join("data: " + json.dumps(chunk) for chunk in chunks) + "\ndata: [DONE]\n")
    async def reasoning(text):
        raise AssertionError("No reasoning was sent")
    result = await _collect_stream(response, reasoning)
    assert [row["index"] for row in result["choices"]] == list(range(5))
    assert all(len(row["logprobs"]["content"]) == 2 for row in result["choices"])
    assert all(json.loads(row["message"]["content"])["problem"] == "pagerank" for row in result["choices"])
    assert result["usage"]["total_tokens"] == 30


def test_calibration_is_bound_to_model_catalog_and_precision(tmp_path):
    settings = SimpleNamespace(repository_root=tmp_path, analytics_router_model=None, llm_model="router", analytics_router_base_url=None, llm_base_url="http://router/v1")
    cards = [card()]
    calibration = {"score_version": SCORE_VERSION, "samples": 5, "temperature": .7, "model": "router", "server": "http://router/v1", "catalog_sha256": catalog_signature(cards),
                   "high": {"count": 7, "precision": 6/7, "threshold": .9}}
    path = tmp_path / "catalog/option_calibration.json"; path.parent.mkdir()
    path.write_text(json.dumps(calibration))
    assert load_calibration(settings, cards)
    assert load_calibration(settings, [card("changed")]) is None
    assert load_calibration(settings, [{**cards[0], "quality": "parameter_dependent"}]) is None
    path.write_text(json.dumps({**calibration, "score_version": 1}))
    assert load_calibration(settings, cards) is None
    calibration["high"]["precision"] = .8; path.write_text(json.dumps(calibration))
    assert load_calibration(settings, cards) is None
