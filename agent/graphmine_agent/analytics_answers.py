"""Answers in chat: facts computed from the result, chosen and introduced by a model.

The model never writes a number. It picks which facts answer the question and
adds one lead sentence without digits or number words; every figure comes from
the saved result.
"""

from __future__ import annotations

import json
import re
import time

import httpx
import jsonschema

FACT_LIMIT = 12
QUALITY = {
    "exact": "exact, so it establishes the declared result",
    "heuristic": "a heuristic, so it does not guarantee the best possible answer",
    "approximate": "approximate",
    "numerical": "a numerical calculation",
    "stochastic": "randomized, so repeated runs can differ",
}
SYSTEM = (
    "You answer a person's question about their network using only the supplied "
    "facts, which were computed by a verified graph library. Choose the facts that "
    "answer the question, most relevant first. Write one plain-language lead "
    "sentence that answers the question from the chosen facts, naming the specific "
    "entities they identify. The lead must not contain digits or number words such "
    "as two or three; the facts state the figures. Do not claim anything the facts "
    "do not state, including causes or real-world meaning. Choose facts about "
    "guarantees or completeness only when "
    "the question asks about reliability or a chosen output is incomplete. Return "
    "JSON matching the supplied schema."
)
CLIQUE_OPERATIONS = {"maximal-cliques", "maximum-clique", "k-cliques"}

_NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
} | {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000, "dozen": 12,
}
# "One of them" and "no one" do not state a count.
_NOT_A_COUNT = re.compile(r"\b(?:no|any|every|each|some)\s+one\b|\bone\s+(?:of|another)\b", re.IGNORECASE)
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def _numbers(text):
    """Every number a sentence states, in digits or words."""
    text = _NOT_A_COUNT.sub(" ", text)
    found = [float(match.group().replace(",", "")) for match in _NUMERAL.finditer(text)]
    words = re.findall(r"[a-z]+", text.lower())
    index = 0
    while index < len(words):
        value = _NUMBER_WORDS.get(words[index])
        if value is not None:
            following = _NUMBER_WORDS.get(words[index + 1]) if index + 1 < len(words) else None
            if 20 <= value < 100 and following is not None and 0 < following < 10:
                value += following  # twenty-one
                index += 1
            found.append(float(value))
        index += 1
    return found


def numberless_lead(lead):
    """The lead, unless it states a number in digits or words.

    Matching a lead's numbers against the facts is not enough: "three groups"
    would pass whenever any fact mentions a 3, such as a group size.
    """
    lead = lead.strip()
    return "" if _numbers(lead) else lead


def default_fact_ids(facts, limit=4):
    """Findings first; each step's quality is already shown beside the answer."""
    chosen = [fact["id"] for fact in facts if fact["kind"] != "quality"][:limit]
    return chosen or [facts[0]["id"]]


def suggested_questions(saved, facts=()):
    """Follow-ups that the result does not already answer.

    A suggestion the saved result can satisfy carries a checked action, so
    choosing it changes the view or cites facts without another model call.
    The others are sent to the planner as ordinary questions.
    """
    ports, operations = [], set()
    for step in saved.get("steps", {}).values():
        result = step.get("result") or {}
        operations.add(result.get("operation"))
        ports.extend(result.get("ports", {}).values())
    # Empty count-only collections cannot support questions about their members.
    kinds = {port.get("type") for port in ports if port.get("value") or port.get("type") == "scalar"}
    noun = "clique" if operations & CLIQUE_OPERATIONS else "group"
    scored = bool(kinds & {"vertex_scores", "edge_scores"})
    suggestions = []
    if kinds & {"vertex_groups", "vertex_partition"}:
        suggestions.append({
            "text": f"Show the largest {noun}.",
            "action": {"intent": "view", "view": {"kind": "show_group", "group": "largest"}},
        })
        if not scored:
            suggestions.append({"text": f"Who connects the different {noun}s?", "action": None})
    if scored:
        top = top_ranked(saved)
        if top:
            suggestions.append({
                "text": "Highlight the top-ranked entities on the graph.",
                "action": {"intent": "view", "view": {"kind": "highlight", "vertices": top}},
            })
    if "path_set" in kinds:
        suggestions.append({"text": "Explain the returned paths.", "action": None})
    if not suggestions:
        suggestions.append({"text": "Explain this result.", "action": None})
    scope = [fact["id"] for fact in facts if fact["kind"] in ("quality", "scope")]
    incomplete = any(port.get("complete") is not True for port in ports)
    suggestions.append({
        "text": "Is this result complete?" if incomplete else "What guarantees does this calculation provide?",
        "action": {"intent": "explain", "fact_ids": scope[:6]} if scope else None,
    })
    return suggestions[:3]


