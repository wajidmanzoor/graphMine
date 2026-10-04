"""Reproducible routing comparison with identical NF4 weights and optional LoRA.

No training, native jobs, model uploads, or serving-configuration changes. Use
the isolated training environment with evaluation-requirements.txt installed.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.metadata
import json
import os
import random
import statistics
import time
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlparse

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import ApplicationIntent, RouteDecision, utc_now
from ..planning import application_capability_errors, resolve_route_scope
from .corpus import digest, load_corpus
from .finetune import read_training_export
from .pipeline import training_route_payload

VERSION = "routing-adapter-comparison-v2"
ARMS = ("base_nf4", "adapter_nf4", "serving_fp8")


def routing_schema():
    """Match production's requirement that every semantic field be emitted."""
    schema = RouteDecision.model_json_schema()

    def visit(value):
        if isinstance(value, dict):
            if "properties" in value:
                value["required"] = list(value["properties"])
            value.pop("default", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


def _pattern(edges):
    names = list(dict.fromkeys(node for edge in edges for node in edge))
    return [[names.index(node) for node in edge] for edge in edges]


def semantic_intent(intent, timestamp_unit=None):
    data = intent.model_dump(mode="json")
    unit = data["time_unit"]
    if unit == "native":
        unit = timestamp_unit
    window = data["time_window"]
    if unit == "milliseconds" and window is not None:
        window /= 1000
        unit = "seconds"
    return {
        "filters": sorted(data["filters"], key=lambda v: json.dumps(v, sort_keys=True)),
        "requires_edge_weights": data["requires_edge_weights"],
        "weight_attribute": data["weight_attribute"],
        "weight_usage": data["weight_usage"],
        "requires_direction": data["requires_direction"],
        "pattern_vertex_count": data["pattern_vertex_count"],
        "pattern_edges": _pattern(data["pattern_edges"]),
        "time_unit": unit,
        "time_window": window,
    }


def score_route(case, raw, catalog):
    """Score behavior and preserved requirements, not explanatory phrasing.

    Report raw refusals separately from server-enforced capability refusals.
    Effective scopes use the real application's inheritance/clear semantics.
    This is a routing metric, not a test of later plan parameters or answers.
    """
    issues = []
    try:
        decision = RouteDecision.model_validate_json(raw)
    except (ValueError, TypeError) as error:
        return {"passed": False, "schema_valid": False, "issues": [str(error)]}
    expected = RouteDecision.model_validate(case["expected"])
    payload = case["payload"]
    previous = payload.get("active_constraints")
    previous = ApplicationIntent.model_validate(previous) if previous else None
    try:
        effective = resolve_route_scope(catalog, decision, previous)
        capability_errors = application_capability_errors(
            effective.intent, effective.operation_id or case["operation_id"]
        )
    except ValueError as error:
        return {"passed": False, "schema_valid": True, "issues": [str(error)]}
    if effective.ambiguity or effective.missing_information:
        behavior = "clarify"
    elif not effective.supported or capability_errors:
        behavior = "unsupported"
    else:
        behavior = "execute"
    if behavior != case["behavior"]:
        issues.append(f"behavior: expected {case['behavior']}, got {behavior}")
    if effective.problem_id != expected.problem_id:
        issues.append(
            f"problem_id: expected {expected.problem_id}, got {effective.problem_id}"
        )
    if (
        case["behavior"] == "execute"
        and effective.operation_id != expected.operation_id
    ):
        issues.append(
            f"operation_id: expected {expected.operation_id}, got {effective.operation_id}"
        )
    unit = payload["graph_context"].get("timestamp_unit")
    actual_intent = semantic_intent(effective.intent, unit)
    expected_intent = semantic_intent(expected.intent, unit)
    for name, value in expected_intent.items():
        if actual_intent[name] != value:
            issues.append(f"{name}: expected {value!r}, got {actual_intent[name]!r}")
    actual_extra = sorted(
        (x.problem_id, x.operation_id) for x in effective.additional_analyses
    )
    expected_extra = sorted(
        (x.problem_id, x.operation_id) for x in expected.additional_analyses
    )
    if actual_extra != expected_extra:
        issues.append(
            "additional_analyses: missing or unexpected supporting computation"
        )
    if effective.inspections:
        issues.append("unnecessary inspection on a complete routing fixture")
    return {
        "passed": not issues,
        "schema_valid": True,
        "issues": issues,
        "behavior": behavior,
        "behavior_correct": behavior == case["behavior"],
        "unsafe_execution": behavior == "execute" and case["behavior"] != "execute",
        "semantic_requirements_correct": actual_intent == expected_intent,
        "raw_supported": decision.supported,
        "raw_route_matches": all(
            getattr(decision, field) == getattr(expected, field)
            for field in ("problem_id", "operation_id", "supported")
        ),
        "capability_errors": capability_errors,
        "decision": decision.model_dump(mode="json"),
    }


def score_generation(case, result, catalog):
    score = score_route(case, result["raw"], catalog)
    if result["finish_reason"] == "length":
        score["issues"].append("generation exhausted token budget")
        score["passed"] = False
    return score


def evaluation_dependencies():
    settings = Settings.from_env()
    agent = Path(__file__).parent.parent
    paths = [
        agent / name
        for name in (
            "catalog.py",
            "models.py",
            "planning.py",
            "graph_context.py",
            "learning/pipeline.py",
            "learning/corpus.py",
            "learning/oracles.py",
        )
    ] + [
        settings.catalog_path,
        settings.manifest_path,
        settings.program_instructions_path,
        agent.parent / "domain_profiles.json",
    ]
    return {str(path.resolve()): HistoryStore.digest(path) for path in paths}


def prepare_suite(run: Path, corpus: Path, output: Path, *, split="test", limit=None):
    if output.exists():
        raise ValueError("Use a new suite directory to preserve evidence")
    if split not in {"validation", "test"}:
        raise ValueError("Evaluate validation or test; never report training accuracy")
    if limit is not None and (split != "validation" or limit < 1):
        raise ValueError("Only a development smoke run may limit the number of cases")
    config = json.loads((run / "run.json").read_text())
    status = json.loads((run / "status.json").read_text())
    if status["phase"] != "completed":
        raise ValueError("A completed adapter is required")
    if config["prompt_sha256"] != digest(ROUTING_SYSTEM_PROMPT):
        raise ValueError("Training and runtime prompts differ")
    if HistoryStore.digest(run / "run.json") != status["config_sha256"]:
        raise ValueError("Run configuration changed")
    if HistoryStore.digest(corpus / "manifest.json") != config["corpus_sha256"]:
        raise ValueError("This is not the recorded training corpus")
    provenance, _ = read_training_export(Path(config["dataset"]))
    training_ids = {x["id"] for x in provenance["rows"] if x["split"] == "train"}
    manifest, graphs = load_corpus(corpus)
    catalog = Catalog(Settings.from_env())
    examples = [x for x in manifest["examples"] if x["split"] == split]
    random.Random(20261003).shuffle(examples)
    if limit:
        examples = examples[:limit]
    if not examples or any(x["id"] in training_ids for x in examples):
        raise ValueError("Empty evaluation or training leakage")
    train_queries = {
        x["task"]["query"] for x in manifest["examples"] if x["split"] == "train"
    }
    cases = [
        {
            "id": x["id"],
            "split": x["split"],
            "family": x["family"],
            "domain": x["domain"],
            "behavior": x["task"]["behavior"],
            "operation_id": x["task"]["operation_id"],
            "source_sha256": digest(x),
            "query_seen_in_training": x["task"]["query"] in train_queries,
            "payload": training_route_payload(catalog, x, graphs[x["graph_id"]]),
            "expected": x["gold_route"],
        }
        for x in examples
    ]
    output.mkdir(parents=True, mode=0o700)
    HistoryStore.write(output / "cases.json", cases)
    (output / "evaluator.py").write_bytes(Path(__file__).read_bytes())
    plan = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "run": str(run.resolve()),
        "run_sha256": HistoryStore.digest(run / "run.json"),
        "adapter_sha256": HistoryStore.digest(
            run / "adapter/adapter_model.safetensors"
        ),
        "corpus": str(corpus.resolve()),
        "corpus_sha256": config["corpus_sha256"],
        "split": split,
        "case_count": len(cases),
        "cases_sha256": HistoryStore.digest(output / "cases.json"),
        "source_sha256": HistoryStore.digest(Path(__file__)),
        "dependencies": evaluation_dependencies(),
        "system_prompt": ROUTING_SYSTEM_PROMPT,
        "response_schema": routing_schema(),
        "max_new_tokens": 2400,
        "max_input_tokens": config["max_sequence_length"],
        "seed": 20261003,
        "decoding": "greedy; thinking disabled; required-field JSON schema; no repair retry",
        "metric": "schema validity + effective routing + exact semantic requirements",
        "limitations": [
            "Graph families are held out, but question templates are shared with training.",
            "Validation cases were used for token-loss evaluation during training.",
            "Routing alone does not prove downstream parameters, numerical answers, or usability.",
            "FP8 uses a different precision and inference engine; only NF4 arms isolate adapter impact.",
        ],
        "queries_seen_in_training": sum(c["query_seen_in_training"] for c in cases),
    }
    HistoryStore.write(output / "plan.json", plan)
    return plan


