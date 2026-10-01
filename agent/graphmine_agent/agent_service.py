from __future__ import annotations

import json
import re
from typing import Any

from .catalog import Catalog
from .config import Settings
from .database import Database, RecordNotFound
from .graph_store import GraphStore
from .jobs import JobManager
from .llm import LLMError, OpenAICompatibleModel, RuleBasedModel
from .models import (
    ChatRequest,
    ChatResponse,
    EvidenceItem,
    ExecutionPlan,
    FileRole,
    Interpretation,
    LLMMode,
    PlanningOutcome,
    PlanRequest,
    ResultRecord,
    RouteDecision,
)
from .planning import PlanValidator, normalize_route
from .results import summarize_result
from .visualization import (
    default_visualizations,
    sanitize_visualizations,
)


def _resolve_data_ref(context: dict[str, Any], data_ref: str) -> tuple[str, Any]:
    reference = data_ref.strip()
    if reference == "ok" or reference.startswith(
        ("output.", "provenance.", "warnings.")
    ):
        reference = f"result.{reference}"
    normalized = re.sub(r"\[(\d+)\]", r".\1", reference)
    components = normalized.split(".")
    if not components or components[0] not in {
        "result",
        "result_summary",
        "graph_metadata",
        "execution_plan",
        "problem",
        "domain",
    }:
        raise KeyError(reference)
    current: Any = context
    for component in components:
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, list) and component.isdigit():
            current = current[int(component)]
        else:
            raise KeyError(reference)
    return normalized, current


def _bounded_evidence_value(value: Any) -> Any:
    try:
        if len(json.dumps(value, ensure_ascii=False)) <= 2_000:
            return value
    except (TypeError, ValueError):
        return str(value)[:2_000]
    return summarize_result(value, item_limit=10)


def _sanitize_evidence(
    evidence: list[EvidenceItem], context: dict[str, Any]
) -> list[EvidenceItem]:
    safe: list[EvidenceItem] = []
    for item in evidence:
        try:
            reference, value = _resolve_data_ref(context, item.data_ref)
        except (KeyError, IndexError):
            continue
        safe.append(
            item.model_copy(
                update={
                    "data_ref": reference,
                    "value": _bounded_evidence_value(value),
                }
            )
        )
    return safe