def top_ranked(saved, limit=5):
    """The highest positive vertex scores in the latest scored step."""
    for step_id in reversed(list(saved.get("order", saved.get("steps", {})))):
        result = (saved.get("steps", {}).get(step_id) or {}).get("result") or {}
        for port in (result.get("ports") or {}).values():
            if port.get("type") != "vertex_scores" or not isinstance(port.get("value"), list):
                continue
            field = port.get("score_field", "score")
            rows = [
                row for row in port["value"]
                if isinstance(row, dict) and "vertex" in row
                and isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)
                and row[field] > 0
            ]
            rows.sort(key=lambda row: -row[field])
            return [row["vertex"] for row in rows[:limit]]
    return []


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:.4g}"


def _names(ids, labels, limit=5):
    names = [labels.get(json.dumps(item, sort_keys=True), str(item)) for item in ids]
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit:,} more" if len(names) > limit else "")


def _title(name):
    return name.replace("_", " ")


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _singular(noun):
    if noun == "vertices":
        return "vertex"
    if noun.endswith("ies"):
        return noun[:-3] + "y"
    if noun.endswith(("ches", "shes", "xes", "sses")):
        return noun[:-2]
    return noun[:-1] if noun.endswith("s") else noun


def _count(number, noun):
    """A count with the matching noun form, such as 1 group or 2 groups."""
    return f"{number:,} {_singular(noun) if number == 1 else noun}"


def build_facts(saved, titles, labels):
    """Plain statements of what each completed step found, most important first.

    Each statement is labelled with its calculation's title, because titles are
    descriptions ("Divide a network into communities"), not sentence subjects.
    """
    facts = []

    def add(kind, step, statement):
        facts.append(
            {
                "id": f"f{len(facts) + 1}",
                "kind": kind,
                "step": step,
                "statement": statement,
            }
        )

    for step_id in saved.get("order", saved.get("steps", {})):
        step = saved.get("steps", {}).get(step_id, {})
        result = step.get("result") or {}
        if step.get("status") != "completed" or not result:
            continue
        method = titles.get(result.get("operation"), result.get("operation") or step_id)
        ports = result.get("ports") or {}
        # A partition and its group list describe the same grouping: state it once.
        partitioned = next(
            (
                len(port["value"])
                for port in ports.values()
                if port.get("type") == "vertex_partition" and isinstance(port.get("value"), list)
            ),
            None,
        )
        listed = any(
            port.get("type") == "vertex_groups" and port.get("value")
            for port in ports.values()
        )
        for name, port in ports.items():
            kind, value = port.get("type"), port.get("value")
            what = _title(name)
            if kind == "scalar":
                add("value", step_id, f"{method}: {what} is {_number(value)}.")
            elif kind == "vertex_groups" and isinstance(value, list):
                groups = sorted(
                    (g.get("vertices", []) for g in value if isinstance(g, dict)),
                    key=len,
                    reverse=True,
                )
                if not groups:
                    if port.get("complete") is False:
                        add("scope", step_id, f"{method}: did not retain {what} for inspection; an empty retained collection does not establish a zero count.")
                    else:
                        add("value", step_id, f"{method}: found no {what}.")
                    continue
                retained = port.get("complete") is False
                found = f"{method}: {'retained' if retained else 'found'} {_count(len(groups), what)}"
                if partitioned is not None:
                    found += f" covering {_count(partitioned, 'vertices')}"
                sizes = [len(group) for group in groups]
                names = _names(groups[0], labels)
                if len(groups) == 1:
                    add("groups", step_id, f"{found}, with {_count(sizes[0], 'members')}: {names}.")
                elif len(groups) <= 5:
                    add(
                        "groups",
                        step_id,
                        f"{found}, with {_join([f'{size:,}' for size in sizes])} members; "
                        f"the largest{' retained' if retained else ''}: {names}.",
                    )
                else:
                    add("groups", step_id, f"{found}; the largest has {_count(sizes[0], 'members')}: {names}.")
                    add(
                        "sizes",
                        step_id,
                        f"{method}: the five largest {what} have "
                        f"{_join([f'{size:,}' for size in sizes[:5]])} members.",
                    )
            elif kind == "vertex_partition" and isinstance(value, list):
                if listed:
                    continue
                parts = {}
                for row in value:
                    if isinstance(row, dict):
                        parts.setdefault(json.dumps(row.get("part")), []).append(
                            row.get("vertex")
                        )
                largest = max(parts.values(), key=len, default=[])
                add(
                    "groups",
                    step_id,
                    f"{method}: split {_count(len(value), 'vertices')} into "
                    f"{_count(len(parts), 'groups')}; the largest has "
                    f"{len(largest):,}: {_names(largest, labels)}.",
                )
            elif kind in ("vertex_scores", "edge_scores") and isinstance(value, list):
                field = port.get("score_field", "score")
                noun = "vertices" if kind == "vertex_scores" else "connections"
                ranked = sorted(
                    (
                        row
                        for row in value
                        if isinstance(row, dict)
                        and isinstance(row.get(field), (int, float))
                        and not isinstance(row.get(field), bool)
                    ),
                    key=lambda row: -row[field],
                )
                if not ranked:
                    continue
                if ranked[0][field] == ranked[-1][field]:
                    add(
                        "ranking",
                        step_id,
                        f"{method}: all {_count(len(ranked), noun)} have {_title(field)} "
                        f"{_number(ranked[0][field])}.",
                    )
                    continue
                # Zero is a floor here (e.g. no shortest paths pass through), not a rank.
                floor = ranked[-1][field] == 0
                shown = [row for row in ranked if not (floor and row[field] == 0)][:5]
                statement = f"{method}: highest {_title(field)} — " + _join([
                    f"{_names([row.get('vertex', row.get('edge'))], labels)} ({_number(row[field])})"
                    for row in shown
                ])
                zeros = sum(row[field] == 0 for row in ranked) if floor else 0
                add(
                    "ranking",
                    step_id,
                    statement
                    + (f"; {zeros:,} other {_singular(noun) if zeros == 1 else noun} scored 0." if zeros else "."),
                )
            elif kind == "vertex_set" and isinstance(value, list):
                add(
                    "members",
                    step_id,
                    f"{method}: selected {_count(len(value), 'vertices')}: {_names(value, labels)}.",
                )
            elif kind == "graph" and isinstance(value, dict):
                add(
                    "value",
                    step_id,
                    f"{method}: produced a graph with {_count(len(value.get('vertices', [])), 'vertices')} "
                    f"and {_count(len(value.get('edges', [])), 'connections')}.",
                )
            elif isinstance(value, list):
                add("value", step_id, f"{method}: returned {_count(len(value), what)}.")
        quality = QUALITY.get(result.get("quality"), result.get("quality"))
        if quality:
            complete = bool(result.get("complete"))
            add(
                "quality" if complete else "scope",
                step_id,
                f"{method}: {quality}" + ("." if complete else "; its output is incomplete."),
            )
    return facts[:FACT_LIMIT]