def read_suite(suite):
    plan = json.loads((suite / "plan.json").read_text())
    if plan["version"] != VERSION or plan["source_sha256"] != HistoryStore.digest(
        Path(__file__)
    ):
        raise ValueError("Evaluation implementation changed; prepare a new suite")
    if plan["cases_sha256"] != HistoryStore.digest(suite / "cases.json"):
        raise ValueError("Evaluation cases changed")
    for path, expected_hash in plan["dependencies"].items():
        if HistoryStore.digest(Path(path)) != expected_hash:
            raise ValueError(f"Evaluation dependency changed: {path}")
    if (
        plan["system_prompt"] != ROUTING_SYSTEM_PROMPT
        or plan["response_schema"] != routing_schema()
    ):
        raise ValueError("Runtime prompt/schema changed")
    cases = json.loads((suite / "cases.json").read_text())
    if len(cases) != plan["case_count"] or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Missing or duplicate evaluation cases")
    for case in cases:
        HistoryStore.identifier(case["id"])
    run = Path(plan["run"])
    if HistoryStore.digest(run / "run.json") != plan["run_sha256"]:
        raise ValueError("Training config changed")
    if (
        HistoryStore.digest(run / "adapter/adapter_model.safetensors")
        != plan["adapter_sha256"]
    ):
        raise ValueError("Adapter changed")
    return plan, cases, json.loads((run / "run.json").read_text())


