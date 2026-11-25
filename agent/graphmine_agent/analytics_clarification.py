"""Code-owned gaps and durable, single-question continuations.

The model can phrase a question or select an opaque offered choice. Values,
entity identities, input bindings and snapshot edits always come from code or
an explicitly typed, checked answer.
"""

import asyncio
from collections import defaultdict
from copy import deepcopy
import json
import re
from uuid import uuid4

import jsonschema

from .analytics import AnalyticsError, InputReference
from .analytics_modes import saved_mode
from .analytics_bipartite import CONVERT_CHOICE, KEEP_CHOICE
from .analytics_context import matched_entities
from .graph_context import display_name, fields, identity, infer_bipartition
from .models import FileRole


VERTEX_ARRAYS = {"vertices", "sources", "seeds", "start_vertices", "seed_vertices", "required_vertices", "origins", "destinations"}
GRAPH_ARGUMENTS = {"query_graph", "other_graph"}


def normalized(text):
    return re.sub(r"\s+", " ", str(text).casefold()).strip(" .?!")


def gap(kind, message, choices=(), **details):
    return {"kind": kind, "message": message, "choices": [
        {**choice, "id": f"choice_{index + 1}"} for index, choice in enumerate(choices)
    ], **details}


def vertex_choices(inputs, aliases, candidates=None):
    allowed = None if candidates is None else {(row["input"], identity(row["id"])) for row in candidates}
    result = []
    for alias in aliases:
        for vertex in inputs[alias]["data"].get("vertices", []):
            if allowed is not None and (alias, identity(vertex["id"])) not in allowed:
                continue
            # The ID and type disambiguate duplicate display names. They are
            # read from the full snapshot and never supplied by the model.
            label = f"{display_name(vertex)} · {vertex.get('type', 'vertex')} · ID {json.dumps(vertex['id'], ensure_ascii=False)} · {alias}"
            result.append({"label": label, "value": vertex["id"], "alias": alias,
                           "name": display_name(vertex), "action": "vertex"})
    return result


def parameter_gap(card, name, inputs, aliases, values, *, error=None):
    spec = card["parameters"][name]
    choices = [{"label": str(value).replace("_", " "), "value": value, "action": "parameter"}
               for value in spec.get("choices", [])]
    if spec["kind"] == "boolean":
        choices = [{"label": "Yes", "value": True, "action": "parameter"},
                   {"label": "No", "value": False, "action": "parameter"}]
    if spec["kind"] == "vertex_id" or name in VERTEX_ARRAYS:
        choices = vertex_choices(inputs, aliases)
        # A flow's endpoints must differ; do not offer an already chosen peer.
        if name in {"source", "sink"}:
            peer = "source" if name == "sink" else "sink"
            choices = [row for row in choices if peer not in values or identity(row["value"]) != identity(values[peer])]
    if name in GRAPH_ARGUMENTS:
        choices = [{"label": f"Use {alias} as the {name.replace('_', ' ')}.", "alias": alias, "action": "binding"}
                   for alias, row in inputs.items() if row["kind"] == "graph" and alias not in aliases]
        choices.append({"label": "Use the newly selected input.", "action": "current_input"})
    message = f"What value should I use for {name.replace('_', ' ')}?"
    if name in GRAPH_ARGUMENTS:
        message = f"Which separate input should supply the {name.replace('_', ' ')}?"
    return gap("parameter", message, choices, parameter=name, spec=spec,
               key=f"parameter:{card['id']}:{name}", **({"validation_error": error} if error else {}))


def ambiguous_entities(entities, answered=()):
    groups = defaultdict(list)
    for row in entities:
        groups[normalized(row["matched"])].append(row)
    for name, rows in groups.items():
        if len({(row['input'], identity(row['id'])) for row in rows}) > 1 and f"entity:{name}" not in answered:
            return name, rows
    return None