def choice_schema(facts):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["lead", "fact_ids"],
        "properties": {
            "lead": {"type": "string", "maxLength": 300},
            "fact_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {"enum": [fact["id"] for fact in facts]},
            },
        },
    }


async def compose(settings, question, facts, *, on_call=None):
    """The model's choice of facts and a lead sentence grounded in them.

    ``on_call`` receives the exact request and raw response for training capture.
    """
    from .accounts import model_post

    schema = choice_schema(facts)
    request = {
        "model": settings.analytics_answer_model or settings.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": json.dumps({"question": question, "facts": facts}),
            },
        ],
        "temperature": 0,
        "seed": 0,
        # Choosing from computed facts needs no deliberation, and reasoning
        # tokens were nearly all of this call's time.
        "reasoning_effort": "none",
        "max_completion_tokens": 1024,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "AnalyticsAnswer",
                "strict": True,
                "schema": schema,
            },
        },
    }
    started, body, answer, outcome, error = time.monotonic(), None, None, "interrupted", None
    try:
        async with httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=httpx.Timeout(90, connect=5),
        ) as client:
            response = await model_post(client, "/chat/completions", json=request)
            response.raise_for_status()
            body = response.json()
            data = json.loads(body["choices"][0]["message"]["content"])
        jsonschema.Draft202012Validator(schema).validate(data)
        # Figures must come from the facts, never from the model's wording.
        answer = {
            "lead": numberless_lead(data["lead"]),
            "fact_ids": list(dict.fromkeys(data["fact_ids"])),
        }
        outcome = "ok"
        return answer
    except Exception as exc:
        outcome, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        if on_call:
            on_call(
                request=request, response=body, output=answer, outcome=outcome,
                seconds=time.monotonic() - started, error=error,
                target_schema=schema, output_schema=schema,
            )
