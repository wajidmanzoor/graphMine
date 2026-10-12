from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .analysis import (
    CHART_REPAIR_GUIDANCE,
    analyst_payload,
    apply_narrative,
    prepare_analysis,
    validate_narrative,
)
from .answers import answer_interpretation, build_answer
from .catalog import Catalog
from .commands import command_name
from .commands import dispatch as dispatch_command
from .config import Settings
from .database import Database
from .graph_context import (
    infer_bipartition,
    inspect_records,
    project_graph,
    semantic_context,
)
from .graph_store import GraphStore
from .jobs import JobManager
from .llm import LLMError, OpenAICompatibleModel, RuleBasedModel
from .models import (
    AnalysisTask,
    ApplicationIntent,
    ChatRequest,
    ChatResponse,
    ExecutionPlan,
    FileRole,
    GroundedNarrative,
    LLMMode,
    PlanDraft,
    PlanningOutcome,
    PlanRequest,
    ResultRecord,
    RouteDecision,
    TurnDecision,
    new_id,
)
from .planning import (
    APPLICATION_PREPROCESSING,
    PlanValidationError,
    PlanValidator,
    bind_unique_required_auxiliary_inputs,
    normalize_route,
    preserve_review_intent,
    resolve_route_scope,
    route_blocker,
    route_request_payload,
)
from .profiles import (
    DIRECTION_PRESERVING_OPERATIONS,
    ProfileInputError,
    prepare_operation_graph,
)
from .reporting import render_report
from .visualization import (
    answer_visualizations,
    sanitize_visualizations,
)


@dataclass(frozen=True)
class _DraftAttempt:
    outcome: PlanningOutcome
    review_reason: dict[str, Any] | None = None