def endpoint_scope(card, question):
    """Null means all vertices for this contract, not unknown endpoints.

    An explicitly scoped path request must supply its endpoints. Unqualified
    problem requests and explicit all-pairs requests retain native defaults.
    """
    if card["id"] != "many-source-shortest-paths":
        return ()
    text = normalized(question)
    all_vertices = r"\b(?:all|every|each)\s+(?:vertices|vertex|nodes?|accounts?|pairs?|businesses|users?)\b"
    directed = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)", text)
    if directed:
        return tuple(name for name, segment in zip(("origins", "destinations"), directed.groups())
                     if not re.search(all_vertices, segment))
    if re.search(r"\ball[ -]pairs\b|" + all_vertices, text):
        return ()
    if re.search(r"\bbetween\b", text):
        return ("origins", "destinations")
    return ()


def detect_gap(card, inputs, values, alias, entities, answered=(), bindings=None, *, question=""):
    """Return the first answer-changing gap in the specified priority order."""
    aliases = [alias] if alias else [key for key, row in inputs.items() if row["kind"] == card["input_kind"]]
    bindings = bindings or {}
    scoped = endpoint_scope(card, question)
    # Required arguments take priority. Input-dependent values wait for an
    # input when no candidate snapshot exists at all.
    for name, spec in card["parameters"].items():
        required = spec.get("required") and spec.get("default") is None and name not in values
        required = required or name in scoped and not values.get(name)
        if not required or name in bindings:
            continue
        if name in GRAPH_ARGUMENTS and alias and len([key for key, row in inputs.items() if row["kind"] == "graph" and key != alias]) == 1:
            continue
        if aliases or spec["kind"] not in {"vertex_id", "array"}:
            return parameter_gap(card, name, inputs, aliases, values)
    ambiguous = ambiguous_entities(entities, answered)
    if ambiguous:
        name, rows = ambiguous
        return gap("entity", f"Which {rows[0]['matched']} do you mean?",
                   vertex_choices(inputs, list(inputs), rows), key=f"entity:{name}", matched=name)
    if alias is None:
        choices = [{"label": f"Use {key}.", "alias": key, "action": "input"} for key in aliases]
        choices.append({"label": "Use the newly selected input.", "action": "current_input"})
        return gap("input", f"Which {card['input_kind'].replace('_', ' ')} input should this calculation use?", choices, key="input")
    if "bipartite_side" in card["requirements"]["needs"]:
        graph = inputs[alias]["data"]
        if infer_bipartition(graph) is None and not all(name in values for name in ("left_partition", "right_partition")):
            return gap("sides", "Which records belong on each side? Type two vertex types, or provide left_partition and right_partition as JSON arrays. You can also select a snapshot with valid sides.",
                       [{"label": "Use the newly selected input.", "action": "current_input"}], key="sides")
    return None


def checked_value(spec, value):
    kind = spec["kind"]
    schema = {"type": ["string", "integer"] if kind == "vertex_id" else kind}
    schema.update({key: spec[key] for key in ("minimum", "maximum") if key in spec})
    schema.update(spec.get("json_schema", {}))
    if spec.get("choices"):
        schema["enum"] = spec["choices"]
    if value is None and spec.get("nullable"):
        return value
    jsonschema.Draft202012Validator(schema).validate(value)
    if kind == "integer" and type(value) is float and value.is_integer():
        value = int(value)
    # JSON Schema treats NaN as a number; native JSON cannot carry it.
    json.dumps(value, allow_nan=False)
    return value


def explicit_problem(question, cards):
    """Recognize an explicitly named contract, including removed problems.

    This only repairs a routing *gap/refusal*. It never overrides reply/view or
    interprets vague vocabulary (the draft vague_terms catalog is not active).
    """
    text = normalized(question).replace("-", " ")
    found = [card["id"] for card in cards if any(
        re.search(r"(?<!\w)" + re.escape(normalized(name).replace("-", " ")) + r"(?!\w)", text)
        for name in (card["id"], card["title"]))]
    return found if len(found) == 1 else []