class LocalRouter:
    def __init__(self, run, config, plan):
        import torch
        import xgrammar as xgr
        from peft import PeftModel, prepare_model_for_kbit_training
        from transformers import (
            AutoConfig,
            AutoTokenizer,
            BitsAndBytesConfig,
            Qwen3_5ForCausalLM,
        )

        if os.environ.get("CUDA_VISIBLE_DEVICES") != config["gpu"]:
            raise ValueError("Isolate the training GPU by its recorded UUID")
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise ValueError("Exactly one isolated GPU is required")
        if torch.cuda.mem_get_info()[0] < 34 * 1024**3:
            raise ValueError("The evaluation GPU must have at least 34 GiB free")
        for name, version in config["packages"].items():
            if importlib.metadata.version(name) != version:
                raise ValueError(f"Pinned training package changed: {name}")
        base = Path(config["base_checkpoint"])
        for name, expected in config["checkpoint_files"].items():
            if HistoryStore.digest(base / name) != expected:
                raise ValueError(f"Base checkpoint changed: {name}")
        model, loading = Qwen3_5ForCausalLM.from_pretrained(
            base,
            config=AutoConfig.from_pretrained(base, local_files_only=True).text_config,
            local_files_only=True,
            dtype=torch.bfloat16,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            ),
            device_map={"": 0},
            attn_implementation="sdpa",
            output_loading_info=True,
        )
        if any(
            loading.get(k)
            for k in (
                "missing_keys",
                "unexpected_keys",
                "mismatched_keys",
                "error_msgs",
            )
        ):
            raise ValueError(f"Incomplete model loading: {loading}")
        # Match the dtype conversions used by training, with gradients disabled.
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
        model.get_input_embeddings().to(torch.bfloat16)
        model.get_output_embeddings().to(torch.bfloat16)
        self.model = PeftModel.from_pretrained(
            model, run / "adapter", is_trainable=False
        )
        self.model.eval()
        self.model.config.use_cache = True
        self.tokenizer = AutoTokenizer.from_pretrained(
            base, local_files_only=True, padding_side="left"
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        info = xgr.TokenizerInfo.from_huggingface(
            self.tokenizer, vocab_size=self.model.config.vocab_size
        )
        self.grammar = xgr.GrammarCompiler(info).compile_json_schema(
            plan["response_schema"]
        )
        self.plan = plan
        self.metadata = {
            "gpu": config["gpu"],
            "base_checkpoint_files_verified": True,
            "packages": {
                name: importlib.metadata.version(name)
                for name in (*config["packages"], "xgrammar", "apache-tvm-ffi")
            },
            "quantization": "NF4 double quantization, BF16 computation, same frozen weights for both arms",
            "loading": {
                k: sorted(v) if isinstance(v, set) else v for k, v in loading.items()
            },
        }

    def generate(self, cases, arm):
        import torch
        from transformers import GenerationConfig
        from xgrammar.contrib.hf import LogitsProcessor

        messages = [
            [
                {"role": "system", "content": self.plan["system_prompt"]},
                {
                    "role": "user",
                    "content": json.dumps(case["payload"], ensure_ascii=False),
                },
            ]
            for case in cases
        ]
        prompts = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.tokenizer(
            prompts, return_tensors="pt", padding=True, add_special_tokens=False
        )
        if inputs.input_ids.shape[1] > self.plan["max_input_tokens"]:
            raise ValueError(
                "Evaluation input exceeds the budget; no silent truncation"
            )
        inputs = inputs.to(self.model.device)
        options = GenerationConfig(
            max_new_tokens=self.plan["max_new_tokens"],
            do_sample=False,
            use_cache=True,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id,
        )
        context = self.model.disable_adapter() if arm == "base_nf4" else nullcontext()
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
        seconds = time.monotonic() - started
        results = []
        for ids, mask in zip(
            output[:, inputs.input_ids.shape[1] :], inputs.attention_mask, strict=True
        ):
            values = ids.tolist()
            stopped = self.tokenizer.eos_token_id in values
            if stopped:
                values = values[: values.index(self.tokenizer.eos_token_id)]
            results.append(
                {
                    "raw": self.tokenizer.decode(values, skip_special_tokens=True),
                    "input_tokens": int(mask.sum()),
                    "output_tokens": len(values),
                    "finish_reason": "stop" if stopped else "length",
                    "batch_seconds": seconds,
                    "batch_size": len(cases),
                    "amortized_seconds": seconds / len(cases),
                }
            )
        return results


def serving_generate(case, plan, settings):
    import httpx

    if urlparse(settings.llm_base_url).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "This local comparison accepts only a loopback serving endpoint"
        )
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": plan["system_prompt"]},
            {
                "role": "user",
                "content": json.dumps(case["payload"], ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "top_p": 1,
        "top_k": 0,
        "seed": plan["seed"],
        "reasoning_effort": "none",
        "max_completion_tokens": plan["max_new_tokens"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "RouteDecision",
                "strict": True,
                "schema": plan["response_schema"],
            },
        },
    }
    started = time.monotonic()
    response = httpx.post(
        settings.llm_base_url + "/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        timeout=240,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "raw": data["choices"][0]["message"]["content"],
        "finish_reason": data["choices"][0]["finish_reason"],
        "usage": data.get("usage"),
        "response_model": data.get("model"),
        "seconds": time.monotonic() - started,
    }


