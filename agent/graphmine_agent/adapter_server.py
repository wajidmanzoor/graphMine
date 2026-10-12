"""Loopback-only serving of a verified, frozen routing adapter.

Reuses the exact NF4 conversation runtime used in application comparisons.
Expanded catalog routing is an explicit experimental opt-in with a separately
identified runtime prompt; historical evaluation bindings remain unchanged.
No evaluation cases are executed, no training occurs, and other model stages
remain on the existing inference service.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .history import HistoryStore
from .learning.adapter_eval import routing_schema
from .learning.adapter_workflows import ConversationRouter
from .llm import EXPANDED_ROUTING_SYSTEM_PROMPT, ROUTING_SYSTEM_PROMPT, LLMError
from .models import RouteDecision


class RoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any]
    conversation: list[dict[str, Any]] = Field(default_factory=list, max_length=12)


def create_router_app() -> FastAPI:
    suite = Path(os.environ["GRAPHMINE_ROUTER_SUITE"])
    model_name = os.getenv("GRAPHMINE_ROUTER_MODEL", "graphmine-business-v1")
    api_key = os.environ["GRAPHMINE_LLM_API_KEY"]
    settings = Settings.from_env()
    supported_contracts = ["legacy-20"]
    if settings.llm_route_allow_expanded_catalog:
        contract = settings.routing_contract_version
        if contract != "legacy-20":
            supported_contracts.append(contract)

    def identity_for(contract):
        expanded = contract != "legacy-20"
        prompt = EXPANDED_ROUTING_SYSTEM_PROMPT if expanded else ROUTING_SYSTEM_PROMPT
        return {
            **app.state.identity,
            "routing_contract_version": contract,
            "routing_experimental": expanded,
            "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        }

    @asynccontextmanager
    async def lifespan(app):
        plan = json.loads((suite / "plan.json").read_text())
        run = Path(plan["run"])
        if HistoryStore.digest(run / "run.json") != plan["run_sha256"]:
            raise ValueError("Training configuration changed")
        digest = HistoryStore.digest(run / "adapter/adapter_model.safetensors")
        if (
            digest != plan["adapter_sha256"]
            or digest != os.environ["GRAPHMINE_ROUTER_ADAPTER_SHA256"]
        ):
            raise ValueError("Routing adapter does not match the deployment binding")
        if (
            plan["system_prompt"] != ROUTING_SYSTEM_PROMPT
            or plan["response_schema"] != routing_schema()
        ):
            raise ValueError("Routing prompt/schema differs from the evaluated adapter")
        config = json.loads((run / "run.json").read_text())
        app.state.router = await asyncio.to_thread(
            ConversationRouter, run, config, plan
        )
        app.state.identity = {
            "model": model_name,
            "adapter_sha256": digest,
            "base_model": config["base_model"],
            "precision": "NF4",
            "scope": "RouteDecision",
            "supported_routing_contracts": supported_contracts,
            "evaluated_contract_version": "legacy-20",
            "max_input_tokens": 16384,
        }
        yield

    def authorize(authorization: str | None = Header(default=None)):
        if not authorization or not hmac.compare_digest(
            authorization, f"Bearer {api_key}"
        ):
            raise HTTPException(401, "A valid internal API token is required")

    app = FastAPI(
        title="GraphMine routing adapter",
        lifespan=lifespan,
        dependencies=[Depends(authorize)],
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health")
    async def health():
        return {"ready": True, **identity_for(supported_contracts[-1])}

    @app.post("/route")
    async def route(body: RoutingRequest):
        contract = body.payload.get("routing_context", {}).get(
            "contract_version", "legacy-20"
        )
        if contract not in supported_contracts:
            raise HTTPException(
                422,
                "This adapter does not accept the requested catalog. Expanded routing requires explicit experimental configuration on both services.",
            )
        try:
            generated = await asyncio.to_thread(
                app.state.router.route,
                body.payload,
                body.conversation,
                "adapter_nf4",
                system_prompt=(
                    EXPANDED_ROUTING_SYSTEM_PROMPT
                    if contract != "legacy-20"
                    else ROUTING_SYSTEM_PROMPT
                ),
            )
            if generated["finish_reason"] != "stop":
                raise LLMError("Routing exceeded its output budget")
            decision = RouteDecision.model_validate_json(generated["raw"])
            return {
                "decision": decision.model_dump(mode="json"),
                "identity": identity_for(contract),
                "usage": {
                    key: generated[key]
                    for key in ("input_tokens", "output_tokens", "seconds")
                },
            }
        except (ValueError, RuntimeError) as error:
            raise HTTPException(503, str(error)) from error

    return app