class AgentService:
    """Domain-first planning and verified answer presentation around one model."""

    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        database: Database,
        graph_store: GraphStore,
        validator: PlanValidator,
        jobs: JobManager,
    ):
        self.settings = settings
        self.catalog = catalog
        self.database = database
        self.graph_store = graph_store
        self.validator = validator
        self.jobs = jobs
        self.model = (
            OpenAICompatibleModel(settings, database.history)
            if settings.llm_enabled
            else RuleBasedModel()
        )

    async def close(self) -> None:
        await self.model.close()

    async def plan(
        self,
        session_id: str,
        request: PlanRequest,
        *,
        followup: TurnDecision | None = None,
    ) -> PlanningOutcome:
        self.database.get_session(session_id)
        with self.database.history.scope(session_id, "planning", request):
            outcome = await self._plan(session_id, request, followup=followup)
            self.database.history.current("planning.response", outcome)
            return outcome

    async def _generate(self, **kwargs):
        context = self.database.history.context()
        schema_name = kwargs["schema"].__name__
        stage = {
            "RouteDecision": "Understanding your request",
            "TurnDecision": "Checking your follow-up",
            "PlanDraft": "Validating the analysis plan",
            "GroundedNarrative": "Explaining the computed results",
        }.get(schema_name, "Preparing your analysis")
        activity_id = new_id("activity")

        async def activity(status, message, **extra):
            if context.get("session_id"):
                await self.jobs.event_bus.publish(
                    context["session_id"],
                    "analysis.activity",
                    {
                        "activity_id": activity_id,
                        "turn_id": context.get("turn_id"),
                        "stage": stage,
                        "status": status,
                        "message": message,
                        **extra,
                    },
                    job_id=context.get("job_id"),
                )

        await activity("running", stage + "…")
        started = time.monotonic()
        self.database.history.current(
            "model.input",
            {
                "provider": "llm" if self.settings.llm_enabled else "offline_rules",
                "schema": kwargs["schema"].__name__,
                "mode": kwargs["mode"].value,
                "payload": kwargs["user_payload"],
                "conversation": kwargs.get("conversation", []),
            },
        )
        try:
            result = await self.model.generate(**kwargs)
        except Exception:
            await activity(
                "failed",
                "This stage could not finish. The error is saved with this conversation.",
            )
            raise
        self.database.history.current(
            "model.parsed",
            {
                "schema": kwargs["schema"].__name__,
                "value": result,
            },
        )
        summary = "Stage completed."
        if isinstance(result, RouteDecision):
            summary = result.explanation or "Request interpretation completed."
        elif isinstance(result, PlanDraft):
            summary = result.message
        elif isinstance(result, TurnDecision):
            summary = {
                "explain": "Using the existing result to answer your follow-up.",
                "analyze": "Your follow-up requires a new analysis.",
                "clarify": "Checking the full context before deciding what to ask.",
            }.get(result.action, summary)
        elif isinstance(result, GroundedNarrative):
            summary = "Explanation prepared from the computed facts."
        await activity(
            "completed", summary, elapsed_seconds=round(time.monotonic() - started, 2)
        )
        return result

    def _context_result(self, session_id, graph_id, result_id=None):
        result = (
            self.database.get_result(result_id)
            if result_id
            else self.database.latest_result(session_id, graph_id=graph_id)
        )
        if result is not None:
            if result.session_id != session_id:
                raise ValueError("result_id must identify a result from this session")
            if self.database.get_job(result.job_id).plan.graph_id != graph_id:
                raise ValueError(
                    "result_id must identify a result from the selected graph"
                )
        return result

    def _conversation_state(self, graph, result, conversation):
        previous_plan = self.database.get_job(result.job_id).plan if result else None
        intent = previous_plan.application_intent if previous_plan else None
        return {
            "graph_id": graph.id,
            "graph_sha256": graph.sha256,
            "result_id": result.id if result else None,
            "active_constraints": intent.model_dump(mode="json") if intent else None,
            "previous_objective": result.answer.get("question") if result else None,
            "previous_result_status": result.answer.get("result_status")
            if result
            else None,
            "pending_request": self._pending_request(conversation, graph.id),
        }

    async def _plan(
        self,
        session_id: str,
        request: PlanRequest,
        *,
        followup: TurnDecision | None = None,
    ) -> PlanningOutcome:
        session = self.database.get_session(session_id)
        graph = self.database.get_file(request.graph_id)
        if graph.session_id != session_id or graph.role != FileRole.graph:
            raise ValueError("graph_id must identify a graph uploaded to this session")
        conversation = self.database.messages(session_id)
        raw_graph = self.graph_store.read_graph(request.graph_id, session_id)
        context = getattr(graph.metadata, "semantic_context", None) or semantic_context(
            raw_graph
        )
        previous = self._context_result(session_id, request.graph_id, request.result_id)
        previous_intent = (
            self.database.get_job(previous.job_id).plan.application_intent
            if previous
            else None
        )
        state = self._conversation_state(graph, previous, conversation)
        self.database.history.current("conversation.context", state)
        await self.jobs.event_bus.publish(
            session_id,
            "analysis.understanding",
            {"message": "Understanding your question and the available data."},
        )
        route_payload = route_request_payload(
            message=request.message,
            graph_context=context,
            active_constraints=previous_intent.model_dump(mode="json")
            if previous_intent
            else None,
            pending_request=self._pending_request(conversation, request.graph_id),
            graph_metadata=(
                graph.metadata.model_dump(mode="json", exclude={"semantic_context"})
                if hasattr(graph.metadata, "model_dump")
                else graph.metadata
            ),
            routing_context=self.catalog.routing_context(session.domain_id),
        )
        route_payload["conversation_state"] = state
        if followup:
            route_payload["followup_interpretation"] = {
                **followup.model_dump(mode="json"),
                "usage": "A model-proposed interpretation, not a replacement for the user's original message. Resolve it against that message, the selected result and its constraints. Do not omit or weaken explicit conditions.",
            }
        for inspection_round in range(3):
            decision = await self._generate(
                mode=LLMMode.planner,
                schema=RouteDecision,
                user_payload=route_payload,
                conversation=conversation,
            )
            if not decision.inspections:
                break
            if inspection_round == 2:
                return self._record_nonready(
                    session_id,
                    request,
                    decision,
                    "needs_information",
                    "I need a more specific selection to answer reliably. Which entities, relationship, or time period should I focus on?",
                )
            observations = []
            for inspection in decision.inspections:
                try:
                    value = inspect_records(raw_graph, inspection)
                except ValueError as error:
                    value = {"error": str(error)}
                observations.append(
                    {"request": inspection.model_dump(mode="json"), "result": value}
                )
                self.database.history.current("tool.inspect_records", observations[-1])
            route_payload.setdefault("inspection_results", []).extend(observations)
            route_payload["remaining_inspection_rounds"] = 1 - inspection_round
        decision = resolve_route_scope(self.catalog, decision, previous_intent)
        blocker = route_blocker(self.catalog, decision)
        # One bounded review supplies verified application capabilities and scope.
        # Never clear a refusal or a weight requirement by heuristic: a fresh
        # structured decision still has to pass every semantic/execution gate.
        if blocker and (
            decision.intent.filters
            or not raw_graph["vertices"]
            or not raw_graph["edges"]
        ):
            try:
                selected_graph = project_graph(raw_graph, decision.intent.filters)
            except ValueError:
                selected_graph = None
            if selected_graph is not None:
                review = {
                    "previous_decision": decision.model_dump(mode="json"),
                    "verified_projection": self._projection_evidence(
                        raw_graph, selected_graph, decision.intent
                    ),
                    "instruction": "Check your decision against application_preprocessing. Valid attribute filtering is supported independently of kernel weights. Empty selections are answers, not missing inputs. Keep genuine ambiguity, direction, pattern and weighted-computation requirements; never substitute a different question. Return a corrected decision only when justified by the user's request.",
                }
                self.database.history.current("planning.scope_review", review)
                revised = await self._generate(
                    mode=LLMMode.planner,
                    schema=RouteDecision,
                    user_payload={**route_payload, "scope_review": review},
                    conversation=conversation,
                )
                # A scope review may correct a refusal, but cannot remove the
                # constraints whose projection was just verified by the server.
                protected_intent, conflicts = preserve_review_intent(
                    decision.intent, revised.intent
                )
                if conflicts:
                    self.database.history.current(
                        "planning.scope_review.conflict", {"fields": conflicts}
                    )
                    return self._record_nonready(
                        session_id,
                        request,
                        decision,
                        "needs_information",
                        "I could not verify a correction that keeps your selection and conditions. Please clarify the required result and filters.",
                    )
                revised = revised.model_copy(
                    update={
                        "intent": protected_intent,
                        "additional_analyses": decision.additional_analyses,
                    }
                )
                decision = resolve_route_scope(self.catalog, revised, previous_intent)
                blocker = route_blocker(self.catalog, decision)
        if blocker:
            status, message = blocker
            if status == "unsupported":
                decision = decision.model_copy(
                    update={"supported": False, "operation_id": None}
                )
            return self._record_nonready(session_id, request, decision, status, message)

        # All steps are planned and checked before any of them may be queued.
        tasks = [(request, decision)]
        for additional in decision.additional_analyses:
            tasks.append(
                (
                    request.model_copy(update={"message": additional.question}),
                    decision.model_copy(
                        update={
                            "problem_id": additional.problem_id,
                            "operation_id": additional.operation_id,
                            "additional_analyses": [],
                        }
                    ),
                )
            )
        plans = []
        planned_tasks = []
        recovery_used = False
        for step_request, step_decision in tasks:
            step_decision = normalize_route(self.catalog, step_decision)
            blocker = route_blocker(self.catalog, step_decision)
            if blocker:
                return self._record_nonready(
                    session_id, request, step_decision, *blocker
                )
            if not step_decision.supported or not step_decision.operation_id:
                return self._record_nonready(
                    session_id,
                    request,
                    step_decision,
                    "unsupported",
                    "A required part of this question has no supported computation. No partial analysis has been executed.",
                )
            attempt = await self._draft(
                session_id, step_request, step_decision, raw_graph, context
            )
            if attempt.review_reason and not recovery_used:
                recovery_used = True
                reviewed = await self._review_route(
                    session_id,
                    step_request,
                    step_decision,
                    raw_graph,
                    route_payload,
                    attempt.review_reason,
                    request,
                )
                if isinstance(reviewed, PlanningOutcome):
                    return self._record_nonready(
                        session_id,
                        request,
                        reviewed.decision,
                        reviewed.status,
                        reviewed.message,
                    )
                step_decision = reviewed
                attempt = await self._draft(
                    session_id,
                    step_request,
                    step_decision,
                    raw_graph,
                    context,
                    route_review=attempt.review_reason,
                )
                self.database.history.current(
                    "planning.recovery.outcome",
                    {
                        "status": attempt.outcome.status,
                        "operation_id": step_decision.operation_id,
                        "reason": attempt.review_reason,
                    },
                )
            outcome = attempt.outcome
            if outcome.status != "ready":
                if attempt.review_reason:
                    # A failed choice is not proof that the entire catalog
                    # cannot answer this question. Do not retry indefinitely.
                    return self._record_nonready(
                        session_id,
                        request,
                        step_decision,
                        "needs_information",
                        "I could not verify an analysis that keeps all of your conditions. Please clarify the required result and any filters that must apply.",
                    )
                return self._record_nonready(
                    session_id,
                    request,
                    step_decision,
                    outcome.status,
                    outcome.message,
                )
            plans.append(outcome.plan)
            planned_tasks.append((step_request, step_decision))
        decision = planned_tasks[0][1].model_copy(
            update={
                "additional_analyses": [
                    AnalysisTask(
                        question=step.message,
                        problem_id=selected.problem_id,
                        operation_id=selected.operation_id,
                    )
                    for step, selected in planned_tasks[1:]
                ],
            }
        )
        outcome = PlanningOutcome(
            message=f"The analysis is ready ({len(plans)} step{'s' if len(plans) != 1 else ''}).",
            decision=decision,
            status="ready",
            plan=plans[0],
            plans=plans,
        )
        # Persist one user-visible outcome only after every required step has
        # passed validation. Intermediate failures remain in the trace.
        self.database.add_message(
            session_id,
            "user",
            {"message": request.message, "graph_id": request.graph_id},
            LLMMode.planner.value,
        )
        self.database.add_message(
            session_id,
            "assistant",
            {
                "message": outcome.message,
                "graph_id": request.graph_id,
                "plan": plans[0].model_dump(mode="json"),
                "plans": [plan.model_dump(mode="json") for plan in plans],
            },
            LLMMode.planner.value,
        )
        return outcome

    async def _review_route(
        self,
        session_id,
        request,
        decision,
        raw_graph,
        route_payload,
        reason,
        original_request,
    ) -> RouteDecision | PlanningOutcome:
        """One catalog review per request, with at most one inspection round."""
        review = {
            "attempt": 1,
            "maximum_attempts": 1,
            "failed_decision": decision.model_dump(mode="json"),
            "failure": reason,
            "original_request": original_request.model_dump(mode="json"),
            "step_request": request.model_dump(mode="json"),
            "protected_intent": decision.intent.model_dump(mode="json"),
            "instruction": "The selected operation could not produce a valid plan. Review the full catalog against this exact step and the original question. A limitation of one operation is not proof that all operations are unavailable. Correct the operation only when it answers the same question. Preserve every filter, weight, direction, pattern, time requirement, supplied parameter, backend, output and input. Do not add or remove supporting analyses. Missing input and genuinely unsupported requests must remain non-ready. If the meaning cannot be verified, ask a concrete question in the user's domain language. You may inspect records once; do not substitute a nearby computation to obtain a ready response.",
        }
        self.database.history.current("planning.recovery.request", review)
        await self.jobs.event_bus.publish(
            session_id,
            "analysis.understanding",
            {
                "message": "Checking another way to answer your original question while keeping its conditions.",
            },
        )
        payload = {
            **route_payload,
            "message": request.message,
            "routing_review": review,
        }
        for round_index in range(2):
            revised = await self._generate(
                mode=LLMMode.planner,
                schema=RouteDecision,
                user_payload=payload,
                conversation=self.database.messages(session_id),
            )
            if not revised.inspections:
                break
            if round_index == 1:
                return PlanningOutcome(
                    decision=decision,
                    status="needs_information",
                    message="I need a more specific selection to verify this request. Which entities or relationships should the analysis cover?",
                )
            observations = []
            for inspection in revised.inspections:
                try:
                    value = inspect_records(raw_graph, inspection)
                except ValueError as error:
                    value = {"error": str(error)}
                observation = {
                    "request": inspection.model_dump(mode="json"),
                    "result": value,
                }
                observations.append(observation)
                self.database.history.current("tool.inspect_records", observation)
            payload = {
                **payload,
                "inspection_results": [
                    *payload.get("inspection_results", []),
                    *observations,
                ],
                "remaining_inspection_rounds": 0,
            }
        # Omitting a constraint does not clear it. A contradictory or additional
        # constraint needs clarification instead of silently changing the task.
        protected_intent, conflicts = preserve_review_intent(
            decision.intent, revised.intent
        )
        if any(
            task not in decision.additional_analyses
            for task in revised.additional_analyses
        ):
            conflicts.append("supporting_analyses")
        if conflicts:
            self.database.history.current(
                "planning.recovery.constraint_conflict", {"fields": conflicts}
            )
            return PlanningOutcome(
                decision=decision,
                status="needs_information",
                message="I could not verify a correction that keeps all of your conditions. Please clarify the required result and any filters that must apply.",
            )
        revised = revised.model_copy(
            update={
                "intent": protected_intent,
                "additional_analyses": decision.additional_analyses,
            }
        )
        try:
            revised = normalize_route(self.catalog, revised)
        except PlanValidationError as error:
            self.database.history.current(
                "planning.recovery.invalid_route", {"errors": error.errors}
            )
            return PlanningOutcome(
                decision=decision,
                status="needs_information",
                message="I could not validate a supported analysis for this request. Please clarify the result you need.",
            )
        blocker = route_blocker(self.catalog, revised)
        if blocker:
            if blocker[0] == "unsupported":
                revised = revised.model_copy(
                    update={"supported": False, "operation_id": None}
                )
            return PlanningOutcome(
                decision=revised, status=blocker[0], message=blocker[1]
            )
        return revised

    @staticmethod
    def _projection_evidence(original, projected, intent):
        return {
            "filters": [item.model_dump(mode="json") for item in intent.filters],
            "original_vertices": len(original["vertices"]),
            "original_edges": len(original["edges"]),
            "selected_vertices": len(projected["vertices"]),
            "selected_edges": len(projected["edges"]),
            "attribute_filters_validated": True,
            "empty_selections_are_valid": True,
        }

    async def _draft(
        self,
        session_id: str,
        request: PlanRequest,
        decision: RouteDecision,
        raw_graph: dict[str, Any],
        context: dict[str, Any],
        *,
        route_review: dict[str, Any] | None = None,
    ) -> _DraftAttempt:
        def stop(status, message, *, code=None, errors=None):
            return _DraftAttempt(
                PlanningOutcome(decision=decision, status=status, message=message),
                {"code": code, "message": message, "errors": errors or []}
                if code
                else None,
            )

        session = self.database.get_session(session_id)
        graph = self.database.get_file(request.graph_id)
        conversation = self.database.messages(session_id)
        intent = (decision.intent or ApplicationIntent()).model_copy(
            update={"objective": request.message[:1500]}
        )
        try:
            projected = project_graph(raw_graph, intent.filters)
        except ValueError as error:
            return stop("needs_information", str(error))
        inferred_inputs = {}
        if (
            decision.operation_id == "maximal-bicliques"
            and "left_partition" not in request.auxiliary_inputs
        ):
            existing = [
                item
                for item in self.database.list_files(session_id)
                if item.role == FileRole.left_partition
            ]
            if not any(
                item.original_name != "inferred-entity-partition.json"
                for item in existing
            ):
                partition = infer_bipartition(projected, intent.entity_type)
                if partition is not None:
                    content = json.dumps(
                        {
                            "left_partition": partition,
                            "source_graph_id": graph.id,
                            "source_sha256": graph.sha256,
                        }
                    ).encode()
                    generated = next(
                        (
                            item
                            for item in existing
                            if self.graph_store.execution_path(
                                item.id, session_id
                            ).read_bytes()
                            == content
                        ),
                        None,
                    )
                    if generated is None:
                        generated = self.graph_store.ingest(
                            session_id=session_id,
                            role=FileRole.left_partition,
                            filename="inferred-entity-partition.json",
                            content=content,
                            media_type="application/json",
                        )
                    inferred_inputs["left_partition"] = [generated.id]
                    self.database.history.current(
                        "tool.infer_partition",
                        {
                            "source_graph_id": graph.id,
                            "source_sha256": graph.sha256,
                            "file_id": generated.id,
                            "entity_type": intent.entity_type,
                            "count": len(partition),
                        },
                    )

        available_files = [
            {
                "id": item.id,
                "role": item.role.value,
                "name": item.original_name,
                "metadata": (
                    item.metadata.model_dump(mode="json", exclude={"semantic_context"})
                    if hasattr(item.metadata, "model_dump")
                    else item.metadata
                ),
            }
            for item in self.database.list_files(session_id)
        ]
        planning_payload = {
            "task": "Check whether this exact application question can be answered by the supplied tool contract. Return ready with a complete plan OR needs_information/unsupported with plan=null. Never execute a nearby but different computation.",
            "message": request.message,
            "application_intent": intent.model_dump(mode="json"),
            "application_preprocessing": APPLICATION_PREPROCESSING,
            "verified_projection": self._projection_evidence(
                raw_graph, projected, intent
            ),
            "graph_context": context,
            "session_id": session_id,
            "graph_id": request.graph_id,
            "domain": self.catalog.domain(session.domain_id).model_dump(mode="json"),
            "graph_metadata": (
                graph.metadata.model_dump(mode="json", exclude={"semantic_context"})
                if hasattr(graph.metadata, "model_dump")
                else graph.metadata
            ),
            "selected_operation": {
                "problem_id": decision.problem_id,
                "operation_id": decision.operation_id,
            },
            "supporting_analyses_planned_separately": [
                item.model_dump(mode="json") for item in decision.additional_analyses
            ],
            "operation_context": self.catalog.operation_context(decision.operation_id),
            "available_files": available_files,
            "requested_backend": request.backend_id,
            "supplied_parameters": request.parameters,
            "requested_optional_outputs": request.optional_outputs,
            "explicit_request_fields": sorted(request.model_fields_set),
            "supplied_auxiliary_inputs": request.auxiliary_inputs,
            "inferred_auxiliary_inputs": inferred_inputs,
            "allow_directed_projection": request.allow_directed_projection,
        }
        if route_review:
            planning_payload["routing_review"] = {
                "previous_failure": route_review,
                "instruction": "Recheck the exact original step against this operation. The catalog review did not approve execution or waive constraints. Return ready only if every requirement is met; retain genuine missing inputs and unsupported meanings.",
            }
        draft = await self._generate(
            mode=LLMMode.planner,
            schema=PlanDraft,
            user_payload=planning_payload,
            conversation=conversation,
        )
        if draft.status != "ready" and (
            intent.filters or not projected["vertices"] or not projected["edges"]
        ):
            draft = await self._generate(
                mode=LLMMode.planner,
                schema=PlanDraft,
                user_payload={
                    **planning_payload,
                    "scope_review": {
                        "previous_draft": draft.model_dump(mode="json"),
                        "instruction": "Recheck application_preprocessing and verified_projection. Filtering is performed before the kernel; zero qualifying results are valid answers. Do not ask the user to confirm an empty result. Preserve genuine missing inputs and unsupported semantic requirements.",
                    },
                },
                conversation=conversation,
            )
        if draft.status != "ready":
            return stop(
                draft.status,
                draft.message,
                code="selected_operation_refused"
                if draft.status == "unsupported"
                else None,
            )
        assert draft.plan is not None
        plan = ExecutionPlan(
            session_id=session_id,
            graph_id=request.graph_id,
            problem_id=decision.problem_id,
            operation_id=decision.operation_id,
            **draft.plan.model_dump(),
        )
        # Identity and explicit API values are authoritative; the model may only
        # fill values the user did not provide.
        merged_parameters = dict(plan.parameters)
        if (
            plan.operation_id == "temporal-motif-mining"
            and "max_time_span" not in request.parameters
        ):
            if intent.time_window is None or intent.time_unit == "unspecified":
                return stop(
                    "needs_information",
                    "How much time may pass between the first and last event, and is that seconds or milliseconds?",
                )
            source_unit = context["timestamp_unit"]
            if intent.time_unit != "native" and source_unit == "unspecified":
                return stop(
                    "needs_information",
                    "Do the event timestamps use seconds or milliseconds? Declare that unit in the upload options so I can apply your time window correctly.",
                )
            factor = Decimal(1)
            if intent.time_unit != "native" and source_unit != intent.time_unit:
                factor = (
                    Decimal(1000) if source_unit == "milliseconds" else Decimal("0.001")
                )
            converted = Decimal(str(intent.time_window)) * factor
            if converted != converted.to_integral_value():
                return stop(
                    "unsupported",
                    "That time window cannot be represented exactly in this dataset's integer timestamp units.",
                )
            # Derive from the original requested window, never reconvert the
            # model's potentially already-converted parameter.
            merged_parameters["max_time_span"] = int(converted)
        merged_parameters.update(request.parameters)
        merged_auxiliary = dict(plan.auxiliary_inputs)
        merged_auxiliary.update(inferred_inputs)
        merged_auxiliary.update(request.auxiliary_inputs)
        optional_outputs = (
            request.optional_outputs
            if "optional_outputs" in request.model_fields_set
            else plan.optional_outputs
        )
        plan = plan.model_copy(
            update={
                "session_id": session_id,
                "graph_id": request.graph_id,
                "problem_id": decision.problem_id,
                "operation_id": decision.operation_id,
                "backend_id": request.backend_id or "auto",
                "parameters": merged_parameters,
                "optional_outputs": optional_outputs,
                "auxiliary_inputs": merged_auxiliary,
                "allow_directed_projection": request.allow_directed_projection,
                "application_intent": intent,
                "collect_statistics": True,
            }
        )
        plan = bind_unique_required_auxiliary_inputs(
            plan,
            self.catalog.operation(decision.operation_id),
            available_files,
            protected_names=set(request.auxiliary_inputs),
        )
        try:
            plan = self.validator.validate(plan, for_execution=False)
        except PlanValidationError as error:
            return stop(
                "unsupported",
                "I cannot safely answer that exact question with this computation. "
                + str(error),
                code="invalid_plan",
                errors=error.errors,
            )
        try:
            prepare_operation_graph(projected, plan)
        except ProfileInputError as error:
            return stop(error.status, str(error))
        if (
            raw_graph["graph"]["directed"]
            and plan.operation_id not in DIRECTION_PRESERVING_OPERATIONS
            and not plan.allow_directed_projection
        ):
            return stop(
                "needs_information",
                "These connections have a direction, but this analysis requires two-way relationships. If that meaning fits your question, enable 'Treat directed links as two-way' in the browser or enter /direction two-way in the CLI, then ask again. Otherwise I cannot use this computation safely.",
            )
        message = (
            f"Ready to answer: {request.message}"
            if not plan.missing_inputs
            else self._missing_input_question(plan.missing_inputs)
        )
        if plan.missing_inputs:
            return stop("needs_information", message)
        return _DraftAttempt(
            PlanningOutcome(
                message=message,
                decision=decision,
                plan=plan,
                plans=[plan],
                status="ready",
            )
        )

    def _record_nonready(self, session_id, request, decision, status, message):
        self.database.add_message(
            session_id,
            "user",
            {"message": request.message, "graph_id": request.graph_id},
            LLMMode.planner.value,
        )
        self.database.add_message(
            session_id,
            "assistant",
            {
                "message": message,
                "status": status,
                "graph_id": request.graph_id,
                "pending_question": request.message,
                "decision": decision.model_dump(mode="json"),
            },
            LLMMode.planner.value,
        )
        return PlanningOutcome(message=message, decision=decision, status=status)

    @staticmethod
    def _pending_request(conversation, graph_id):
        """Only the latest assistant turn on this graph may be continued.

        Failed/clarified intent is context, never silently promoted to the
        completed result's active constraints or carried into another graph.
        """
        last = next(
            (item for item in reversed(conversation) if item["role"] == "assistant"),
            None,
        )
        if last is None:
            return None
        payload = last.get("payload", {})
        if (
            payload.get("graph_id") != graph_id
            or payload.get("status") not in {"needs_information", "unsupported"}
            or not payload.get("pending_question")
        ):
            return None
        return {
            "question": payload["pending_question"],
            "status": payload["status"],
            "clarification_or_limitation": payload.get("message"),
            "intent": (payload.get("decision") or {}).get("intent"),
            "usage": "Use only when the current user reply continues or corrects this request. It has not executed; do not silently adopt its constraints for a different question.",
        }

    @staticmethod
    def _missing_input_question(names):
        questions = {
            "source": "Where should the flow start? Choose the source entity from your data.",
            "sink": "Where should the flow end? Choose a different destination entity from your data.",
            "connectivity_mode": "Should a group require paths in both directions between its members, or should connections count regardless of direction?",
            "left_partition": "Which records belong on each side of the relationship (for example customers and products)? Add a type to those records or upload their membership list.",
            "k": "How many members or partners should each requested group have?",
            "max_time_span": "How much time may pass between the first and last event, and what units do the timestamps use?",
            "query_graph": "Please provide an example of the relationship pattern you want to find.",
            "motifs": "Please provide the relationship patterns you want to count.",
            "updates": "Please provide the connections that were added or removed.",
        }
        return " ".join(
            questions.get(
                name,
                "Please describe the missing selection or threshold in your application terms.",
            )
            for name in names
        )

    async def interpret(
        self,
        result_id: str,
        *,
        user_message: str = "Interpret this result and select useful visualizations.",
    ) -> ResultRecord:
        result = self.database.get_result(result_id)
        with self.database.history.scope(
            result.session_id,
            "interpretation",
            {
                "result_id": result_id,
                "message": user_message,
            },
        ):
            return await self._interpret(result_id, user_message=user_message)

    async def _interpret(self, result_id: str, *, user_message: str) -> ResultRecord:
        result = self.database.get_result(result_id)
        job = self.database.get_job(result.job_id)
        graph_record = self.database.get_file(job.plan.graph_id)
        graph = self.graph_store.read_graph(job.plan.graph_id, result.session_id)
        answer = build_answer(
            graph, job.plan, result.payload, source_hash=graph_record.sha256
        )
        is_final = job.step_index == job.step_count - 1
        if job.analysis_id and job.step_count > 1 and is_final:
            siblings = [
                item
                for item in self.database.list_jobs(result.session_id)
                if item.analysis_id == job.analysis_id
                and item.step_index < job.step_index
            ]
            steps = {}
            for sibling in siblings:
                if not sibling.result_id:
                    raise ValueError("A supporting analysis did not produce a result.")
                previous = self.database.get_result(sibling.result_id)
                steps[f"step_{sibling.step_index}"] = previous.answer
            steps[f"step_{job.step_index}"] = answer
            all_facts = [
                {**fact, "id": f"{step_id}_{fact['id']}"}
                for step_id, step in steps.items()
                for fact in step["facts"]
            ]
            answer = {
                **answer,
                "question": next(iter(steps.values()))["question"],
                "steps": steps,
                "facts": all_facts,
                "limitations": list(
                    dict.fromkeys(
                        value
                        for step in steps.values()
                        for value in step["limitations"]
                    )
                ),
            }
        prepare_analysis(answer)
        defaults = answer_visualizations(answer)
        self.database.history.current("answer.materialized", answer)
        # Persist verified facts even when inference subsequently fails.
        self.database.update_result(result.model_copy(update={"answer": answer}))
        session = self.database.get_session(result.session_id)
        payload = analyst_payload(
            answer, defaults, self.catalog, session.domain_id, user_message
        )
        source = "offline_rules"
        narrative = None
        generated_views = []
        if is_final:
            source = "llm" if self.settings.llm_enabled else "offline_rules"
            try:
                for attempt in range(2):
                    narrative = await self._generate(
                        mode=LLMMode.analyst,
                        schema=GroundedNarrative,
                        user_payload=payload,
                        conversation=self.database.messages(result.session_id),
                    )
                    try:
                        known_facts = {
                            fact["id"] for fact in payload["answer"]["facts"]
                        }
                        known_followups = {
                            item["id"] for item in payload["followup_options"]
                        }
                        references = set(narrative.fact_ids)
                        for statement in (
                            ([narrative.summary] if narrative.summary else [])
                            + narrative.findings
                            + narrative.charts
                        ):
                            references.update(statement.fact_ids)
                        if (
                            not references <= known_facts
                            or not set(narrative.followup_ids) <= known_followups
                        ):
                            raise ValueError(
                                "The explanation references evidence or follow-ups absent from its input."
                            )
                        generated_views = await asyncio.to_thread(
                            validate_narrative,
                            narrative,
                            answer,
                            defaults,
                            set(self.catalog.instructions),
                        )
                        break
                    except ValueError as error:
                        self.database.history.current(
                            "analyst.validation",
                            {"attempt": attempt + 1, "error": str(error)},
                        )
                        if attempt:
                            raise LLMError(
                                f"Analyst validation failed after repair: {error}"
                            ) from error
                        payload = {
                            **payload,
                            "validation_feedback": str(error),
                            "repair_guidance": CHART_REPAIR_GUIDANCE,
                            "previous_draft": narrative.model_dump(mode="json"),
                        }
            except LLMError as error:
                source = "fallback"
                narrative = None
                self.database.history.current(
                    "model.fallback",
                    {"reason": str(error), "provider": "verified_facts"},
                )
                answer["limitations"].append(
                    "The language model was unavailable or returned an invalid response. These findings and views are computed directly from the result and original data."
                )
        # Recipes are validated against the same enriched dataset as the facts.
        selected = generated_views + [
            view for view in defaults if narrative and view.id in narrative.view_ids
        ]
        # Keep the deterministic operation-specific inspection views, including
        # those belonging to supporting analyses. Narration may prioritize them
        # but cannot remove access to computed values or linked exploration.
        selected.extend(view for view in defaults if view not in selected)
        safe_views = sanitize_visualizations(
            selected or defaults, {"answer": answer, **result.payload}
        )
        interpretation = answer_interpretation(
            answer,
            safe_views,
            fact_ids=narrative.fact_ids if narrative else None,
            hypotheses=narrative.hypotheses if narrative else None,
            followups=narrative.suggested_followups if narrative else None,
            followup_ids=narrative.followup_ids if narrative else None,
        )
        if narrative:
            apply_narrative(interpretation, narrative, answer)
        self.database.history.current(
            "visualization.selection",
            {
                "proposed_ids": narrative.view_ids if narrative else [],
                "available": defaults,
                "accepted": safe_views,
                "fallback": narrative is None or not selected,
            },
        )
        updated = result.model_copy(
            update={
                "answer": answer,
                "interpretation": interpretation,
                "interpretation_source": source,
            }
        )
        self.database.update_result(updated)
        with self.database.history.best_effort("answer.report"):
            report = self.database.history.text_snapshot(
                result.session_id,
                f"results/{result.id}/answer.html",
                render_report(updated),
            )
            self.database.history.current(
                "answer.report",
                {
                    "path": f"results/{result.id}/answer.html",
                    "sha256": self.database.history.digest(report),
                },
            )
        self.database.history.snapshot(
            result.session_id, f"results/{result.id}/answer.json", answer
        )
        self.database.add_message(
            result.session_id,
            "assistant",
            {
                "result_id": result.id,
                "question": answer["question"],
                "interpretation": interpretation.model_dump(mode="json"),
            },
            LLMMode.analyst.value,
        )
        return updated

    async def handle_completed_result(
        self, result: ResultRecord, plan: ExecutionPlan
    ) -> ResultRecord:
        return await self.interpret(
            result.id,
            user_message=plan.application_intent.objective
            if plan.application_intent
            else "Explain the computed result.",
        )

    async def chat(self, session_id: str, request: ChatRequest) -> ChatResponse:
        self.database.get_session(session_id)
        history = self.database.history
        is_command = command_name(request.message) is not None
        previous = history.last_chat(session_id) if is_command else None
        kind = "feedback_command" if is_command else "chat"
        with history.scope(session_id, kind, request) as turn_id:
            if is_command:
                response = dispatch_command(
                    self.database, self.settings, session_id, request, previous
                )
            else:
                history.current("deployment.context", self.deployment_info())
                response = await self._chat(session_id, request)
            response = response.model_copy(update={"turn_id": turn_id})
            history.current(f"{kind}.response", response)
            return response

    def deployment_info(self):
        return {
            "version": self.settings.deployment_version,
            "routing_model": self.settings.active_routing_model,
            "adapter_sha256": self.settings.llm_route_adapter_sha256
            if self.settings.routing_adapter_active
            else None,
            "routing_contract_version": self.settings.routing_contract_version,
            "routing_experimental": self.settings.routing_adapter_experimental,
            "adapter_evaluated_contract_version": "legacy-20"
            if self.settings.routing_adapter_active
            else None,
            "answer_model": self.settings.llm_analyst_model or self.settings.llm_model,
            "planner_model": self.settings.llm_planner_model or self.settings.llm_model,
            "shared_base_model": self.settings.llm_model,
            "dual_adapters_active": self.settings.dual_adapters_active,
            "llm_enabled": self.settings.llm_enabled,
            "routing_scope": "understanding, routing, planning and recovery"
            if self.settings.dual_adapters_active
            else "RouteDecision"
            if self.settings.routing_adapter_active
            else "base",
        }

    async def _chat(self, session_id: str, request: ChatRequest) -> ChatResponse:
        self.database.get_session(session_id)
        result = (
            self.database.get_result(request.result_id) if request.result_id else None
        )
        if result is not None and result.session_id != session_id:
            raise ValueError("result_id must identify a result from this session")
        if result is None and request.mode == "analyst" and not request.graph_id:
            result = self.database.latest_result(session_id)
        graph_id = request.graph_id or (
            self.database.get_job(result.job_id).plan.graph_id
            if result
            else self._latest_graph_id(session_id)
        )
        if graph_id:
            graph = self.database.get_file(graph_id)
            if graph.session_id != session_id or graph.role != FileRole.graph:
                raise ValueError(
                    "graph_id must identify a graph uploaded to this session"
                )
            if (
                result
                and self.database.get_job(result.job_id).plan.graph_id != graph_id
            ):
                if request.mode == "analyst":
                    raise ValueError(
                        "result_id must identify a result from the selected graph"
                    )
                # A newly selected/uploaded graph replaces the browser's stale
                # result selection. Never transfer its filters to this dataset.
                result = None
            result = self._context_result(
                session_id, graph_id, result.id if result else None
            )
        mode = request.mode
        followup = None
        if mode == "auto":
            mode = "planner"
            if result is not None:
                previous_plan = self.database.get_job(result.job_id).plan
                previous_graph = self.database.get_file(previous_plan.graph_id)
                state = self._conversation_state(
                    previous_graph, result, self.database.messages(session_id)
                )
                self.database.history.current("conversation.context", state)
                turn = await self._generate(
                    mode=LLMMode.planner,
                    schema=TurnDecision,
                    user_payload={
                        "message": request.message,
                        "previous_question": result.answer.get("question"),
                        "previous_operation": result.operation_id,
                        "previous_parameters": previous_plan.parameters,
                        "previous_output_requests": previous_plan.optional_outputs,
                        "pending_request": self._pending_request(
                            self.database.messages(session_id), previous_plan.graph_id
                        ),
                        "graph_context": getattr(
                            previous_graph.metadata, "semantic_context", {}
                        ),
                        "active_constraints": previous_plan.application_intent.model_dump(
                            mode="json"
                        )
                        if previous_plan.application_intent
                        else None,
                        "previous_facts": result.answer.get("facts", [])[:8],
                        "graph_id": graph_id,
                        "conversation_state": state,
                    },
                    conversation=self.database.messages(session_id),
                )
                if turn.action == "clarify":
                    # A shallow action classifier must not invent missing
                    # inputs or preempt the planner's richer capability check.
                    # Keep the user's original question; the full planner can
                    # still ask a genuine domain-language clarification.
                    self.database.history.current(
                        "conversation.routing_uncertain",
                        {
                            "question": request.message,
                            "decision": turn.model_dump(mode="json"),
                        },
                    )
                elif turn.action == "explain":
                    mode = "analyst"
                else:
                    followup = turn
        if mode == "analyst":
            if result is None:
                raise ValueError("analysis mode requires a completed result")
            self.database.add_message(
                session_id, "user", {"message": request.message}, LLMMode.analyst.value
            )
            updated = await self.interpret(result.id, user_message=request.message)
            return ChatResponse(
                mode=LLMMode.analyst,
                message=updated.interpretation.summary,
                interpretation=updated.interpretation,
                interpretation_source=updated.interpretation_source,
                result_id=updated.id,
            )
        if graph_id is None:
            return ChatResponse(
                mode=LLMMode.planner,
                message="Upload your relationship data before asking for an analysis.",
                planning_status="needs_information",
            )
        outcome = await self.plan(
            session_id,
            PlanRequest(
                message=request.message,
                graph_id=graph_id,
                result_id=result.id if result else None,
                allow_directed_projection=request.allow_directed_projection,
            ),
            followup=followup,
        )
        if outcome.status != "ready" or outcome.plan is None or not request.execute:
            return ChatResponse(
                mode=LLMMode.planner,
                message=outcome.message,
                plan=outcome.plan,
                planning_status=outcome.status,
            )
        self.jobs.runner.require_ready()
        normalized = [
            self.validator.validate(
                plan,
                compiled_backends=(
                    self.jobs.runner.compiled_backends_for(plan.operation_id)
                    if self.jobs.runner.capabilities.binary_available
                    else None
                ),
                for_execution=True,
            )
            for plan in outcome.plans
        ]
        analysis_id = new_id("analysis")
        jobs = await self.jobs.enqueue_many(normalized, analysis_id=analysis_id)
        return ChatResponse(
            mode=LLMMode.planner,
            message=f"I'll answer your question using {len(jobs)} validated analysis step{'s' if len(jobs) != 1 else ''}.",
            plan=normalized[0],
            job_id=jobs[-1].id,
            job_ids=[job.id for job in jobs],
            planning_status="ready",
        )

    def _latest_graph_id(self, session_id: str) -> str | None:
        graphs = [
            item
            for item in self.database.list_files(session_id)
            if item.role == FileRole.graph
        ]
        return graphs[-1].id if graphs else None