def validator_gap(error, card, inputs, alias, values):
    """Native validation messages are contracts, not model repair suggestions."""
    message = str(error)
    if error.status >= 500 or error.code.startswith("planner_"):
        return None
    if "Source and sink must be distinct" in message and "sink" in card["parameters"]:
        return parameter_gap(card, "sink", inputs, [alias], values, error=message)
    for name in card["parameters"]:
        if re.search(r"(?:Missing required parameter:\s*|Missing\s+)" + re.escape(name) + r"\b|\b" + re.escape(name) + r"\s+(?:must|is below|exceeds|has an unsupported|requires)\b", message, re.I):
            return parameter_gap(card, name, inputs, [alias] if alias else [], values, error=message)
    if re.search(r"unknown.*vertex|vertex.*not.*(exist|found)", message, re.I) and alias in inputs:
        ids = {identity(row['id']) for row in inputs[alias]['data'].get('vertices', [])}
        for name, spec in card['parameters'].items():
            if name in values and spec['kind'] == 'vertex_id' and identity(values[name]) not in ids:
                return parameter_gap(card, name, inputs, [alias], values, error=message)
    if re.search(r"bipartit|partition|attributes\.side", message, re.I):
        return gap("sides", "Which valid sides should this calculation use? Supply left_partition and right_partition as JSON arrays, or select a snapshot with sides.",
                   [{"label": "Use the newly selected input.", "action": "current_input"}], key="sides", validation_error=message)
    if re.search(r"directed|undirected|weight|timestamp|query graph|input kind", message, re.I):
        return gap("input", message + " Which snapshot should this calculation use?",
                   [{"label": "Use the newly selected input.", "action": "current_input"}], key="input", validation_error=message)
    return None


