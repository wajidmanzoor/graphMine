from __future__ import annotations

import json
import re
from typing import Any, ClassVar, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings
from .models import ExecutionPlan, Interpretation, LLMMode, RouteDecision

T = TypeVar("T", bound=BaseModel)


PLANNER_SYSTEM_PROMPT = """You are the planning skill for GraphMine, a validated GPU graph-mining system.
Translate the user's domain-specific request into the exact requested JSON schema.
Use only problem IDs, operations, backends, parameters, outputs, and file IDs present in the supplied context.
For ExecutionPlan.parameters, use only exact keys from operation_context.program_instruction.parameters.
For ExecutionPlan.optional_outputs, include every user-requested result whose exact key appears in operation_context.program_instruction.optional_outputs.
Represent behaviors such as listing instances through optional_outputs when the execution contract exposes no corresponding boolean parameter.
For ExecutionPlan.auxiliary_inputs, use only exact keys and matching file IDs from the available-files list.
The program_instruction is the sole executable allowlist; never copy a broader research parameter into a plan.
Distinguish maximum clique (a largest clique) from maximal clique enumeration (all inclusion-maximal cliques).
Never invent a required semantic parameter. Report ambiguity or missing information instead.
Do not generate shell commands. Do not change semantic parameters for speed.
Unsupported problems must remain unsupported; never substitute a nearby operation.
The selected domain provides vocabulary and interpretation context, but formal problem definitions are authoritative.
For an ExecutionPlan, keep rationale under 120 words and do not predict the algorithm's result.
"""


ANALYST_SYSTEM_PROMPT = """You are the analysis skill for GraphMine.
Interpret only the supplied structured result and bounded result summary. Ground every concrete claim in a data_ref.
Every evidence data_ref must be a dot path rooted at result, result_summary, graph_metadata, execution_plan, problem, or domain. Use numeric components for list indexes.
Do not infer the graph's vertex or edge count from a returned clique, community, match, or count; use graph_metadata, and say the size is unknown when metadata is absent.
An ignored attribute means the current algorithm did not use it, not that the uploaded graph lacked it.
allow_directed_projection=false means directed input is rejected when an undirected graph is required; it does not make directed edges bidirectional.
Only set requires_new_execution=true when the user's current message explicitly asks to run, rerun, or change a computation. Do not turn a request for explanation or limitations into a new job.
Any proposed computation must use an operation in supported_operations; never invent capabilities, parameters, or input semantics.
State limitations, truncation, normalization warnings, and incomplete materialization clearly.
Select useful visualizations from the allowed visualization schema; never emit JavaScript or executable code.
If the follow-up changes the computation, set requires_new_execution=true and describe the proposed request.
Use domain terminology where helpful without changing the mathematical meaning of the result.
"""


class LLMError(RuntimeError):
    pass