def summarize(rows, expected_cases, arms):
    by_arm = {}
    for arm in arms:
        selected = [r for r in rows if r["arm"] == arm]
        groups = {}
        for field in ("behavior", "family", "operation_id"):
            grouped = defaultdict(list)
            for row in selected:
                grouped[str(row[field])].append(row)
            groups[field] = {
                k: {"passed": sum(x["score"]["passed"] for x in v), "total": len(v)}
                for k, v in sorted(grouped.items())
            }
        times = [r.get("amortized_seconds", r.get("seconds", 0)) for r in selected]
        by_arm[arm] = {
            "passed": sum(r["score"]["passed"] for r in selected),
            "total": len(selected),
            "schema_valid": sum(r["score"]["schema_valid"] for r in selected),
            "raw_route_matches": sum(
                r["score"].get("raw_route_matches", False) for r in selected
            ),
            "behavior_correct": sum(
                r["score"].get("behavior_correct", False) for r in selected
            ),
            "unsafe_execution": sum(
                r["score"].get("unsafe_execution", False) for r in selected
            ),
            "semantic_requirements_correct": sum(
                r["score"].get("semantic_requirements_correct", False) for r in selected
            ),
            "truncated": sum(r["finish_reason"] == "length" for r in selected),
            "median_amortized_seconds": statistics.median(times) if times else None,
            "by": groups,
        }
    pairs = {arm: {r["id"]: r for r in rows if r["arm"] == arm} for arm in arms}
    comparison = Counter()
    regressions, improvements = [], []
    if "base_nf4" in pairs and "adapter_nf4" in pairs:
        for case_id in sorted(pairs["base_nf4"].keys() & pairs["adapter_nf4"].keys()):
            base = pairs["base_nf4"][case_id]["score"]["passed"]
            adapter = pairs["adapter_nf4"][case_id]["score"]["passed"]
            key = (
                "both_pass"
                if base and adapter
                else "both_fail"
                if not (base or adapter)
                else "improved"
                if adapter
                else "regressed"
            )
            comparison[key] += 1
            if key == "regressed":
                regressions.append(case_id)
            elif key == "improved":
                improvements.append(case_id)
    return {
        "by_arm": by_arm,
        "paired_nf4": dict(comparison),
        "regressions": regressions,
        "improvements": improvements,
        "expected_cases_per_arm": expected_cases,
        "complete": all(len(pairs[arm]) == expected_cases for arm in arms),
        "latency_caution": "Local values are amortized batch time, not end-user latency; first batch includes warm-up. FP8 has another engine/precision.",
    }


