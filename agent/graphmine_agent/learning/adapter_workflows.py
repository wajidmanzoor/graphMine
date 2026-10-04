"""Evaluate local routing adapters through an isolated, complete GraphMine app.

Only RouteDecision uses the optional adapter. Planning, turn resolution and
answer writing use the unchanged local serving model. Existing workflow/native
oracles are reused. Real-data development mode preserves its source holdout;
the explicit final-holdout mode consumes it for the frozen candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import threading
import time
from contextlib import asynccontextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx

from ..api import create_app
from ..config import Settings
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT, LLMError
from ..models import RouteDecision, new_id, utc_now
from . import adapter_holdout, realworld_eval, workflows
from .adapter_eval import ARMS, LocalRouter, read_suite
from .teacher import local_endpoint


def route_messages(payload, conversation):
    """Use the same history window/serialization as OpenAICompatibleModel."""
    messages = [{"role": "system", "content": ROUTING_SYSTEM_PROMPT}]
    for item in (conversation or [])[-12:]:
        if item.get("role") in {"user", "assistant"}:
            messages.append(
                {
                    "role": item["role"],
                    "content": json.dumps(item.get("payload", {}), ensure_ascii=False),
                }
            )
    messages.append(
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
    )
    return messages


class ConversationRouter(LocalRouter):
    def __init__(self, run, config, plan, *, max_input_tokens=16384):
        super().__init__(run, config, plan)
        if (
            not plan["max_input_tokens"]
            <= max_input_tokens
            <= self.model.config.max_position_embeddings
        ):
            raise ValueError(
                "Application input budget is outside the model's context range"
            )
        self.max_input_tokens = max_input_tokens
        self._lock = threading.Lock()

    def route(self, payload, conversation, arm):
        import torch
        from transformers import GenerationConfig
        from xgrammar.contrib.hf import LogitsProcessor

        if arm not in {"base_nf4", "adapter_nf4"}:
            raise ValueError("The local router supports matched NF4 arms only")
        messages = route_messages(payload, conversation)
        with self._lock:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = self.tokenizer(
                prompt, return_tensors="pt", add_special_tokens=False
            )
            if inputs.input_ids.shape[1] > self.max_input_tokens:
                raise LLMError(
                    "Full routing history exceeds the recorded input budget; no silent truncation"
                )
            inputs = inputs.to(self.model.device)
            options = GenerationConfig(
                max_new_tokens=self.plan["max_new_tokens"],
                do_sample=False,
                use_cache=True,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.pad_token_id,
            )
            context = (
                self.model.disable_adapter() if arm == "base_nf4" else nullcontext()
            )
            torch.cuda.synchronize()
            started = time.monotonic()
            with context, torch.inference_mode():
                output = self.model.generate(
                    **inputs,
                    generation_config=options,
                    logits_processor=[LogitsProcessor(self.grammar)],
                    logits_to_keep=1,
                )
            torch.cuda.synchronize()
            values = output[0, inputs.input_ids.shape[1] :].tolist()
            stopped = self.tokenizer.eos_token_id in values
            if stopped:
                values = values[: values.index(self.tokenizer.eos_token_id)]
            return {
                "raw": self.tokenizer.decode(values, skip_special_tokens=True),
                "finish_reason": "stop" if stopped else "length",
                "seconds": time.monotonic() - started,
                "input_tokens": inputs.input_ids.shape[1],
                "output_tokens": len(values),
            }


class StageModel:
    """Dispatch routing locally, preserving every other stage and its history."""

    def __init__(self, delegate, router, arm, history):
        if arm not in {"base_nf4", "adapter_nf4"}:
            raise ValueError("Expected a local comparison arm")
        self.delegate, self.router, self.arm, self.history = (
            delegate,
            router,
            arm,
            history,
        )

    async def available(self):
        return await self.delegate.available()

    async def close(self):
        await self.delegate.close()

    async def generate(self, **kwargs):
        if kwargs["schema"] is not RouteDecision:
            return await self.delegate.generate(**kwargs)
        payload, conversation = kwargs["user_payload"], kwargs.get("conversation")
        call_id = new_id("llm")
        self.history.current(
            "llm.request",
            {
                "call_id": call_id,
                "mode": kwargs["mode"].value,
                "request": {
                    "model": self.arm,
                    "messages": route_messages(payload, conversation),
                    "decoding": self.router.plan["decoding"],
                    "response_schema": self.router.plan["response_schema"],
                },
            },
        )
        try:
            result = await asyncio.to_thread(
                self.router.route, payload, conversation, self.arm
            )
            self.history.current("llm.response", {"call_id": call_id, **result})
            if result["finish_reason"] != "stop":
                raise LLMError("Local routing generation exhausted its token budget")
            return RouteDecision.model_validate_json(result["raw"])
        except (ValueError, RuntimeError) as error:
            raise LLMError(f"Local routing failed: {error}") from error


def embedded_client(router, arm):
    @asynccontextmanager
    async def client_context(settings, *, data_dir, base_url=None):
        if base_url is not None or data_dir.resolve() == settings.data_root.resolve():
            raise ValueError(
                "Adapter workflow evaluation requires a new isolated local store"
            )
        data_dir.mkdir(parents=True, mode=0o700)
        with (data_dir / ".adapter-app.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            configured = replace(
                settings, data_root=data_dir.resolve(), history_directory=None
            )
            app = create_app(configured)
            headers = (
                {"Authorization": f"Bearer {settings.api_token}"}
                if settings.api_token
                else {}
            )
            async with app.router.lifespan_context(app):
                runtime = app.state.runtime
                if arm != "serving_fp8":
                    runtime.agent.model = StageModel(
                        runtime.agent.model,
                        router,
                        arm,
                        runtime.database.history,
                    )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://graphmine.local",
                    headers=headers,
                    timeout=httpx.Timeout(600, connect=10),
                ) as client:
                    yield client, configured.history_root

    return client_context


async def evaluate(
    suite,
    output,
    *,
    arms=ARMS,
    repeats=1,
    case_ids=None,
    real_corpus=None,
    questions=None,
    max_input_tokens=16384,
    final_holdout=False,
    reference_native_gpu=None,
):
    if output.exists():
        raise ValueError("Use a new complete-application evaluation directory")
    if not arms or len(set(arms)) != len(arms) or set(arms) - set(ARMS):
        raise ValueError("Choose distinct known arms")
    if reference_native_gpu and list(arms) != ["serving_fp8"]:
        raise ValueError(
            "A different native GPU is only allowed for a separate serving reference"
        )
    if reference_native_gpu:
        try:
            canonical_gpu = f"GPU-{UUID(reference_native_gpu.removeprefix('GPU-'))}"
        except ValueError as error:
            raise ValueError(
                "Reference native GPU must be a canonical GPU UUID"
            ) from error
        if canonical_gpu != reference_native_gpu:
            raise ValueError("Reference native GPU must be a canonical GPU UUID")
    if not 1 <= repeats <= 3:
        raise ValueError("Choose one to three complete workflow trials")
    if questions and not real_corpus:
        raise ValueError("Reviewed real-world questions need their source corpus")
    if final_holdout and (not real_corpus or questions or case_ids):
        raise ValueError(
            "Final holdout requires the real corpus and all original reserved cases"
        )
    if real_corpus and case_ids:
        raise ValueError(
            "Case filtering is only supported for synthetic workflow smoke tests"
        )
    plan, _, config = read_suite(suite)
    settings = Settings.from_env()
    local_endpoint(settings.llm_base_url)
    settings = replace(
        settings,
        graph_gpu_uuid=reference_native_gpu or config["gpu"],
        history_directory=None,
    )
    output.mkdir(parents=True, mode=0o700)
    status = {
        "phase": "loading_model",
        "pid": os.getpid(),
        "started_at": utc_now().isoformat(),
        "completed_arms": [],
    }

    def save(**changes):
        status.update(changes, updated_at=utc_now().isoformat())
        HistoryStore.write(output / "status.json", status)

    save()
    try:
        router = (
            ConversationRouter(
                Path(plan["run"]), config, plan, max_input_tokens=max_input_tokens
            )
            if any(arm != "serving_fp8" for arm in arms)
            else None
        )
        protocol = {
            "suite_plan_sha256": HistoryStore.digest(suite / "plan.json"),
            "adapter_sha256": plan["adapter_sha256"],
            "source_sha256": HistoryStore.digest(Path(__file__)),
            "arms": list(arms),
            "repeats": repeats,
            "route_context_budget": max_input_tokens,
            "route_completion_budget": plan["max_new_tokens"],
            "routing_only": True,
            "other_stages_model": settings.llm_model,
            "llm_plan_reasoning_effort": settings.llm_plan_reasoning_effort,
            "llm_analyst_reasoning_effort": settings.llm_analyst_reasoning_effort,
            "native_gpu": settings.graph_gpu_uuid,
            "local_route_environment": router.metadata if router else None,
            "scope": (
                "Final reserved-source application comparison."
                if final_holdout
                else "Complete application development workflows."
            )
            + " GPU placement is recorded; no concurrency/throughput or novice-usability claim.",
            "real_corpus": str(real_corpus) if real_corpus else None,
            "questions": str(questions) if questions else None,
            "final_holdout": final_holdout,
            "deployment_changed": False,
        }
        HistoryStore.write(output / "protocol.json", protocol)
        reports = {}
        for arm in arms:
            save(phase="evaluating", arm=arm)
            options = {
                "settings": settings,
                "output": output / f"{arm}.json",
                "data_dir": output / f"{arm}-runtime",
                "repeats": repeats,
            }
            # This patch exists only inside this isolated evaluation process. It
            # preserves the checked workflow/oracle loops without changing the API.
            module = (
                adapter_holdout
                if final_holdout
                else realworld_eval
                if real_corpus
                else workflows
            )
            with patch.object(module, "agent_client", embedded_client(router, arm)):
                if final_holdout:
                    result = await adapter_holdout.evaluate_holdout(
                        **options, corpus=real_corpus
                    )
                elif real_corpus:
                    result = await realworld_eval.evaluate_realworld(
                        **options, corpus=real_corpus, questions=questions
                    )
                else:
                    result = await workflows.evaluate_workflows(
                        **options, corpus=Path(plan["corpus"]), case_ids=case_ids
                    )
            reports[arm] = {
                k: result[k]
                for k in ("passed", "total", "workflows_passed", "finished_at")
            }
            reports[arm]["report_sha256"] = HistoryStore.digest(output / f"{arm}.json")
            HistoryStore.write(output / "summary.json", reports)
            status["completed_arms"].append(arm)
            save()
        save(phase="completed")
        return reports
    except BaseException as error:
        save(phase="failed", error=f"{type(error).__name__}: {error}")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--real-corpus", type=Path)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--max-input-tokens", type=int, default=16384)
    parser.add_argument(
        "--final-holdout",
        action="store_true",
        help="Consume every reserved source case for the frozen final candidate",
    )
    parser.add_argument(
        "--reference-native-gpu",
        help="Place small native jobs on this GPU for a serving_fp8-only reference",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                evaluate(
                    args.suite,
                    args.output,
                    arms=args.arms,
                    repeats=args.repeats,
                    case_ids=set(args.case_id) if args.case_id else None,
                    real_corpus=args.real_corpus,
                    questions=args.questions,
                    max_input_tokens=args.max_input_tokens,
                    final_holdout=args.final_holdout,
                    reference_native_gpu=args.reference_native_gpu,
                )
            )
        )
    )


if __name__ == "__main__":
    main()
