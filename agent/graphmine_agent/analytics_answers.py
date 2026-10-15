"""Answers in chat: facts computed from the result, chosen and introduced by a model.

The model never writes a number. It picks which facts answer the question and
adds one lead sentence without digits; every figure comes from the saved result.
"""

from __future__ import annotations

import json
import re

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
    "sentence that introduces them. The lead must not contain any digits or "
    "numbers, and must not claim anything the facts do not state, including "
    "causes or real-world meaning. Return JSON matching the supplied schema."
)


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


def build_facts(saved, titles, labels):
    """Plain statements of what each completed step found, most important first."""
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
        for name, port in (result.get("ports") or {}).items():
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
                    add("value", step_id, f"{method} found no {what}.")
                    continue
                add(
                    "groups",
                    step_id,
                    f"{method} found {len(groups):,} {what}; the largest has "
                    f"{len(groups[0]):,} members: {_names(groups[0], labels)}.",
                )
                if len(groups) > 1:
                    add(
                        "sizes",
                        step_id,
                        f"Sizes of the largest {what}: "
                        + ", ".join(f"{len(g):,}" for g in groups[:5])
                        + ".",
                    )
            elif kind == "vertex_partition" and isinstance(value, list):
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
                    f"{method} split {len(value):,} vertices into {len(parts):,} "
                    f"{what}; the largest has {len(largest):,}: {_names(largest, labels)}.",
                )
            elif kind in ("vertex_scores", "edge_scores") and isinstance(value, list):
                field = port.get("score_field", "score")
                ranked = sorted(
                    (
                        row
                        for row in value
                        if isinstance(row, dict)
                        and isinstance(row.get(field), (int, float))
                        and not isinstance(row.get(field), bool)
                    ),
                    key=lambda row: -row[field],
                )[:5]
                if ranked:
                    entries = ", ".join(
                        f"{_names([row.get('vertex', row.get('edge'))], labels)} "
                        f"({_number(row[field])})"
                        for row in ranked
                    )
                    add(
                        "ranking",
                        step_id,
                        f"Highest {_title(field)} from {method}: {entries}.",
                    )
            elif kind == "vertex_set" and isinstance(value, list):
                add(
                    "members",
                    step_id,
                    f"{method} selected {len(value):,} vertices: {_names(value, labels)}.",
                )
            elif kind == "graph" and isinstance(value, dict):
                add(
                    "value",
                    step_id,
                    f"{method} produced a graph with {len(value.get('vertices', [])):,} "
                    f"vertices and {len(value.get('edges', [])):,} connections.",
                )
            elif isinstance(value, list):
                add("value", step_id, f"{method} returned {len(value):,} {what}.")
        quality = QUALITY.get(result.get("quality"), result.get("quality"))
        if quality:
            add(
                "scope",
                step_id,
                f"{method} is {quality}"
                + ("." if result.get("complete") else "; its output is incomplete."),
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


async def compose(settings, question, facts):
    """The model's choice of facts and a lead sentence that cannot carry numbers."""
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
        "reasoning_effort": "low",
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
    if settings.analytics_thinking_token_budget is not None:
        request["thinking_token_budget"] = 256
    async with httpx.AsyncClient(
        base_url=settings.llm_base_url,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        timeout=httpx.Timeout(90, connect=5),
    ) as client:
        response = await model_post(client, "/chat/completions", json=request)
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
    jsonschema.Draft202012Validator(schema).validate(data)
    lead = data["lead"].strip()
    # Figures must come from the facts, never from the model's wording.
    return {
        "lead": "" if re.search(r"\d", lead) else lead,
        "fact_ids": list(dict.fromkeys(data["fact_ids"])),
    }