class AgentService:
    """Stateful two-skill orchestration around one local model instance."""

    _execution_followup = re.compile(
        r"\b(run|rerun|re-run|calculate|compute|try|use .*backend|change .* to|set k|with k)\b",
        re.IGNORECASE,
    )

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
            OpenAICompatibleModel(settings)
            if settings.llm_enabled
            else RuleBasedModel()
        )

    async def close(self) -> None:
        await self.model.close()

    async def plan(self, session_id: str, request: PlanRequest) -> PlanningOutcome:
        session = self.database.get_session(session_id)
        graph = self.database.get_file(request.graph_id)
        if graph.session_id != session_id or graph.role != FileRole.graph:
            raise ValueError("graph_id must identify a graph uploaded to this session")
        conversation = self.database.messages(session_id)
        route_payload = {
            "task": "Identify exactly one formal graph problem and runnable operation, or report ambiguity/unsupported intent.",
            "message": request.message,
            "graph_metadata": (
                graph.metadata.model_dump(mode="json")
                if hasattr(graph.metadata, "model_dump")
                else graph.metadata
            ),
            "routing_context": self.catalog.routing_context(session.domain_id),
        }
        decision = await self.model.generate(
            mode=LLMMode.planner,
            schema=RouteDecision,
            user_payload=route_payload,
            conversation=conversation,
        )
        decision = normalize_route(self.catalog, decision)
        if (
            not decision.supported
            or not decision.problem_id
            or not decision.operation_id
        ):
            message = decision.explanation
            if decision.ambiguity:
                message += " Please clarify: " + "; ".join(decision.ambiguity)
            if decision.missing_information:
                message += " Missing: " + ", ".join(decision.missing_information)
            self.database.add_message(
                session_id, "user", {"message": request.message}, LLMMode.planner.value
            )
            self.database.add_message(
                session_id,
                "assistant",
                {"message": message, "decision": decision.model_dump(mode="json")},
                LLMMode.planner.value,
            )
            return PlanningOutcome(message=message, decision=decision)

        available_files = [
            {
                "id": item.id,
                "role": item.role.value,
                "name": item.original_name,
                "metadata": (
                    item.metadata.model_dump(mode="json")
                    if hasattr(item.metadata, "model_dump")
                    else item.metadata
                ),
            }
            for item in self.database.list_files(session_id)
        ]
        planning_payload = {
            "task": "Produce a complete GraphMine ExecutionPlan. Preserve user-supplied values. Use missing_inputs rather than inventing required values.",
            "message": request.message,
            "session_id": session_id,
            "graph_id": request.graph_id,
            "domain": self.catalog.domain(session.domain_id).model_dump(mode="json"),
            "graph_metadata": (
                graph.metadata.model_dump(mode="json")
                if hasattr(graph.metadata, "model_dump")
                else graph.metadata
            ),
            "selected_operation": {
                "problem_id": decision.problem_id,
                "operation_id": decision.operation_id,
            },
            "operation_context": self.catalog.operation_context(decision.operation_id),
            "available_files": available_files,
            "requested_backend": request.backend_id,
            "supplied_parameters": request.parameters,
            "requested_optional_outputs": request.optional_outputs,
            "supplied_auxiliary_inputs": request.auxiliary_inputs,
            "allow_directed_projection": request.allow_directed_projection,
        }
        plan = await self.model.generate(
            mode=LLMMode.planner,
            schema=ExecutionPlan,
            user_payload=planning_payload,
            conversation=conversation,
        )
        # Identity and explicit API values are authoritative; the model may only
        # fill values the user did not provide.
        merged_parameters = dict(plan.parameters)
        merged_parameters.update(request.parameters)
        merged_auxiliary = dict(plan.auxiliary_inputs)
        merged_auxiliary.update(request.auxiliary_inputs)
        optional_outputs = request.optional_outputs or plan.optional_outputs
        plan = plan.model_copy(
            update={
                "session_id": session_id,
                "graph_id": request.graph_id,
                "problem_id": decision.problem_id,
                "operation_id": decision.operation_id,
                "backend_id": request.backend_id or plan.backend_id,
                "parameters": merged_parameters,
                "optional_outputs": optional_outputs,
                "auxiliary_inputs": merged_auxiliary,
                "allow_directed_projection": request.allow_directed_projection,
            }
        )
        plan = self.validator.validate(plan, for_execution=False)
        message = (
            "The execution plan is ready."
            if not plan.missing_inputs
            else "The plan needs additional input: " + ", ".join(plan.missing_inputs)
        )
        self.database.add_message(
            session_id, "user", {"message": request.message}, LLMMode.planner.value
        )
        self.database.add_message(
            session_id,
            "assistant",
            {"message": message, "plan": plan.model_dump(mode="json")},
            LLMMode.planner.value,
        )
        return PlanningOutcome(message=message, decision=decision, plan=plan)

    async def interpret(
        self,
        result_id: str,
        *,
        user_message: str = "Interpret this result and select useful visualizations.",
    ) -> ResultRecord:
        result = self.database.get_result(result_id)
        job = self.database.get_job(result.job_id)
        session = self.database.get_session(result.session_id)
        defaults = default_visualizations(result.operation_id, result.payload)
        domain = self.catalog.domain(session.domain_id).model_dump(mode="json")
        problem = self.catalog.problem(job.plan.problem_id)["spec"]
        execution_plan = job.plan.model_dump(mode="json")
        try:
            graph = self.database.get_file(job.plan.graph_id)
            graph_metadata = (
                graph.metadata.model_dump(mode="json")
                if hasattr(graph.metadata, "model_dump")
                else graph.metadata
            )
        except RecordNotFound:
            graph_metadata = None
        supported_operations = []
        for operation_id in sorted(self.catalog.instructions):
            operation = self.catalog.operation(operation_id)
            supported_operations.append(
                {
                    "operation_id": operation.id,
                    "problem_id": operation.problem_id,
                    "description": self.catalog.problem(operation.problem_id)["spec"][
                        "problem_statement"
                    ],
                }
            )
        payload = {
            "task": "Interpret the result and return grounded findings plus a safe visualization plan.",
            "user_message": user_message,
            "domain": domain,
            "operation_id": result.operation_id,
            "problem": problem,
            "execution_plan": execution_plan,
            "graph_metadata": graph_metadata,
            "result_summary": result.summary,
            "supported_operations": supported_operations,
            "default_visualizations": [
                item.model_dump(mode="json") for item in defaults
            ],
        }
        try:
            interpretation = await self.model.generate(
                mode=LLMMode.analyst,
                schema=Interpretation,
                user_payload=payload,
                conversation=self.database.messages(result.session_id),
            )
        except LLMError:
            fallback = RuleBasedModel()
            interpretation = await fallback.generate(
                mode=LLMMode.analyst,
                schema=Interpretation,
                user_payload=payload,
            )
        safe_views = sanitize_visualizations(
            interpretation.visualizations, result.payload
        )
        if not safe_views:
            safe_views = sanitize_visualizations(defaults, result.payload)
        evidence_context = {
            "result": result.payload,
            "result_summary": result.summary,
            "graph_metadata": graph_metadata,
            "execution_plan": execution_plan,
            "problem": problem,
            "domain": domain,
        }
        safe_evidence = _sanitize_evidence(interpretation.evidence, evidence_context)
        if not safe_evidence:
            safe_evidence = [
                EvidenceItem(
                    claim="GraphMine reported whether execution succeeded.",
                    data_ref="result.ok",
                    value=result.payload.get("ok"),
                )
            ]
        explicitly_requests_execution = bool(
            self._execution_followup.search(user_message)
        )
        interpretation = interpretation.model_copy(
            update={
                "visualizations": safe_views,
                "evidence": safe_evidence,
                "requires_new_execution": (
                    interpretation.requires_new_execution
                    and explicitly_requests_execution
                ),
                "proposed_request": (
                    interpretation.proposed_request
                    if interpretation.requires_new_execution
                    and explicitly_requests_execution
                    else None
                ),
            }
        )
        updated = result.model_copy(update={"interpretation": interpretation})
        self.database.update_result(updated)
        self.database.add_message(
            result.session_id,
            "assistant",
            {
                "result_id": result.id,
                "interpretation": interpretation.model_dump(mode="json"),
            },
            LLMMode.analyst.value,
        )
        return updated

    async def handle_completed_result(
        self, result: ResultRecord, plan: ExecutionPlan
    ) -> ResultRecord:
        return await self.interpret(result.id)

    async def chat(self, session_id: str, request: ChatRequest) -> ChatResponse:
        self.database.get_session(session_id)
        requested_mode = request.mode
        result = (
            self.database.get_result(request.result_id)
            if request.result_id
            else self.database.latest_result(session_id)
        )
        if result is not None and result.session_id != session_id:
            raise ValueError("result_id must identify a result from this session")
        mode = request.mode
        if mode == "auto":
            mode = (
                "analyst"
                if result is not None
                and not self._execution_followup.search(request.message)
                else "planner"
            )
        if mode == "analyst":
            if result is None:
                raise ValueError("analysis mode requires a completed result")
            self.database.add_message(
                session_id, "user", {"message": request.message}, LLMMode.analyst.value
            )
            updated = await self.interpret(result.id, user_message=request.message)
            assert updated.interpretation is not None
            if (
                requested_mode == "auto"
                and updated.interpretation.requires_new_execution
            ):
                return await self.chat(
                    session_id,
                    request.model_copy(
                        update={
                            "message": updated.interpretation.proposed_request
                            or request.message,
                            "mode": "planner",
                            "result_id": None,
                        }
                    ),
                )
            return ChatResponse(
                mode=LLMMode.analyst,
                message=updated.interpretation.summary,
                interpretation=updated.interpretation,
                result_id=updated.id,
            )

        graph_id = request.graph_id or self._latest_graph_id(session_id)
        if graph_id is None:
            return ChatResponse(
                mode=LLMMode.planner,
                message="Upload a graph before asking GraphMine to run an analysis.",
            )
        outcome = await self.plan(
            session_id, PlanRequest(message=request.message, graph_id=graph_id)
        )
        if outcome.plan is None or outcome.plan.missing_inputs or not request.execute:
            return ChatResponse(
                mode=LLMMode.planner,
                message=outcome.message,
                plan=outcome.plan,
            )
        normalized = self.validator.validate(
            outcome.plan,
            compiled_backends=(
                self.jobs.runner.compiled_backends_for(outcome.plan.operation_id)
                if self.jobs.runner.capabilities.binary_available
                else None
            ),
            for_execution=True,
        )
        job = await self.jobs.enqueue(normalized)
        return ChatResponse(
            mode=LLMMode.planner,
            message="The validated plan has been queued for GPU execution.",
            plan=normalized,
            job_id=job.id,
        )

    def _latest_graph_id(self, session_id: str) -> str | None:
        graphs = [
            item
            for item in self.database.list_files(session_id)
            if item.role == FileRole.graph
        ]
        return graphs[-1].id if graphs else None