def compare(suite, output, *, arms=ARMS[:2], batch_size=2, resume=False):
    if not arms or len(set(arms)) != len(arms) or set(arms) - set(ARMS):
        raise ValueError("Choose distinct known evaluation arms")
    if batch_size < 1 or batch_size > 4:
        raise ValueError("Batch size must be 1 through 4")
    if output.exists() and not resume:
        raise ValueError(
            "Output exists; use explicit --resume after confirming its process stopped"
        )
    if resume and not output.exists():
        raise ValueError("Cannot resume a missing comparison")
    output.mkdir(parents=True, exist_ok=resume, mode=0o700)
    with (output / ".eval.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, cases, config = read_suite(suite)
        settings, catalog = Settings.from_env(), Catalog(Settings.from_env())
        contract = {
            "plan_sha256": HistoryStore.digest(suite / "plan.json"),
            "arms": list(arms),
            "batch_size": batch_size,
        }
        if resume:
            if json.loads((output / "contract.json").read_text()) != contract:
                raise ValueError("Resume conditions differ")
        else:
            HistoryStore.write(output / "contract.json", contract)
        status = {
            "phase": "preparing",
            "pid": os.getpid(),
            "started_at": utc_now().isoformat(),
            **contract,
        }
        rows = []
        for arm in arms:
            for case in cases:
                path = output / "calls" / f"{case['id']}--{arm}.json"
                if path.exists():
                    row = json.loads(path.read_text())
                    if (
                        row["case_sha256"] != digest(case)
                        or row["arm"] != arm
                        or row["id"] != case["id"]
                    ):
                        raise ValueError("Changed or mismatched saved inference")
                    row["score"] = score_generation(case, row, catalog)
                    rows.append(row)

        def save(**changes):
            status.update(
                changes,
                updated_at=utc_now().isoformat(),
                completed_calls=len(rows),
                planned_calls=len(cases) * len(arms),
            )
            HistoryStore.write(output / "status.json", status)

        save()
        try:
            done = {(r["id"], r["arm"]) for r in rows}
            need_local = any(
                (c["id"], arm) not in done
                for c in cases
                for arm in arms
                if arm != "serving_fp8"
            )
            router = None
            if need_local:
                save(phase="loading_model")
                router = LocalRouter(Path(plan["run"]), config, plan)
                HistoryStore.write(output / "environment.json", router.metadata)
            for start in range(0, len(cases), batch_size):
                batch = cases[start : start + batch_size]
                # Alternate which NF4 arm goes first; no cache crosses generate calls.
                order = (
                    list(arms)
                    if (start // batch_size) % 2 == 0
                    else list(reversed(arms))
                )
                for arm in order:
                    pending = [c for c in batch if (c["id"], arm) not in done]
                    if not pending:
                        continue
                    save(
                        phase="generating",
                        arm=arm,
                        current_cases=[c["id"] for c in pending],
                    )
                    generated = (
                        [serving_generate(c, plan, settings) for c in pending]
                        if arm == "serving_fp8"
                        else router.generate(pending, arm)
                    )
                    for case, result in zip(pending, generated, strict=True):
                        score = score_generation(case, result, catalog)
                        row = {
                            k: case[k]
                            for k in ("id", "family", "behavior", "operation_id")
                        }
                        row.update(
                            arm=arm, case_sha256=digest(case), **result, score=score
                        )
                        HistoryStore.write(
                            output / "calls" / f"{case['id']}--{arm}.json", row
                        )
                        rows.append(row)
                        done.add((case["id"], arm))
                        print(
                            json.dumps(
                                {
                                    "id": case["id"],
                                    "arm": arm,
                                    "passed": score["passed"],
                                    "issues": score["issues"],
                                }
                            ),
                            flush=True,
                        )
                    save()
                    HistoryStore.write(
                        output / "summary.json", summarize(rows, len(cases), arms)
                    )
            summary = summarize(rows, len(cases), arms)
            if not summary["complete"]:
                raise RuntimeError("Incomplete comparison")
            save(phase="completed")
            return summary
        except BaseException as error:
            save(
                phase="interrupted"
                if isinstance(error, KeyboardInterrupt)
                else "failed",
                error=f"{type(error).__name__}: {error}",
            )
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("run", type=Path)
    prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--split", choices=("validation", "test"), default="test")
    prep.add_argument("--limit", type=int)
    evaluate = commands.add_parser("compare")
    evaluate.add_argument("suite", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS[:2]))
    evaluate.add_argument("--batch-size", type=int, default=2)
    evaluate.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_suite(
            args.run, args.corpus, args.output, split=args.split, limit=args.limit
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "version",
                        "split",
                        "case_count",
                        "queries_seen_in_training",
                    )
                }
            )
        )
    else:
        print(
            json.dumps(
                compare(
                    args.suite,
                    args.output,
                    arms=args.arms,
                    batch_size=args.batch_size,
                    resume=args.resume,
                )
            )
        )


if __name__ == "__main__":
    main()
