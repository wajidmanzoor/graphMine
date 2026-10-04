"""Loopback-only serving of a verified, frozen routing adapter.

Reuses the exact NF4 conversation runtime used in application comparisons.
No evaluation cases are executed, no training occurs, and other model stages
remain on the existing inference service.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .history import HistoryStore
from .learning.adapter_eval import routing_schema
from .learning.adapter_workflows import ConversationRouter
from .llm import ROUTING_SYSTEM_PROMPT, LLMError
from .models import RouteDecision


class RoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any]
    conversation: list[dict[str, Any]] = Field(default_factory=list, max_length=12)


def create_router_app() -> FastAPI:
    suite = Path(os.environ["GRAPHMINE_ROUTER_SUITE"])
    model_name = os.getenv("GRAPHMINE_ROUTER_MODEL", "graphmine-business-v1")
    api_key = os.environ["GRAPHMINE_LLM_API_KEY"]

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
            "routing_contract_version": "legacy-20",
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
        return {"ready": True, **app.state.identity}

    @app.post("/route")
    async def route(body: RoutingRequest):
        if (
            body.payload.get("routing_context", {}).get("contract_version", "legacy-20")
            != "legacy-20"
        ):
            raise HTTPException(
                422,
                "This frozen adapter accepts only its evaluated legacy catalog; use the base router for the expanded catalog.",
            )
        try:
            generated = await asyncio.to_thread(
                app.state.router.route, body.payload, body.conversation, "adapter_nf4"
            )
            if generated["finish_reason"] != "stop":
                raise LLMError("Routing exceeded its output budget")
            decision = RouteDecision.model_validate_json(generated["raw"])
            return {
                "decision": decision.model_dump(mode="json"),
                "identity": app.state.identity,
                "usage": {
                    key: generated[key]
                    for key in ("input_tokens", "output_tokens", "seconds")
                },
            }
        except (ValueError, RuntimeError) as error:
            raise HTTPException(503, str(error)) from error

    return app