class Clarifications:
    async def _planned_question(self, body, plan, cards, inputs, entities, context=None, error=None):
        """Keep a selected DAG intact when a later step needs an answer."""
        by_id = {card["id"]: card for card in cards}
        for step in plan["steps"]:
            card, alias = by_id[step["problem"]], step["input"].get("input")
            # Output-dependent facts remain the native validator's job. A
            # binding is already a value, not a missing parameter.
            if alias not in inputs:
                continue
            if error:
                missing = validator_gap(error, card, inputs, alias, step["parameters"])
            else:
                answered = [key.removeprefix(step["id"] + ":") for key in (context or {}).get("answered", [])
                            if key.startswith(step["id"] + ":")]
                missing = detect_gap(card, inputs, step["parameters"], alias, entities,
                                     answered, step["bindings"], question=(context or {}).get("question", body.message))
                if not missing and card["requirements"]["direction"] == "undirected" and inputs[alias]["data"].get("graph", {}).get("directed"):
                    missing = gap("direction", "Use an undirected copy for this calculation and keep the original snapshot?",
                        [{"action": "undirected", "label": CONVERT_CHOICE if card["id"] == "maximal-bicliques" else "Use an undirected copy for this analysis."},
                         {"action": "cancel", "label": KEEP_CHOICE if card["id"] == "maximal-bicliques" else "Keep the directed graph and stop this calculation."}], key="direction")
            if missing:
                # Distinct steps may use the same problem with distinct
                # arguments. One round per gap means one per *step* here.
                missing["key"] = step["id"] + ":" + missing["key"]
                saved = {**(context or {}), "question": (context or {}).get("question", body.message),
                         "problems": list(dict.fromkeys(row["problem"] for row in plan["steps"])),
                         "parameters": step["parameters"], "bindings": step["bindings"], "alias": alias,
                         "selected": True, "entities": entities, "plan": plan, "step_id": step["id"]}
                return await self._ask_gap(body, saved, missing)
        return None

    async def _continue_plan(self, session_id, body, inputs, cards, context):
        from .analytics_bipartite import complete_partitions
        plan = deepcopy(context["plan"])
        step = next(row for row in plan["steps"] if row["id"] == context["step_id"])
        step.update(parameters=context["parameters"], bindings=context.get("bindings", {}), input={"input": context["alias"]})
        missing = await self._planned_question(body, plan, cards, inputs, context.get("entities", []), context)
        if missing:
            return missing
        plan, sides, _directed = complete_partitions(plan, inputs)
        if sides:
            return {**sides, "lane": "needs_information"}
        try:
            checked = await self.analytics.validate(session_id, body.inputs, plan, inputs)
        except AnalyticsError as error:
            if error.status >= 500:
                raise
            missing = await self._planned_question(body, plan, cards, inputs, context.get("entities", []), context, error)
            return missing or {"status": "unsupported", "lane": "unsupported", "plan": None,
                               "message": f"This calculation cannot run on these inputs: {error}"}
        return {"status": "ready", "lane": "calculate", "message": "The selected calculation is ready.",
                "plan": checked["plan"], "validation": checked}

    async def _ask_gap(self, body, context, missing, *, sentence=None):
        context = deepcopy(context)
        key = missing["key"]
        if key in context.get("asked", []):
            # A completed gap cannot start a second clarification round after
            # native validation. Keep the precise issue, without another ask.
            return {"status": "unsupported", "lane": "unsupported", "plan": None,
                    "message": missing.get("validation_error") or "The supplied answer does not satisfy this calculation. Start a new request with corrected inputs."}
        context.setdefault("asked", []).append(key)
        message = sentence or missing["message"]
        if not sentence and self.settings.llm_enabled:
            wording = await self._generate("clarify", {
                "task": "word_question", "question": context["question"],
                "prompt": missing["message"], "gap": missing["kind"],
                "choices": [{"id": row["id"], "label": row["label"]} for row in missing["choices"][:30]],
            }, {"type": "object", "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 700}},
                "required": ["message"], "additionalProperties": False})
            message = wording["message"]
        pending = {"id": str(uuid4()), "gap": "clarification", **missing, "message": message,
                   "context": context, "question": context["question"], "problems": context["problems"],
                   "inputs": {key: ref.model_dump() for key, ref in body.inputs.items()}, "device": body.device,
                   "mode": body.mode}
        return self._pending_response(pending)

    @staticmethod
    def _pending_response(pending, error=None):
        return {"status": "needs_information", "lane": "needs_information", "message": pending["message"],
                "choices": [] if pending.get("open_question") else [row["label"] for row in pending["choices"][:8]], "plan": None,
                "pending_question": {**pending, **({"answer_error": error} if error else {})}}

    async def _answer_choice(self, body, pending, inputs):
        choices, text = pending["choices"], body.message.strip()
        if body.clarification_choice:
            choice = next((row for row in choices if row["id"] == body.clarification_choice), None)
            if choice is None:
                raise ValueError("Choose one of the offered options or type your answer.")
            return choice
        exact = [row for row in choices if normalized(text) in {
            normalized(row["label"]), normalized(row.get("alias", "")), normalized(row.get("value", ""))}]
        if len(exact) == 1:
            return exact[0]
        if pending["kind"] == "objective":
            wording = normalized(text).replace("-", " ")
            named = [row for row in choices if re.search(r"(?<!\w)" + re.escape(row["problem"].replace("-", " ")) + r"(?!\w)", wording)]
            if len(named) == 1:
                return named[0]
        spec, parameter = pending.get("spec"), pending.get("parameter")
        if spec and parameter not in GRAPH_ARGUMENTS:
            if spec["kind"] == "vertex_id" or parameter in VERTEX_ARRAYS:
                aliases = {row["alias"] for row in choices if row["action"] == "vertex"}
                matches = matched_entities(text, {key: value for key, value in inputs.items() if key in aliases}, limit=1000000)
                explicit_ids = False
                try:
                    raw = json.loads(text)
                    ids = raw if isinstance(raw, list) else [raw]
                    typed = [row for row in choices if row["action"] == "vertex" and any(identity(row["value"]) == identity(value) for value in ids)]
                    if len(typed) == len(ids):
                        matches = [{"input": row["alias"], "id": row["value"], "matched": row["name"]} for row in typed]
                        explicit_ids = True
                except ValueError:
                    pass
                allowed = {(row["alias"], identity(row["value"])) for row in choices if row["action"] == "vertex"}
                if matches and all((row['input'], identity(row['id'])) in allowed for row in matches) and (explicit_ids or not ambiguous_entities(matches)) and len({row['input'] for row in matches}) == 1:
                    if spec["kind"] == "vertex_id" and len(matches) != 1:
                        raise ValueError("Choose one vertex for this value.")
                    return {"action": "parameter", "value": matches[0]["id"] if spec["kind"] == "vertex_id" else [row["id"] for row in matches], "alias": matches[0]["input"]}
            elif not choices:
                try:
                    value = json.loads(text)
                except ValueError:
                    if spec["kind"] == "string":
                        value = text
                    elif spec["kind"] in {"integer", "number"} and len(numbers := re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])", text.rstrip(".!?"))) == 1:
                        value = json.loads(numbers[0])
                    else:
                        raise ValueError(f"Enter a valid {spec['kind']} value for {parameter.replace('_', ' ')}.")
                return {"action": "parameter", "value": checked_value(spec, value)}
        if pending["kind"] == "sides":
            alias = pending["context"]["alias"]
            graph = deepcopy(inputs[alias]["data"])
            try:
                partitions = json.loads(text)
            except ValueError:
                partitions = None
            if isinstance(partitions, dict) and set(partitions) == {"left_partition", "right_partition"}:
                if not all(isinstance(value, list) for value in partitions.values()):
                    raise ValueError("Both partitions must be JSON arrays.")
                left, right = ({identity(value) for value in partitions[name]} for name in ("left_partition", "right_partition"))
                actual = {identity(row['id']) for row in graph['vertices']}
                if left & right or left | right != actual or not left or not right or len(left) != len(partitions["left_partition"]) or len(right) != len(partitions["right_partition"]):
                    raise ValueError("The two nonempty sides must include every vertex exactly once.")
                for vertex in graph["vertices"]:
                    vertex.setdefault("attributes", {})["side"] = "left" if identity(vertex["id"]) in left else "right"
                if infer_bipartition(graph) is None:
                    raise ValueError("Every connection must cross between the two sides.")
                return {"action": "sides", "graph": graph}
            types = sorted({row.get("type", "unspecified") for row in graph['vertices']})
            if len(types) == 2 and all(normalized(name) in normalized(text) for name in types) and infer_bipartition(graph) is not None:
                return {"action": "sides"}
        if pending["kind"] == "entity":
            try:
                value = json.loads(text)
                typed = [row for row in choices if identity(row["value"]) == identity(value)]
                if len(typed) == 1:
                    return typed[0]
            except ValueError:
                pass
            named = [row for row in choices if normalized(text) == normalized(row.get("name", ""))]
            if len(named) == 1:
                return named[0]
        # Free prose can only select an existing opaque choice, never create
        # an ID/value. Large sets must first be narrowed by exact code matching.
        if choices and (len(choices) <= 30 or pending["kind"] == "objective") and self.settings.llm_enabled:
            selected = await self._generate("clarify", {"task": "match_answer", "question": pending["message"],
                "answer": text, "choices": [{"id": row["id"], "label": row["label"]} for row in choices]},
                {"type": "object", "properties": {"choice_id": {"enum": [None, *[row['id'] for row in choices]]}},
                 "required": ["choice_id"], "additionalProperties": False})
            choice = next((row for row in choices if row["id"] == selected["choice_id"]), None)
            if choice is not None:
                return choice
        raise ValueError("I couldn't match that reply. Choose an option, or enter a specific value, name or ID.")

    async def _copy_for_answer(self, session_id, body, inputs, alias, choice, question):
        graph = deepcopy(choice.get("graph", inputs[alias]["data"]))
        action = choice["action"]
        if action == "undirected":
            graph["graph"]["directed"] = False
        elif action in {"weight", "timestamp"}:
            for edge in graph["edges"]:
                edge[action] = fields(edge)[choice["field"]]
        elif action == "sides":
            left = infer_bipartition(graph)
            if left is None:
                raise ValueError("Those sides do not form a valid bipartition on this snapshot.")
            keys = {identity(value) for value in left}
            for vertex in graph["vertices"]:
                vertex.setdefault("attributes", {})["side"] = "left" if identity(vertex["id"]) in keys else "right"
        source = self.analytics.database.get_file(body.inputs[alias].file_id)
        generated = await asyncio.to_thread(self.analytics.graph_store.ingest,
            session_id=session_id, role=FileRole.graph, filename=f"analysis-{action}.json",
            content=json.dumps(graph, allow_nan=False).encode(), unlimited=True,
            provenance={"type": "confirmed_analysis_preparation", "source_file_id": source.id,
                        "source_sha256": source.sha256, "choice": {key: value for key, value in choice.items() if key != "graph"}, "question": question})
        refs = dict(body.inputs)
        suffix = 1
        while f"prepared_{suffix}" in refs:
            suffix += 1
        alias = f"prepared_{suffix}"
        refs[alias] = InputReference(file_id=generated.id, kind="graph")
        return refs, alias

    async def _resume_clarification(self, session_id, body, inputs, cards):
        if body.evaluation_id or body.intent:
            return None
        previous = [event.payload for event in self.analytics.database.events(session_id, types=("workflow.chat",))
                    if event.payload.get("role") == "assistant" and event.payload.get("turn_id") != self.conversation.get()["turn_id"]]
        if body.clarification_id:
            asked = {event.payload.get("turn_id"): event.payload for event in self.analytics.database.events(session_id, types=("workflow.chat",))
                     if event.payload.get("role") == "user"}
            while previous and previous[-1].get("status") in {"failed", "cancelled"} and asked.get(previous[-1].get("turn_id"), {}).get("clarification_id") == body.clarification_id:
                previous.pop()  # Retrying a failed reply still answers the same pending question.
        pending = previous[-1].get("pending_question") if previous else None
        if not pending or pending.get("gap") != "clarification":
            if body.clarification_id:
                raise AnalyticsError("This question is no longer pending in this conversation.", "stale_clarification", 409)
            return None
        legacy_choice = any(normalized(row["label"]) == normalized(body.message) for row in pending["choices"])
        if not body.clarification_id and not legacy_choice:
            return None
        if body.clarification_id and pending["id"] != body.clarification_id:
            raise AnalyticsError("This question is no longer pending in this conversation.", "stale_clarification", 409)
        if body.clarification_cancel:
            return {"status": "answered", "lane": "reply", "plan": None, "message": "Cancelled. You can ask a new question."}
        refs = {key: ref.model_dump() for key, ref in body.inputs.items()}
        # A new input is allowed only for a code-offered input replacement.
        changing = pending["kind"] in {"input", "sides"} or pending.get("parameter") in GRAPH_ARGUMENTS
        if body.device != pending["device"] or body.mode != saved_mode(pending)["mode"] or (refs != pending["inputs"] and not changing):
            raise AnalyticsError("The inputs, device or mode changed. Cancel this question and ask again.", "stale_clarification", 409)
        saved_refs = {key: InputReference.model_validate(ref) for key, ref in pending["inputs"].items()}
        saved_inputs = await self.analytics.load_inputs(session_id, saved_refs)
        context = deepcopy(pending["context"])
        try:
            choice = await self._answer_choice(body, pending, saved_inputs)
            action = choice["action"]
            if action == "cancel":
                return {"status": "answered", "lane": "reply", "plan": None, "message": "The input is unchanged. This calculation has not run."}
            alias, values = context.get("alias"), context["parameters"]
            if action == "current_input":
                available = [(key, ref) for key, ref in body.inputs.items() if ref.model_dump() not in pending["inputs"].values()]
                if len(available) != 1:
                    raise ValueError("Select one new snapshot in Data, then choose this option again.")
                key, ref = available[0]
                wanted = "graph" if pending.get("parameter") in GRAPH_ARGUMENTS else next(card for card in cards if card["id"] == context["problems"][0])["input_kind"]
                if inputs[key]["kind"] != wanted:
                    raise ValueError(f"Select a {wanted.replace('_', ' ')} input.")
                key = "added_input"
                while key in saved_refs:
                    key += "_new"
                saved_refs[key] = ref
                if pending.get("parameter") in GRAPH_ARGUMENTS:
                    context.setdefault("bindings", {})[pending["parameter"]] = {"input": key}
                else:
                    alias = key
            elif action == "input":
                alias = choice["alias"]
            elif action == "binding":
                context.setdefault("bindings", {})[pending["parameter"]] = {"input": choice["alias"]}
            elif action == "problem":
                context["problems"] = [choice["problem"]]
            elif action in {"parameter", "vertex"}:
                value = choice["value"]
                if pending["kind"] == "entity":
                    candidates = {(row["input"], identity(row["id"])) for row in context.get("entities", [])
                                  if normalized(row["matched"]) == pending["matched"]}
                    by_id = {card["id"]: card for card in cards}
                    def replace_entity(parameters, problem, input_alias):
                        for name, spec in by_id[problem]["parameters"].items():
                            if name not in parameters:
                                continue
                            if spec["kind"] == "vertex_id" and (input_alias, identity(parameters[name])) in candidates:
                                parameters[name] = value
                            elif name in VERTEX_ARRAYS and isinstance(parameters[name], list):
                                rewritten = [value if (input_alias, identity(item)) in candidates else item for item in parameters[name]]
                                parameters[name] = list({identity(item): item for item in rewritten}.values())
                    if context.get("plan"):
                        for step in context["plan"]["steps"]:
                            replace_entity(step["parameters"], step["problem"], step["input"].get("input"))
                        problem = next(step["problem"] for step in context["plan"]["steps"] if step["id"] == context["step_id"])
                    else:
                        problem = context["problems"][0]
                    replace_entity(values, problem, alias)
                    context["entities"] = [row for row in context.get("entities", []) if normalized(row["matched"]) != pending["matched"]]
                    context["entities"].append({"input": choice["alias"], "id": value, "matched": pending["matched"]})
                    alias = choice["alias"]
                    if context.get("lane") == "lookup":
                        name = "vertices" if context["problems"] == ["node-lookup"] else "entity"
                        values[name] = [value] if name == "vertices" else value
                else:
                    if action == "vertex" and pending["spec"]["kind"] == "array":
                        value = [value]
                    values[pending["parameter"]] = checked_value(pending["spec"], value)
                    alias = choice.get("alias", alias)
            elif action == "unit_weight":
                values.update(choice["parameters"])
            elif action in {"undirected", "weight", "timestamp", "sides"}:
                effective = body.model_copy(update={"inputs": saved_refs})
                saved_refs, alias = await self._copy_for_answer(session_id, effective, saved_inputs, alias, choice, context["question"])
            else:
                raise ValueError("That reply is not available for this question.")
            context["alias"] = alias
            context.setdefault("answered", []).append(pending["key"])
            effective = body.model_copy(update={"message": context["question"], "inputs": saved_refs,
                                                "clarification_id": None, "clarification_choice": None})
            loaded = await self.analytics.load_inputs(session_id, saved_refs)
            if context.get("plan"):
                result = await self._continue_plan(session_id, effective, loaded, cards, context)
            else:
                result = await self._problem_lane(session_id, effective, loaded, cards, context["problems"], values,
                    selected=context["selected"], alias=alias, entities=context.get("entities", []), clarification=context)
            if result is None:
                # Selected DAGs keep their problem set; the constrained plan
                # stage is allowed, but routing is not repeated.
                selected_values = deepcopy(context.get("problem_parameters", values))
                if context.get("problem_parameters"):
                    selected_values[context["problems"][0]] = values
                effective = effective.model_copy(update={"intent": "calculate", "problems": context["problems"], "parameters": selected_values})
                result = await self._plan(session_id, effective, continuation=context)
            return {**result, "inputs": {key: ref.model_dump() for key, ref in saved_refs.items()}}
        except (ValueError, jsonschema.ValidationError) as error:
            if isinstance(error, AnalyticsError):
                raise
            return self._pending_response(pending, str(error)[:500])
