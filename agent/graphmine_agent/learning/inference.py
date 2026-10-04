"""Auditable structured inference for the learning pipeline, never the live API.

External calls require explicit opt-in, an environment key and a finite per-run
budget. No retries, redirects, tools, uploads or background jobs are used.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from ..config import Settings
from ..history import HistoryStore
from ..models import utc_now
from .codex import CodexRunner, execution_policy, parse_stream
from .teacher import local_endpoint

# Published standard text rates checked 2026-10-03; cost reservations use twice
# the input rate to allow for cache writes/overhead. These are not billing quotes.
OPENAI_MODELS = {
    "gpt-6.1-sol": {"input_per_million": 2.0, "output_per_million": 10.0},
    "gpt-6-astra": {"input_per_million": 10.0, "output_per_million": 50.0},
}
PRICING_SOURCE = "https://developers.openai.com/api/docs/models/compare"


@dataclass(frozen=True)
class ModelProfile:
    provider: Literal["local", "openai", "codex"]
    model: str
    base_url: str | None = None
    max_output_tokens: int = 4096

    def __post_init__(self):
        if self.provider not in {"local", "openai", "codex"}:
            raise ValueError("Provider must be local, openai or codex")
        if not self.model.strip() or not 512 <= self.max_output_tokens <= 8192:
            raise ValueError(
                "A model name and a 512-8192 output-token limit are required"
            )
        if self.provider == "local":
            if not self.base_url:
                raise ValueError("A loopback URL is required for local models")
            local_endpoint(self.base_url)
        elif self.model not in OPENAI_MODELS or self.base_url is not None:
            raise ValueError(
                "External profiles must use a documented OpenAI model and the fixed OpenAI endpoint"
            )

    def public(self) -> dict:
        value = {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url
            if self.provider == "local"
            else "https://api.openai.com/v1",
            "max_output_tokens": self.max_output_tokens,
            "reasoning_effort": "none" if self.provider == "local" else "low",
        }
        if self.provider == "codex":
            value["base_url"] = "codex://chatgpt"
            value["execution_policy"] = execution_policy()
        return value


@dataclass
class RequestBudget:
    maximum_usd: float | None = None
    max_calls: int = 100
    reserved_usd: float = 0.0
    calls: int = 0
    stopped: bool = False

    def __post_init__(self):
        if not 1 <= self.max_calls <= 200:
            raise ValueError("The learning pilot allows 1-200 calls")
        if self.maximum_usd is not None and (
            not math.isfinite(self.maximum_usd) or not 0 < self.maximum_usd <= 100
        ):
            raise ValueError("Use a finite budget above zero and at most US$100")

    def reserve(self, profile: ModelProfile, body: dict) -> dict:
        if self.stopped or self.calls >= self.max_calls:
            raise ValueError("Model call budget exhausted or stopped")
        estimate = estimate_request(profile, body)
        if profile.provider == "openai":
            if self.maximum_usd is None:
                raise ValueError("External calls require an explicit --budget-usd")
            if self.reserved_usd + estimate["reserved_usd"] > self.maximum_usd:
                raise ValueError(
                    "Estimated request reservation would exceed the run's budget"
                )
        self.calls += 1
        self.reserved_usd += estimate["reserved_usd"]
        return estimate

    def public(self) -> dict:
        return {
            "maximum_usd": self.maximum_usd,
            "max_calls": self.max_calls,
            "calls": self.calls,
            "reserved_usd": round(self.reserved_usd, 8),
            "stopped": self.stopped,
            "note": "Conservative application-side reservations, not a provider billing guarantee. Reservations are not reclaimed after failures or discounted usage.",
        }


def request_body(
    profile: ModelProfile, system: str, payload: dict, schema: type[BaseModel]
) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    specification = {
        "name": schema.__name__,
        "strict": True,
        "schema": schema.model_json_schema(),
    }
    if profile.provider == "codex":
        return {
            "model": profile.model,
            "instructions": system,
            "input": payload,
            "output_schema": specification["schema"],
            "execution_policy": execution_policy(),
        }
    if profile.provider == "local":
        return {
            "model": profile.model,
            "messages": messages,
            "temperature": 0,
            "seed": 314159,
            "reasoning_effort": "none",
            "max_tokens": profile.max_output_tokens,
            "response_format": {"type": "json_schema", "json_schema": specification},
        }
    return {
        "model": profile.model,
        "input": messages,
        "store": False,
        "reasoning": {"effort": "low"},
        "service_tier": "default",
        "max_output_tokens": profile.max_output_tokens,
        "text": {"format": {"type": "json_schema", **specification}},
    }


def estimate_request(profile: ModelProfile, body: dict) -> dict:
    # UTF-8 byte length of the ENTIRE request plus framing allowance, instead
    # of an optimistic characters/4 estimate. Bound context well below long-
    # context pricing. Provider tokenization/price changes still require review.
    byte_length = len(json.dumps(body, ensure_ascii=False).encode())
    if byte_length > 64_000:
        raise ValueError("Learning requests are limited to 64 KB")
    input_allowance = byte_length + 2048
    rates = OPENAI_MODELS.get(profile.model, {}) if profile.provider == "openai" else {}
    cost = (
        input_allowance * rates.get("input_per_million", 0) * 2
        + profile.max_output_tokens * rates.get("output_per_million", 0)
    ) / 1_000_000
    result = {
        "input_token_allowance": input_allowance,
        "output_token_limit": profile.max_output_tokens,
        "reserved_usd": round(cost, 8),
        "pricing_checked_at": "2026-10-03",
        "pricing_source": PRICING_SOURCE if rates else None,
    }
    if profile.provider == "codex":
        result.update(
            output_token_limit=None,
            output_token_acceptance_limit=profile.max_output_tokens,
            billing="ChatGPT plan usage; zero API reservation does not mean unlimited/free usage",
        )
    return result


class LearningModel:
    def __init__(
        self,
        settings: Settings,
        profile: ModelProfile,
        budget: RequestBudget,
        *,
        allow_external: bool = False,
        allow_codex: bool = False,
    ):
        self.profile, self.budget = profile, budget
        self.codex = None
        if profile.provider == "codex":
            if not allow_codex:
                raise ValueError(
                    "Codex inference requires --allow-codex; it consumes ChatGPT plan usage"
                )
            if budget.maximum_usd is not None:
                raise ValueError(
                    "Codex uses plan allowance, not --budget-usd; use bounded call counts"
                )
            self.codex = CodexRunner()
            return
        if profile.provider == "openai":
            if not allow_external:
                raise ValueError(
                    "External inference requires --allow-external; no request was sent"
                )
            if budget.maximum_usd is None:
                raise ValueError("External inference requires --budget-usd")
            key = os.getenv("OPENAI_API_KEY", "").strip()
            if not key:
                raise ValueError(
                    "OPENAI_API_KEY is not configured; set it securely in the environment, never in a prompt"
                )
            endpoint = "https://api.openai.com/v1/responses"
        else:
            key = settings.llm_api_key
            endpoint = local_endpoint(profile.base_url) + "/chat/completions"
        self.endpoint = endpoint
        self._key = key
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=10),
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {key}"},
        )

    async def __aenter__(self):
        if self.codex:
            await self.codex.preflight()
        return self

    async def __aexit__(self, *_):
        if not self.codex:
            await self.client.aclose()

    async def generate(
        self, *, system: str, payload: dict, schema: type[BaseModel], artifact: Path
    ):
        if artifact.exists():
            raise ValueError("Model-call artifact already exists")
        body = request_body(self.profile, system, payload, schema)
        reservation = self.budget.reserve(self.profile, body)
        record = {
            "started_at": utc_now().isoformat(),
            "profile": self.profile.public(),
            "request": body,
            "reservation": reservation,
        }
        started = time.monotonic()
        try:
            if self.codex:
                record.update(await self.codex.generate(body))
                if record["codex_cli"]["exit_code"] != 0:
                    raise ValueError(
                        "Codex CLI failed; inspect the saved, redacted diagnostic. No fallback was attempted"
                    )
                text, usage = parse_stream(
                    record["raw_response"], self.profile.max_output_tokens
                )
                record.update(
                    usage=usage,
                    model_identity_source="explicit_cli_model_argument_not_provider_attested",
                )
                result = schema.model_validate_json(text)
                record.update(status="completed", parsed=result.model_dump(mode="json"))
                return result
            response = await self.client.post(self.endpoint, json=body)
            record.update(http_status=response.status_code, raw_response=response.text)
            response.raise_for_status()
            raw = response.json()
            record["served_model"] = raw.get("model", self.profile.model)
            record["usage"] = raw.get("usage")
            if self.profile.provider == "openai":
                usage = raw.get("usage") or {}
                consumed_in, consumed_out = (
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                )
                if not all(
                    type(value) is int and value >= 0
                    for value in (consumed_in, consumed_out)
                ):
                    self.budget.stopped = True
                    raise ValueError("Missing OpenAI usage; stopping external calls")
                if (
                    consumed_in > reservation["input_token_allowance"]
                    or consumed_out > self.profile.max_output_tokens
                ):
                    self.budget.stopped = True
                    raise ValueError(
                        "Usage exceeded its reservation; stop and review billing"
                    )
                rates = OPENAI_MODELS[self.profile.model]
                record["undiscounted_usage_cost_usd"] = (
                    consumed_in * rates["input_per_million"]
                    + consumed_out * rates["output_per_million"]
                ) / 1_000_000
                if raw.get("status") != "completed":
                    raise ValueError("Incomplete or failed model response")
                content = [
                    entry
                    for item in raw.get("output", [])
                    if item.get("type") == "message"
                    for entry in item.get("content", [])
                ]
                if any(entry.get("type") == "refusal" for entry in content):
                    raise ValueError("Reviewer refused the structured extraction")
                texts = [
                    entry["text"]
                    for entry in content
                    if entry.get("type") == "output_text"
                ]
                if len(texts) != 1:
                    raise ValueError("Expected exactly one structured model output")
                text = texts[0]
            else:
                choice = raw["choices"][0]
                if choice.get("finish_reason") != "stop" or choice["message"].get(
                    "refusal"
                ):
                    raise ValueError("Incomplete or refused local model response")
                text = choice["message"]["content"]
            result = schema.model_validate_json(text)
            record.update(status="completed", parsed=result.model_dump(mode="json"))
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            OSError,
            TimeoutError,
        ) as error:
            # Do not include authentication headers even in failed call records.
            message = f"{type(error).__name__}: {error}"
            if self.codex:
                self.budget.stopped = True
            elif self._key:
                message = message.replace(self._key, "[REDACTED]")
            record.update(status="failed", error=message)
            raise ValueError(message) from None
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            record["budget"] = self.budget.public()
            # A misconfigured local service could echo credentials in its error.
            encoded = json.dumps(record, ensure_ascii=False)
            if not self.codex and self._key:
                encoded = encoded.replace(
                    json.dumps(self._key, ensure_ascii=False)[1:-1], "[REDACTED]"
                )
            HistoryStore.write(artifact, json.loads(encoded))
