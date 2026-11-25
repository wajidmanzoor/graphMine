"""Lane execution and explicit input preparation, separate from LLM planning."""

import asyncio
from copy import deepcopy
import json

from .analytics import AnalyticsError, InputReference
from .analytics_bipartite import CONVERT_CHOICE, KEEP_CHOICE, complete_partitions, missing_sides
from .analytics_eligibility import eligible, input_profile, numeric, requested_preferences
from .analytics_lane_choices import explicit_parameters, one_step
from .analytics_options import candidate_menu, make_cards, validate_edits
from .analytics_clarification import Clarifications, detect_gap, gap as clarification_gap, validator_gap
from .graph_context import fields, identity, infer_bipartition
from .models import FileRole


class AnalyticsLanes(Clarifications):
    def _picked_option(self, session_id, body):
        if body.intent != "calculate":
            if body.problems or body.parameters or body.option_id or body.option_turn_id:
                raise AnalyticsError("Problems and parameters require an explicit calculation choice.")
            return None
        if not body.problems:
            raise AnalyticsError("Choose at least one problem.")
        if bool(body.option_id) != bool(body.option_turn_id):
            raise AnalyticsError("A saved choice needs its option and question IDs.")
        if not body.option_id:
            return {"problems": body.problems, "parameters": body.parameters, "question": body.message}
        saved = next((event.payload for event in self.analytics.database.events(session_id, types=("workflow.chat",))
                      if event.payload.get("turn_id") == body.option_turn_id and event.payload.get("role") == "assistant"), None)
        refs = {key: ref.model_dump() for key, ref in body.inputs.items()}
        if not saved or saved.get("status") != "options" or saved.get("inputs") != refs:
            raise AnalyticsError("This choice no longer matches the question's inputs. Ask again using the current snapshot.")
        choice = next((row for row in saved.get("options", []) if row["id"] == body.option_id), None)
        if not choice or choice["problems"] != body.problems:
            raise AnalyticsError("The submitted problem does not match the saved choice.")
        try:
            validate_edits(choice, body.parameters)
        except ValueError as error:
            raise AnalyticsError(str(error)) from error
        context = saved.get("clarification_context")
        if context and context["problems"] != choice["problems"]:
            context = None
        return {**choice, "question": saved["question"], "parameters": deepcopy(body.parameters),
                "clarification": context}

    async def _offer_options(self, body, inputs, cards, problems, values, alias, entities, context):
        profiles = self._profiles(inputs)
        allowed = context.get("candidate_problems")
        candidates = cards if allowed is None else [card for card in cards if card["id"] in allowed]
        menu = candidate_menu(candidates, profiles, body.message, entities, selected=problems,
                              supplied=context.get("problem_parameters", values), alias=alias)
        if not menu:
            return self._gap("No eligible calculation matches this input. What result would you like to find?")
        ranked = []
        calculations = context.get("ranked_calculations") or [{"problems": problems, "reason": body.message}]
        if context.get("answered"):
            calculations = [{"problems": problems, "reason": body.message}]
        for index, calculation in enumerate(calculations[:3]):
            selected = calculation["problems"]
            choices = candidate_menu(candidates, profiles, body.message, entities, selected=selected,
                                     supplied=context.get("problem_parameters", values), alias=alias)
            candidate = next((row for row in choices if row.get("problems", [row["problem"]]) == selected), None)
            if candidate is None:
                continue
            candidate["missing"] = [name for name in candidate["missing"] if name not in context.get("bindings", {})]
            ranked.append({**candidate, "score": 1.0 / (index + 1), "match": "Medium",
                "interpretation": calculation["reason"],
                "match_evidence": {"source": "route", "rank": index + 1, "votes": 1,
                    "missing_parameters": candidate["missing"], "calibrated": False}})
        options = make_cards(ranked, cards, profiles, body.message)
        evidence = {"source": "route", "candidates": [{key: row[key] for key in ("id", "problem", "match_evidence")} for row in ranked]}
        if not options:
            return {**self._gap("No supported calculation matches this question. What result would you like to find?"), "option_evidence": evidence}
        if all(option["match"] == "Low" for option in options):
            choices = [{"action": "problem", "problem": card["id"], "label": f"Use {card['title']}."}
                       for card in cards if any(row["problem"] == card["id"] for row in menu)]
            missing = clarification_gap("objective", "What result would answer your question? Please describe what you want to find or compare.", choices, key="objective")
            # Keep the finite allowed set for matching the free-text reply, but
            # show an open question when neither calculation has enough support.
            response = await self._ask_gap(body, {**context, "problems": [], "parameters": {}}, missing, sentence=missing["message"])
            response["choices"] = []
            response["pending_question"]["open_question"] = True
            return {**response, "option_evidence": evidence}
        return {"status": "options", "lane": "options", "message": "Choose the result you want to calculate.",
                "question": body.message, "options": options, "plan": None, "clarification_context": context,
                "option_evidence": evidence}

    @staticmethod
    def _profiles(inputs):
        profiles = {alias: input_profile(row) for alias, row in inputs.items()}
        graphs = sum(row["kind"] == "graph" for row in inputs.values())
        for profile in profiles.values():
            profile["query_graph_available"] = graphs > 1
        return profiles

    @staticmethod
    def _gap(message, choices=(), **extra):
        return {"status": "needs_information", "lane": "needs_information", "message": message,
                "choices": list(choices), "plan": None, **extra}

    def _prepare_question(self, body, problems, parameters, alias, kind, choices, question, selected):
        return self._gap(question, [choice["label"] for choice in choices], pending_question={
            "gap": "lane_preparation", "kind": kind, "problems": problems,
            "parameters": parameters, "alias": alias, "question": body.message,
            "choices": choices, "selected": selected, "device": body.device,
            "inputs": {key: ref.model_dump() for key, ref in body.inputs.items()},
        })

    async def _resume_lane_preparation(self, session_id, body, inputs, cards):
        if body.evaluation_id or body.intent:
            return None
        previous = [event.payload for event in self.analytics.database.events(session_id, types=("workflow.chat",))
                    if event.payload.get("role") == "assistant" and event.payload.get("turn_id") != self.conversation.get()["turn_id"]]
        pending = previous[-1].get("pending_question") if previous else None
        if not pending or pending.get("gap") != "lane_preparation":
            return None
        choice = next((row for row in pending["choices"] if row["label"] == body.message.strip()), None)
        if choice is None:
            return None
        refs = {key: ref.model_dump() for key, ref in body.inputs.items()}
        if pending["inputs"] != refs or pending["device"] != body.device:
            return self._gap("The selected inputs changed. Ask the calculation again using the current snapshot.")
        if choice["action"] == "cancel":
            return self._gap("The input is unchanged. This calculation has not run.")
        alias, parameters = pending["alias"], deepcopy(pending["parameters"])
        graph = deepcopy(inputs[alias]["data"])
        if choice["action"] == "unit_weight":
            parameters.update(choice["parameters"])
        else:
            if choice["action"] == "undirected":
                graph["graph"]["directed"] = False
            elif choice["action"] == "weight":
                values = [fields(edge).get(choice["field"]) for edge in graph["edges"]]
                if not all(numeric(value) for value in values):
                    return self._gap("That field is no longer numeric on every connection.")
                for edge, value in zip(graph["edges"], values):
                    edge["weight"] = value
            elif choice["action"] == "timestamp":
                for edge in graph["edges"]:
                    edge["timestamp"] = fields(edge)[choice["field"]]
            elif choice["action"] == "sides":
                left = infer_bipartition(graph)
                if left is None:
                    return self._gap(missing_sides()["message"])
                keys = {identity(value) for value in left}
                for vertex in graph["vertices"]:
                    vertex.setdefault("attributes", {})["side"] = "left" if identity(vertex["id"]) in keys else "right"
            else:
                raise AnalyticsError("Unknown input preparation choice.")
            source = self.analytics.database.get_file(body.inputs[alias].file_id)
            generated = await asyncio.to_thread(
                self.analytics.graph_store.ingest, session_id=session_id, role=FileRole.graph,
                filename=f"analysis-{choice['action']}.json", content=json.dumps(graph, allow_nan=False).encode(),
                unlimited=True, provenance={"type": "confirmed_analysis_preparation", "source_file_id": source.id,
                    "source_sha256": source.sha256, "choice": choice, "question": pending["question"]})
            # Retain original aliases and rebind this calculation only.
            suffix = 1
            prepared_alias = f"prepared_{suffix}"
            while prepared_alias in refs:
                suffix += 1
                prepared_alias = f"prepared_{suffix}"
            refs[prepared_alias] = {"file_id": generated.id, "kind": "graph"}
            alias = prepared_alias
        resumed = body.model_copy(update={"message": pending["question"],
            "inputs": {key: InputReference.model_validate(value) for key, value in refs.items()}})
        loaded = await self.analytics.load_inputs(session_id, resumed.inputs)
        result = await self._problem_lane(session_id, resumed, loaded, cards,
            pending["problems"], parameters, selected=pending["selected"], alias=alias)
        if result is None:
            raise AnalyticsError("This preparation requires a new explicit calculation choice.")
        return {**result, "inputs": refs}

    async def _problem_lane(self, session_id, body, inputs, cards, problems, parameters=None, *, selected=False, alias=None, entities=(), clarification=None, clarify_only=False, candidate_problems=None, ranked_calculations=None):
        by_id = {card["id"]: card for card in cards}
        if not problems or len(problems) != len(set(problems)) or any(op not in by_id for op in problems):
            raise AnalyticsError("Choose problems available on this server and device.")
        primary = by_id[problems[0]]
        candidates = [key for key, value in inputs.items() if value["kind"] == primary["input_kind"]]
        if alias is None:
            comparison = any(name in primary["parameters"] for name in ("query_graph", "other_graph"))
            alias = candidates[0] if len(candidates) == 1 else "main" if comparison and "main" in candidates else None
        supplied = parameters or {}
        if len(problems) > 1 and isinstance(supplied.get(primary["id"]), dict):
            supplied = supplied[primary["id"]]
        values = {} if selected else explicit_parameters(primary, body.message, entities, alias)
        values.update(supplied)
        context = {"question": body.message, "problems": problems, "parameters": values,
                   "alias": alias, "selected": selected, "entities": list(entities),
                   **(deepcopy(clarification) if clarification else {})}
        context.update(parameters=values, alias=alias, selected=selected)
        if ranked_calculations is not None:
            context["ranked_calculations"] = deepcopy(ranked_calculations)
        if candidate_problems is not None:
            context["candidate_problems"] = list(candidate_problems)
        if len(problems) > 1 and any(isinstance((parameters or {}).get(op), dict) for op in problems):
            context["problem_parameters"] = deepcopy(parameters)
        missing = detect_gap(primary, inputs, values, alias, entities,
                             context.get("answered", []), context.get("bindings"), question=body.message)
        if missing:
            return await self._ask_gap(body, context, missing)
        profiles = self._profiles(inputs)
        profile = profiles[alias]
        requested = requested_preferences(body.message, values)
        ok, reason = eligible(primary, profile, requested)
        if not ok:
            if requested["exact"] and primary["quality"] == "heuristic":
                return {"status": "unsupported", "lane": "unsupported", "message": reason,
                        "plan": None, "alternatives": self._closest(primary, cards)}
            return await self._ask_gap(body, context, clarification_gap("input", reason + " Which snapshot should I use?",
                [{"label": "Use the newly selected input.", "action": "current_input"}], key="input"))

        async def prepare(kind, choices, question):
            return await self._ask_gap(body, context, clarification_gap(kind, question, choices, key=kind))

        req = primary["requirements"]
        if req["direction"] == "undirected" and profile["directed"]:
            choices = [{"action": "undirected", "label": CONVERT_CHOICE if primary["id"] == "maximal-bicliques" else "Use an undirected copy for this analysis."},
                       {"action": "cancel", "label": KEEP_CHOICE if primary["id"] == "maximal-bicliques" else "Keep the directed graph and stop this calculation."}]
            return await prepare("direction", choices,
                "This calculation needs undirected connections. Use an undirected copy and keep the original snapshot?")
        if req["direction"] == "directed" and not profile["directed"]:
            return await prepare("input", [{"label": "Use the newly selected input.", "action": "current_input"}],
                "This calculation requires directed connections. Which directed snapshot should I use?")
        needs_weights = req["weights"] == "required" or (requested["weighted"] and req["weights"] != "ignored")
        if primary["id"] == "max-flow-min-cut":
            needs_weights = values.get("capacity_mode", "edge_weight") != "unit_capacity"
        if primary["id"] == "bipartite-matching":
            needs_weights = values.get("objective") in {"maximum_weight", "minimum_cost"}
        if needs_weights and not profile.get("canonical_weights_complete"):
            choices = [{"action": "weight", "field": field, "label": f"Use {field.removeprefix('attributes.')} as the weight."}
                       for field in profile.get("weight_candidates", [])[:3]]
            if primary["id"] == "max-flow-min-cut":
                choices.append({"action": "unit_weight", "parameters": {"capacity_mode": "unit_capacity"}, "label": "Use unit capacity for every connection."})
            if not choices:
                return await prepare("input", [{"label": "Use the newly selected input.", "action": "current_input"}],
                    "Which snapshot supplies complete numeric connection weights?")
            return await prepare("weights", choices, "Which values should this calculation use as connection weights?")
        if "timestamps" in req["needs"] and not profile.get("timestamps_complete"):
            choices = [{"action": "timestamp", "field": field,
                        "label": f"Use {field} as event timestamps."}
                       for field in profile.get("timestamp_candidates", [])]
            return await prepare("timestamps", choices, "Use the stored timestamp field on a new snapshot?")
        if ("bipartite_side" in req["needs"] and primary["id"] != "maximal-bicliques"
                and profile["bipartition"]["source"] != "attributes.side"):
            choices = [{"action": "sides", "label": f"Use {' / '.join(profile['vertex_types'])} as the two sides."},
                       {"action": "cancel", "label": "Keep the snapshot unchanged and stop this calculation."}]
            return await prepare("sides", choices, "Use the two vertex types as sides on a new snapshot?")
        if not selected:
            if clarify_only:
                return None  # Preserve the router's unresolved objective; do not sample options.
            return await self._offer_options(body, inputs, cards, problems, values, alias, entities, context)
        if len(problems) != 1:
            return None  # The selected multi-step objective uses constrained DAG planning.
        plan = one_step(primary["id"], alias, values, body.device)
        plan["steps"][0]["bindings"].update(context.get("bindings", {}))
        for name in ("query_graph", "other_graph"):
            if primary["parameters"].get(name, {}).get("required") and name not in values and name not in plan["steps"][0]["bindings"]:
                others = [key for key in candidates if key != alias]
                if len(others) != 1:
                    return self._gap("Which separate query or comparison graph should be used?", others[:4])
                plan["steps"][0]["bindings"][name] = {"input": others[0]}
        plan, gap, _directed = complete_partitions(plan, inputs)
        if gap:
            return {**gap, "lane": "needs_information"}
        try:
            checked = await self.analytics.validate(session_id, body.inputs, plan, inputs)
        except AnalyticsError as error:
            if error.status >= 500:
                raise
            missing = validator_gap(error, primary, inputs, alias, values)
            if missing:
                return await self._ask_gap(body, context, missing)
            return {"status": "unsupported", "lane": "unsupported", "plan": None,
                    "message": f"This calculation cannot run on these inputs: {error}"}
        return {"status": "ready", "lane": context.get("lane", "calculate"), "message": "The selected calculation is ready.",
                "plan": checked["plan"], "validation": checked}

    @staticmethod
    def _closest(primary, cards):
        return [{"problem": card["id"], "title": card["title"], "quality": card["quality"]}
                for card in cards if card["family"] == primary["family"] and card["id"] != primary["id"]][:2]