class OpenAICompatibleModel:
    """One loaded Qwen model with separate planner and analyst skills."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def available(self) -> bool:
        try:
            response = await self._client.get("/models", timeout=3.0)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def generate(
        self,
        *,
        mode: LLMMode,
        schema: type[T],
        user_payload: dict[str, Any],
        conversation: list[dict[str, Any]] | None = None,
    ) -> T:
        system = (
            PLANNER_SYSTEM_PROMPT if mode == LLMMode.planner else ANALYST_SYSTEM_PROMPT
        )
        if schema is RouteDecision:
            system += (
                "\nThis is a bounded routing classification. Keep the explanation "
                "under 80 words."
            )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for item in (conversation or [])[-12:]:
            role = item.get("role")
            payload = item.get("payload", {})
            if role in {"user", "assistant"}:
                messages.append(
                    {
                        "role": role,
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                )
        messages.append(
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }
        )
        if schema is RouteDecision:
            reasoning_effort = self.settings.llm_route_reasoning_effort
            max_completion_tokens = self.settings.llm_route_max_tokens
        elif schema is ExecutionPlan:
            reasoning_effort = self.settings.llm_plan_reasoning_effort
            max_completion_tokens = self.settings.llm_plan_max_tokens
        else:
            reasoning_effort = self.settings.llm_analyst_reasoning_effort
            max_completion_tokens = self.settings.llm_analyst_max_tokens
        output_schema = schema.model_json_schema()
        if schema is ExecutionPlan:
            properties = output_schema.get("properties", {})
            output_schema["required"] = list(properties)
            for specification in properties.values():
                if isinstance(specification, dict):
                    specification.pop("default", None)
        request = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.0 if schema is RouteDecision else 1.0,
            "top_p": 1.0 if schema is RouteDecision else 0.95,
            "top_k": 0 if schema is RouteDecision else 20,
            "seed": 0,
            "reasoning_effort": reasoning_effort,
            "max_completion_tokens": max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": output_schema,
                },
            },
        }
        try:
            response = await self._client.post("/chat/completions", json=request)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) if isinstance(item, dict) else str(item)
                    for item in content
                )
            content = re.sub(
                r"<think>.*?</think>", "", str(content), flags=re.DOTALL
            ).strip()
            return schema.model_validate_json(content)
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            json.JSONDecodeError,
            ValidationError,
        ) as error:
            raise LLMError(f"local LLM request failed: {error}") from error


class RuleBasedModel:
    """Offline/testing fallback implementing the same two skill boundary."""

    _routes: ClassVar[list[tuple[str, str, str]]] = [
        (
            r"maximal\s+biclique|bipartite.*clique",
            "maximal_biclique_enumeration",
            "maximal-bicliques",
        ),
        (r"maximum\s+clique|largest\s+clique", "maximum_clique", "maximum-clique"),
        (r"maximal\s+clique", "maximal_clique_enumeration", "maximal-cliques"),
        (r"quasi.?clique", "quasi_clique_mining", "quasi-cliques"),
        (
            r"k.?clique|cliques?\s+of\s+size",
            "k_clique_counting_enumeration",
            "k-cliques",
        ),
        (
            r"dynamic.*triangle|triangle.*updates?",
            "triangle_counting_listing",
            "dynamic-triangle-counting",
        ),
        (r"triangle", "triangle_counting_listing", "triangle-counting"),
        (r"k.?core|core decomposition|degeneracy", "k_core_decomposition", "k-core"),
        (
            r"temporal.*motif|time.*motif",
            "temporal_motif_mining",
            "temporal-motif-mining",
        ),
        (r"motif", "graph_motif_counting", "graph-motifs"),
        (
            r"subgraph|pattern match|isomorph",
            "subgraph_isomorphism",
            "subgraph-isomorphism",
        ),
        (r"communit|cluster", "community_detection", "community-detection"),
        (
            r"betweenness|central|influential|important (?:node|vertex)",
            "centrality_influential_node_mining",
            "betweenness-centrality",
        ),
    ]

    async def close(self) -> None:
        return None

    async def available(self) -> bool:
        return True

    async def generate(
        self,
        *,
        mode: LLMMode,
        schema: type[T],
        user_payload: dict[str, Any],
        conversation: list[dict[str, Any]] | None = None,
    ) -> T:
        if schema is RouteDecision:
            message = str(user_payload.get("message", "")).lower()
            for pattern, problem, operation in self._routes:
                if re.search(pattern, message):
                    return schema.model_validate(
                        {
                            "problem_id": problem,
                            "operation_id": operation,
                            "supported": True,
                            "confidence": 0.8,
                            "ambiguity": [],
                            "missing_information": [],
                            "explanation": "Matched an explicit graph-mining intent.",
                        }
                    )
            return schema.model_validate(
                {
                    "problem_id": None,
                    "operation_id": None,
                    "supported": False,
                    "confidence": 0.0,
                    "ambiguity": [],
                    "missing_information": ["graph problem"],
                    "explanation": "The offline fallback could not identify the requested problem.",
                }
            )
        if schema is ExecutionPlan:
            operation = user_payload["selected_operation"]
            instruction = user_payload["operation_context"]["program_instruction"]
            parameters = dict(user_payload.get("supplied_parameters", {}))
            requested_backend = user_payload.get("requested_backend") or "auto"
            for name, specification in instruction["parameters"].items():
                if (
                    name not in parameters
                    and "default" in specification
                    and (
                        not specification.get("backend")
                        or requested_backend == specification["backend"]
                    )
                ):
                    parameters[name] = specification["default"]
            auxiliary = dict(user_payload.get("supplied_auxiliary_inputs", {}))
            missing = [
                name
                for name, specification in instruction["auxiliary_inputs"].items()
                if specification.get("required") and not auxiliary.get(name)
            ]
            for name, specification in instruction["parameters"].items():
                if specification.get("required") and name not in parameters:
                    missing.append(name)
            return schema.model_validate(
                {
                    "session_id": user_payload["session_id"],
                    "graph_id": user_payload["graph_id"],
                    "problem_id": operation["problem_id"],
                    "operation_id": operation["operation_id"],
                    "backend_id": requested_backend,
                    "parameters": parameters,
                    "optional_outputs": user_payload.get(
                        "requested_optional_outputs", []
                    ),
                    "auxiliary_inputs": auxiliary,
                    "allow_directed_projection": user_payload.get(
                        "allow_directed_projection", False
                    ),
                    "missing_inputs": missing,
                    "rationale": "Offline deterministic planning fallback.",
                }
            )
        if schema is Interpretation:
            operation_id = user_payload["operation_id"]
            return schema.model_validate(
                {
                    "summary": f"GraphMine completed {operation_id} successfully.",
                    "findings": [
                        "The structured result is available for interactive inspection."
                    ],
                    "limitations": [
                        "LLM inference is disabled; this is a deterministic fallback summary."
                    ],
                    "evidence": [
                        {
                            "claim": "The computation succeeded.",
                            "data_ref": "ok",
                            "value": True,
                        }
                    ],
                    "suggested_followups": [
                        "Inspect the result table or enable the local Qwen server for a domain-specific explanation."
                    ],
                    "visualizations": user_payload.get("default_visualizations", []),
                }
            )
        raise LLMError(f"offline model does not implement schema {schema.__name__}")
