"""Runnable routing contracts. Scripted replies test invariants, not model accuracy."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import jsonschema
import pytest
from graphmine_agent._families import FAMILIES, PROBLEMS, TOPICS
from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
from graphmine_agent.analytics_taxonomy import family_context

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / 'agent/evaluation/family_routing_cases.json').read_text())['cases']
CARDS = [{"id": pid, "family": family, "topic_id": row['topic'],
          "title": row['title'], "description": row['description'], "quality": "exact",
          "input_kind": "graph", "parameters": {}, "output_ports": {}}
         for family, group in PROBLEMS.items() for pid, row in group.items()]


class Replay(AnalyticsPlanner):
    def __init__(self, replies):
        super().__init__(None, None, None)
        self.replies, self.calls, self.trace = list(replies), [], []

    async def _generate(self, stage, payload, schema, catalog=None):
        self.calls.append((stage, deepcopy(payload), deepcopy(catalog), deepcopy(schema)))
        assert self.replies, 'Unexpected extra model call'
        return self.replies.pop(0)

    async def remember(self, stage, decision):
        self.trace.append({"stage": stage, **decision})

    async def route(self, question):
        return await self._route_problems(PlanningRequest(message=question),
            {"question": question, "removed_problems": [], "problem_hints": {}}, CARDS, CARDS,
            facts=[], targets=None, input_facts=[], lookups=[], sources=[], remember=self.remember)


def family(identifier):
    return {"family_id": identifier, "reason": "Authored family selection"}


def calculation(problems, **extra):
    return {"intent": "options", "problems": problems, "message": "Authored calculation", **extra}


def test_cases_cover_every_family():
    counts = Counter(c['family'] for c in CASES)
    assert set(counts) == set(PROBLEMS)
    assert min(counts.values()) >= 3


@pytest.mark.parametrize('case', CASES, ids=lambda c:c['id'])
async def test_every_family_routes_directly_to_its_runnable_problems(case):
    selected = case['problems'][:1] or [next(iter(PROBLEMS[case['family']]))]
    planner = Replay([family(case['family']), calculation(selected)])
    decision, candidates = await planner.route(case['question'])
    assert [c[0] for c in planner.calls] == ['family','route']
    assert planner.calls[0][2] == family_context()
    offered = {p['id'] for f in planner.calls[1][2] for p in f['problems']}
    assert offered == set(PROBLEMS[case['family']])
    assert candidates == selected == decision['problems']
    assert all('topic' in p for f in planner.calls[1][2] for p in f['problems'])


async def test_topic_ambiguity_is_a_clarification_not_arbitrary_centrality():
    planner = Replay([family('importance'), {"intent":"needs_information", "message":"Do you mean many connections, bridges, or global influence?", "choices":[]}])
    result, _ = await planner.route('Which vertices are most important?')
    assert result['intent'] == 'needs_information'
    assert len(planner.calls) == 2


async def test_alternatives_are_ranked_calculations_not_combined_steps():
    ranked = [{'problems':['maximum-clique'],'reason':'Largest complete group'},
              {'problems':['maximal-cliques'],'reason':'Every unextendable group'}]
    planner = Replay([family('dense'), calculation(['maximum-clique'],ranked_calculations=ranked)])
    result, candidates = await planner.route('Explore complete groups')
    assert result['problems'] == ['maximum-clique']
    assert candidates == ['maximum-clique','maximal-cliques']
    assert result['ranked_calculations'] == ranked


async def test_no_more_than_three_alternatives():
    ranked=[{'problems':['maximum-clique'],'reason':'Choice'}]*4
    planner=Replay([family('dense'),calculation(['maximum-clique'],ranked_calculations=ranked)])
    with pytest.raises(jsonschema.ValidationError):await planner.route('Groups')


async def test_rejected_family_retries_once():
    planner=Replay([family('records'),{'intent':'unsupported','message':'No matching problem'},
                    family('paths'),{'intent':'unsupported','message':'No matching problem'}])
    result,candidates=await planner.route('An unclear request')
    assert result['intent']=='needs_information' and candidates==[]
    assert [c[0] for c in planner.calls]==['family','route','family','route']
    assert 'records' not in planner.calls[2][3]['properties']['family_id']['enum']
    assert [r['status'] for r in planner.trace if r['stage']=='family_reroute']==['retry','exhausted']


@pytest.mark.parametrize('evidence', [None,'Invented dependency'])
async def test_cross_family_steps_need_a_quote_from_the_question(evidence):
    extra={} if evidence is None else {'cross_family_steps':[{'problem':'query-subgraph','evidence':evidence}]}
    planner=Replay([family('motifs'),calculation(['query-subgraph','triangle-counting'],**extra)])
    with pytest.raises(ValueError,match='Cross-family'):await planner.route('Count triangles')


async def test_explicit_cross_family_dependency_is_kept():
    planner=Replay([family('motifs'),calculation(['query-subgraph','triangle-counting'],
        cross_family_steps=[{'problem':'query-subgraph','evidence':'Extract this neighbourhood'}])])
    result,candidates=await planner.route('Extract this neighbourhood, then count triangles')
    assert result['problems']==candidates==['query-subgraph','triangle-counting']


async def test_every_alternative_must_include_the_selected_family():
    planner=Replay([family('motifs'),calculation(['triangle-counting'],ranked_calculations=[
        {'problems':['triangle-counting'],'reason':'Count'}, {'problems':['pagerank'],'reason':'Unrelated'}])])
    with pytest.raises(ValueError,match='selected family'):await planner.route('Count triangles')


def test_topics_have_no_executable_contract():
    assert len(CARDS)==82 and len({c['id'] for c in CARDS})==82
    assert len(TOPICS)==71
    assert all(set(row)=={'title','description'} for row in TOPICS.values())
    context=family_context();context['records']['title']='Mutated'
    assert family_context()['records']['title']!='Mutated'


async def test_incomplete_clarification_keeps_choices_and_needs_no_extra_call():
    choices = ['Every pair connected', 'Mostly connected']
    planner = Replay([family('dense'), {'intent': 'needs_information',
        'message': 'What do you mean by ', 'choices': choices}])
    result, _ = await planner.route('Find tightly knit groups')
    assert result['message'] == 'Which of these meanings do you intend?'
    assert result['choices'] == choices
    assert len(planner.calls) == 2
