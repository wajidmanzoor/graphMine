"""Finite calculation choices, measured match scores, and editable card contracts.

Models select operation/variant pairs built here. They never supply parameter
values. Confidence thresholds are loaded only from a matching calibration.
"""

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

import jsonschema

from .analytics_eligibility import eligible, requested_preferences, score_hints
from .analytics_lane_choices import explicit_parameters

SAMPLES = 5
TEMPERATURE = 0.7
SCORE_VERSION = 2
KEY_PARAMETERS = {"mode", "objective", "solution_quality", "direction_mode", "weight_mode", "capacity_mode"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def catalog_signature(cards):
    return digest(sorted(({**{key: card.get(key) for key in ("id", "parameters", "requirements", "quality")},
                           "quality_guarantees": quality_guarantees(card)} for card in cards), key=lambda row: row["id"]))


def defaults(card, values=None):
    result = {name: deepcopy(spec["default"]) for name, spec in card["parameters"].items()
              if "default" in spec and (spec["default"] is not None or spec.get("nullable"))}
    result.update(deepcopy(values or {}))
    return result


def effective_quality(card, parameters):
    """A native contract's fixed guarantee can exceed the requested quality.

    Parameter/backend-dependent contracts retain their actual quality choices;
    accepting an approximate request does not imply an approximation solver.
    """
    quality = card.get("quality", "unspecified")
    if quality in {"parameter_dependent", "backend_dependent"}:
        return defaults(card, parameters).get("solution_quality", quality)
    return quality


def quality_guarantees(card):
    spec = card.get("parameters", {}).get("solution_quality", {})
    return {"default": effective_quality(card, {}),
            "by_request": {value: effective_quality(card, {"solution_quality": value})
                           for value in spec.get("choices", [])},
            "canonical_requests": {value: effective_parameters(card, {"solution_quality": value})["solution_quality"]
                                   for value in spec.get("choices", [])}}


def effective_parameters(card, parameters):
    values = defaults(card, parameters)
    # The native catalog's fixed exact guarantee applies to every admitted
    # profile. Keep the original request for execution and saved-choice replay.
    if card.get("quality") == "exact" and values.get("solution_quality") in ("exact", "approximate"):
        values["solution_quality"] = "exact"
    return values


def semantic_key(candidate, cards):
    by_id = {card["id"]: card for card in cards}
    operations = candidate.get("operations", [candidate["operation"]])
    parameters = candidate["parameters"]
    return digest([candidate["input"], [[op, effective_parameters(by_id[op],
        parameters if len(operations) == 1 else parameters.get(op, {}))] for op in operations]])


def candidate_menu(cards, profiles, question, entities=(), *, selected=(), supplied=None, alias=None):
    """One default and meaningful enum alternatives per eligible operation/input.

    Keep literal values private. The prompt receives only opaque keys and safe
    enum descriptions; vertex IDs and compound native arguments never enter it.
    """
    requested = requested_preferences(question)
    result, seen = [], set()
    for card in cards:
        for key, profile in profiles.items():
            if alias is not None and key != alias:
                continue
            if not eligible(card, profile, requested)[0]:
                continue
            stated = explicit_parameters(card, question, entities, key)
            if selected and card["id"] == selected[0]:
                selected_values = (supplied or {}).get(selected[0])
                stated.update(selected_values if isinstance(selected_values, dict) else supplied or {})
            values = defaults(card, stated)
            variants = [values]
            for name, spec in card["parameters"].items():
                if name in KEY_PARAMETERS and name not in stated:
                    variants.extend({**values, name: value} for value in spec.get("choices", [])
                                    if value != values.get(name) and not (requested["exact"] and name == "solution_quality" and value != "exact"))
            if requested["exact"] and "exact" in card["parameters"].get("solution_quality", {}).get("choices", []):
                variants = [{**value, "solution_quality": "exact"} for value in variants]
            for value in variants:
                candidate = {"operation": card["id"], "input": key, "parameters": value}
                meaning = semantic_key(candidate, [card])
                identity = digest([card["id"], key, value])
                if meaning in seen:
                    continue
                seen.add(meaning)
                missing = [name for name, spec in card["parameters"].items()
                           if spec.get("required") and name not in value and spec.get("default") is None]
                result.append({"id": "choice_" + identity[:16], "semantic_key": meaning, "operation": card["id"], "input": key,
                               "parameters": value, "missing": missing,
                               "hints": score_hints(card, profile, requested)})
    # Preserve a routed multi-step objective as a single selectable choice.
    if len(selected) > 1:
        by_id = {card["id"]: card for card in cards}
        available = list(profiles.values())
        chain_ok = True
        for op in selected:
            if op not in by_id or not any(eligible(by_id[op], profile, requested)[0] for profile in available):
                chain_ok = False
                break
            available.extend({"input_kind": port["type"], "unknown_data": True}
                             for port in by_id[op].get("output_ports", {}).values())
        if chain_ok:
            first = next((row for row in result if row["operation"] == selected[0]), None)
            if first:
                values = {op: defaults(by_id[op], explicit_parameters(by_id[op], question, entities, first["input"])) for op in selected}
                if supplied:
                    if not any(isinstance(supplied.get(op), dict) for op in selected):
                        values[selected[0]].update(supplied)
                    for op in selected:
                        if isinstance(supplied.get(op), dict):
                            values[op].update(supplied[op])
                chain = {**first, "id": "choice_" + digest([selected, values, first["input"]])[:16],
                               "operations": list(selected), "parameters": values,
                               "missing": [f"{op}.{name}" for op in selected for name, spec in by_id[op]["parameters"].items()
                                           if spec.get("required") and name not in values[op] and spec.get("default") is None]}
                chain["semantic_key"] = semantic_key(chain, cards)
                result.append(chain)
    return result


def sampling_contract(menu, cards):
    by_id = {card["id"]: card for card in cards}
    variants, offered = [], []
    for operation in dict.fromkeys(row["operation"] for row in menu):
        choices = [row for row in menu if row["operation"] == operation]
        variants.append({"type": "object", "additionalProperties": False,
            "properties": {"operation": {"const": operation},
                           "parameter_choice": {"enum": [row["id"] for row in choices]},
                           "interpretation": {"type": "string", "minLength": 1, "maxLength": 240}},
            "required": ["operation", "parameter_choice", "interpretation"]})
        card = by_id[operation]
        def description(row):
            values = row["parameters"]
            if row.get("operations"):
                return {"id": row["id"], "operations": row["operations"], "missing": row["missing"]}
            return {"id": row["id"], "input": row["input"], "missing": row["missing"],
                    "settings": {name: value for name, value in values.items() if name in KEY_PARAMETERS},
                    "guarantee": effective_quality(card, values)}
        offered.append({"operation": operation, "title": card["title"], "description": card["description"],
                        "quality": card["quality"], "choices": [description(row) for row in choices]})
    return {"oneOf": variants}, offered


def operation_logprob(choice):
    """Log probability of the actual operation value, excluding other prose.

    Match byte offsets so split tokens and non-ASCII text do not shift the span.
    A missing/misaligned stream is unknown, never an invented probability.
    """
    content = choice.get("message", {}).get("content", "")
    match = re.search(r'"operation"\s*:\s*"([^"\\]+)"', content)
    rows = (choice.get("logprobs") or {}).get("content")
    if not match or not isinstance(rows, list):
        return None
    start, end = (len(content[:index].encode()) for index in match.span(1))
    chunks, spans, cursor = [], [], 0
    for row in rows:
        try:
            chunk = bytes(row["bytes"]) if row.get("bytes") is not None else row["token"].encode()
        except (KeyError, ValueError, TypeError, AttributeError):
            return None
        if cursor < end and cursor + len(chunk) > start:
            probability = row.get("logprob")
            if not isinstance(probability, (int, float)) or isinstance(probability, bool) or not math.isfinite(probability) or probability > 0:
                return None
            spans.append(probability)
        cursor += len(chunk)
        chunks.append(chunk)
    encoded = b"".join(chunks)
    # vLLM includes the model's terminal token in logprobs but removes it from
    # message.content. Only known, trailing stop markers may be discarded.
    suffix = encoded[len(content.encode()):] if encoded.startswith(content.encode()) else None
    if suffix not in (b"", b"<|im_end|>", b"<|eot_id|>", b"</s>") or not spans:
        return None
    return {"sum": sum(spans), "tokens": len(spans), "mean": sum(spans) / len(spans)}


def match_score(votes, logprobs, missing):
    share = votes / SAMPLES
    likelihood = math.exp(sum(row["mean"] for row in logprobs) / len(logprobs)) if logprobs else 0
    # Likelihood only contributes to choices actually sampled. Unsampled
    # alternatives never receive confidence from related-operation heuristics.
    return round(max(0, min(1, .65 * share + .35 * likelihood - .15 * min(missing, 4))), 6)


def load_calibration(settings, cards):
    path = Path(settings.repository_root) / "catalog/option_calibration.json"
    if not path.exists():
        return None
    calibration = json.loads(path.read_text())
    if (calibration.get("score_version") != SCORE_VERSION or calibration.get("samples") != SAMPLES
            or calibration.get("temperature") != TEMPERATURE
            or calibration.get("model") != (settings.analytics_router_model or settings.llm_model)
            or calibration.get("server") != (settings.analytics_router_base_url or settings.llm_base_url)
            or calibration.get("catalog_sha256") != catalog_signature(cards)):
        return None
    high = calibration.get("high", {})
    if high.get("count", 0) < 5 or high.get("precision", 0) < .85:
        return None
    return calibration


def rank_candidates(menu, samples, calibration=None):
    by_id, votes = {row["id"]: row for row in menu}, defaultdict(list)
    for sample in samples:
        decision = sample.get("decision", {})
        candidate = by_id.get(decision.get("parameter_choice"))
        if candidate is None or candidate["operation"] != decision.get("operation"):
            continue
        votes[candidate["id"]].append(sample)
    ranked = []
    for candidate in menu:
        chosen = votes[candidate["id"]]
        probabilities = [row["operation_logprob"] for row in chosen if row.get("operation_logprob") is not None]
        score = match_score(len(chosen), probabilities, len(candidate["missing"]))
        level = "Medium" if score >= .35 and len(chosen) >= 2 else "Low"
        if (calibration and chosen and len(probabilities) == len(chosen) and not candidate["missing"]
                and score >= calibration["high"]["threshold"]):
            level = "High"
        ranked.append({**deepcopy(candidate), "score": score, "match": level,
            "interpretation": chosen[0]["decision"]["interpretation"] if chosen else None,
            "match_evidence": {"votes": len(chosen), "samples": SAMPLES, "operation_logprobs": probabilities,
                               "missing_parameters": candidate["missing"], "calibrated": bool(calibration)}})
    ranked.sort(key=lambda row: (-row["score"], -row["hints"]["score"], row["id"]))
    if ranked:
        from .analytics_lane_choices import ALTERNATIVES
        alternate = ALTERNATIVES.get(ranked[0]["operation"], (None, {}))[0]
        ranked.sort(key=lambda row: (-row["score"], row["operation"] != alternate, -row["hints"]["score"], row["id"]))
    return ranked


def distinct(first, second):
    return first["semantic_key"] != second["semantic_key"]


def parameter_fields(cards, candidate):
    from .analytics_planning import parameter_schema
    by_id = {card["id"]: card for card in cards}
    operations = candidate.get("operations", [candidate["operation"]])
    result = []
    for operation in operations:
        values = candidate["parameters"] if len(operations) == 1 else candidate["parameters"].get(operation, {})
        for name, spec in by_id[operation]["parameters"].items():
            description = spec.get("description", "")
            if name == "solution_quality" and by_id[operation].get("quality") == "exact":
                description = "This implementation returns an exact result for every supported quality request."
            result.append({"operation": operation, "name": name, "label": "requested solution quality" if name == "solution_quality" else name.replace("_", " "),
                "schema": parameter_schema(spec), "required": spec.get("required", False),
                "kind": spec["kind"], "has_value": name in values, "value": deepcopy(values.get(name)),
                "default": deepcopy(spec.get("default")), "description": description,
                "application_filled": name in {"left_partition", "right_partition"} and name not in values})
    return result


def validate_edits(choice, parameters):
    """Accept user edits only inside the saved card's native parameter schema."""
    fields = choice.get("parameter_fields")
    if fields is None:  # Old saved cards remain immutable.
        if parameters != choice["parameters"]:
            raise ValueError("The submitted parameters do not match the saved choice.")
        return
    operations = choice["operations"]
    groups = {operations[0]: parameters} if len(operations) == 1 else parameters
    if set(groups) - set(operations):
        raise ValueError("Parameters refer to an operation outside the saved choice.")
    for operation, values in groups.items():
        if not isinstance(values, dict):
            raise ValueError("Each operation's parameters must be an object.")
        specs = {field["name"]: field["schema"] for field in fields if field["operation"] == operation}
        schema = {"type": "object", "properties": specs, "additionalProperties": False}
        try:
            jsonschema.Draft202012Validator(schema).validate(values)
        except jsonschema.ValidationError as error:
            raise ValueError("Invalid edited parameter: " + error.message) from error


def cost_hint(operation, profile):
    n, m = profile.get("vertices_count", 0), profile.get("edges_count", 0)
    enumeration = {"maximal-cliques", "maximum-clique", "maximal-bicliques", "k-cliques", "quasi-cliques", "subgraph-isomorphism", "frequent-subgraphs"}
    repeated = {"betweenness-centrality", "closeness-centrality", "all-pairs-shortest-paths", "simrank", "graph-edit-distance"}
    if operation in enumeration:
        return "Potentially expensive; exact search or enumeration can grow rapidly with graph density."
    if operation in repeated:
        return "Higher cost; compares many vertex pairs or repeats graph traversals."
    return f"Processes {n:,} vertices and {m:,} connections; iteration and output limits affect runtime."


def make_cards(ranked, cards, profiles, question):
    if not ranked:
        return []
    supported = [row for row in ranked if row["match"] in {"Medium", "High"}
                 and row["match_evidence"]["votes"] > 0]
    # Retain one low candidate only so the lane can ask its existing open
    # clarification when none is supported; it is never shown as a choice.
    first = supported[0] if supported else ranked[0]
    second = next((row for row in supported[1:] if distinct(first, row)), None)
    by_id, result = {card["id"]: card for card in cards}, []
    for index, candidate in enumerate((first, second) if second else (first,)):
        card = by_id[candidate["operation"]]
        other = by_id[(second if index == 0 and second else first)["operation"]]
        operations = candidate.get("operations", [candidate["operation"]])
        values = candidate["parameters"] if len(operations) == 1 else candidate["parameters"].get(operations[0], {})
        qualities = {op: effective_quality(by_id[op], values if len(operations) == 1 else candidate["parameters"].get(op, {})) for op in operations}
        quality = next(iter(qualities.values())) if len(set(qualities.values())) == 1 else "mixed"
        result.append({"id": f"option_{index + 1}", "operations": operations,
            "parameters": candidate["parameters"], "input": candidate["input"], "title": " → ".join(by_id[op]["title"] for op in operations),
            "quality": quality, "operation_qualities": qualities,
            "quality_guarantees": {op: quality_guarantees(by_id[op]) for op in operations},
            "description": " ".join(by_id[op]["description"] for op in operations), "rank": index + 1,
            "interpretation": candidate["interpretation"] or f"Another way to explore “{question[:180]}”: {card['title']}",
            "match": candidate["match"], "score": candidate["score"], "match_evidence": candidate["match_evidence"],
            "cost_hint": " ".join(dict.fromkeys(cost_hint(op, profiles[candidate["input"]]) for op in operations)),
            "difference": ("Matches your question." if second is None else
                           f"{card['title']}: {card['description']} Compared with {other['title']}."
                           if card["id"] != other["id"] else f"Uses different settings: {json.dumps({key: value for key, value in values.items() if key in KEY_PARAMETERS})}."),
            "parameter_fields": parameter_fields(cards, candidate),
            "preselected": index == 0 and candidate["match"] == "High" and (second is None or first["score"] - second["score"] >= .25)})
    return result
