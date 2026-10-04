"""Local, opt-in QLoRA routing pilot. No provider uploads or automatic deployment.

Run this module with the isolated training Python, not the serving environment.
The first pilot uses oracle-gated synthetic supervision, not teacher reasoning.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.metadata
import json
import math
import os
import re
import signal
from pathlib import Path

from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import RouteDecision, utc_now
from .corpus import FAMILIES, digest

VERSION = "local-routing-qlora-v1"


def read_training_export(directory: Path) -> tuple[dict, dict]:
    provenance = json.loads((directory / "provenance.json").read_text())
    if provenance.get("quarantine"):
        raise ValueError("Resolve quarantined examples before this bounded pilot")
    rows = {}
    seen = set()
    for split in ("train", "validation"):
        path = directory / f"{split}.jsonl"
        if HistoryStore.digest(path) != provenance["files"][split]:
            raise ValueError(f"Changed {split} export")
        rows[split] = [json.loads(line) for line in path.read_text().splitlines()]
        sources = [p for p in provenance["rows"] if p["split"] == split]
        if not rows[split] or len(rows[split]) != len(sources):
            raise ValueError("Missing or extra provenance rows")
        for row, source in zip(rows[split], sources, strict=True):
            if (
                source["stage"] != "RouteDecision"
                or source["family"] not in FAMILIES[split]
                or source["row_sha256"] != digest(row)
                or source["id"] in seen
            ):
                raise ValueError("Invalid row provenance or split leakage")
            seen.add(source["id"])
            messages = row["messages"]
            if [m["role"] for m in messages] != ["system", "user", "assistant"]:
                raise ValueError(
                    "Only explicit three-message routing examples accepted"
                )
            if messages[0]["content"] != ROUTING_SYSTEM_PROMPT:
                raise ValueError("Training prompt differs from the current runtime")
            RouteDecision.model_validate_json(messages[2]["content"])
            payload = json.loads(messages[1]["content"])
            if (
                not {"graph_metadata", "application_preprocessing", "pending_request"}
                <= payload.keys()
            ):
                raise ValueError("Training input does not match the runtime contract")
    if any(p["split"] not in rows for p in provenance["rows"]):
        raise ValueError("Held-out rows must never enter training")
    return provenance, rows


def assistant_only_tokens(tokenizer, messages, max_length):
    """Mask the whole prompt, including Qwen's empty non-thinking prefix."""
    options = {"tokenize": True, "enable_thinking": False, "return_dict": False}
    prompt = tokenizer.apply_chat_template(
        messages[:-1], add_generation_prompt=True, **options
    )
    full = tokenizer.apply_chat_template(
        messages, add_generation_prompt=False, **options
    )
    if full[: len(prompt)] != prompt or len(full) <= len(prompt):
        raise ValueError(
            "Chat-template prefix mismatch; refusing incorrect loss masking"
        )
    if len(full) > max_length:
        raise ValueError(
            f"Example has {len(full)} tokens, exceeding {max_length}; no silent truncation"
        )
    return {
        "input_ids": full,
        "attention_mask": [1] * len(full),
        "labels": [-100] * len(prompt) + full[len(prompt) :],
    }


def prepare(
    dataset: Path, checkpoint: Path, destination: Path, gpu: str, *, max_length=8192
):
    from transformers import AutoTokenizer

    if destination.exists():
        raise ValueError("Choose a new run directory; prior evidence is immutable")
    if not re.fullmatch(r"GPU-[0-9a-f-]{36}", gpu):
        raise ValueError("Select a GPU explicitly by its nvidia-smi UUID")
    provenance, rows = read_training_export(dataset)
    if len(rows["train"]) < 32 or len(rows["validation"]) < 8:
        raise ValueError(
            "At least 32 training and 8 validation examples required for this pilot"
        )
    checkpoint = checkpoint.resolve()
    config = json.loads((checkpoint / "config.json").read_text())
    if config.get("model_type") != "qwen3_5" or "quantization_config" in config:
        raise ValueError(
            "Use the standard unquantized Qwen checkpoint, not the serving FP8 weights"
        )
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
    encoded = {
        split: [
            assistant_only_tokens(tokenizer, row["messages"], max_length)
            for row in split_rows
        ]
        for split, split_rows in rows.items()
    }
    destination.mkdir(parents=True, mode=0o700)
    prepared = {}
    for split, items in encoded.items():
        path = destination / f"{split}.tokens.json"
        HistoryStore.write(path, items)
        lengths = [len(item["input_ids"]) for item in items]
        prepared[split] = {
            "path": path.name,
            "sha256": HistoryStore.digest(path),
            "rows": len(items),
            "min_tokens": min(lengths),
            "max_tokens": max(lengths),
            "supervised_tokens": sum(
                sum(x != -100 for x in item["labels"]) for item in items
            ),
        }
    print("Hashing the local base checkpoint for reproducibility...", flush=True)
    model_files = {
        p.name: HistoryStore.digest(p)
        for p in sorted(checkpoint.iterdir())
        if p.suffix in {".json", ".safetensors", ".jinja", ".model"}
    }
    run = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "training_started": False,
        "base_checkpoint": str(checkpoint),
        "base_model": "Qwen/Qwen3.8-27B",
        "base_revision": checkpoint.name,
        "checkpoint_files": model_files,
        "gpu": gpu,
        "dataset": str(dataset.resolve()),
        "dataset_provenance_sha256": HistoryStore.digest(dataset / "provenance.json"),
        "corpus_sha256": provenance["corpus_sha256"],
        "audit_sha256": provenance["audit_sha256"],
        "data": prepared,
        "max_sequence_length": max_length,
        "source_sha256": HistoryStore.digest(Path(__file__)),
        "prompt_sha256": digest(ROUTING_SYSTEM_PROMPT),
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "bitsandbytes",
                "accelerate",
                "datasets",
                "flash-linear-attention",
            )
        },
        "hyperparameters": {
            "epochs": 1,
            "batch_size": 1,
            "gradient_accumulation_steps": 4,
            "learning_rate": 0.0001,
            "lora_rank": 16,
            "lora_alpha": 32,
            "lora_dropout": 0.05,
            "seed": 271828,
        },
        "scope": "First local intent-routing adapter pilot from oracle-gated synthetic templates. Not Codex reasoning distillation, not final answer training. All real-world sources and synthetic test families excluded; no deployment.",
    }
    HistoryStore.write(destination / "run.json", run)
    return run


def train(directory: Path, *, execute=False, resume: Path | None = None):
    if not execute:
        return _train(directory, execute=False, resume=resume)
    # Keep the advisory lock until the process exits or training returns. This
    # also protects explicit resumes from overlapping with a still-running job.
    with (directory / ".trainer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another trainer already holds this run") from error
        return _train(directory, execute=True, resume=resume)


def _train(directory: Path, *, execute=False, resume: Path | None = None):
    directory = directory.resolve()
    config = json.loads((directory / "run.json").read_text())
    if config["version"] != VERSION or config["source_sha256"] != HistoryStore.digest(
        Path(__file__)
    ):
        raise ValueError("Training implementation changed; prepare a new run")
    if config["prompt_sha256"] != digest(ROUTING_SYSTEM_PROMPT):
        raise ValueError("Runtime prompt changed; re-export and prepare")
    dataset = Path(config["dataset"])
    if config["dataset_provenance_sha256"] != HistoryStore.digest(
        dataset / "provenance.json"
    ):
        raise ValueError("Changed dataset provenance")
    read_training_export(dataset)
    tokenized = {}
    for split, info in config["data"].items():
        path = directory / info["path"]
        if path.parent != directory or HistoryStore.digest(path) != info["sha256"]:
            raise ValueError("Changed or unsafe tokenized input")
        tokenized[split] = json.loads(path.read_text())
    if not execute:
        return {
            "training_started": False,
            "config": config,
            "next": "Pass --execute using the isolated training Python",
        }
    if os.environ.get("CUDA_VISIBLE_DEVICES") != config["gpu"]:
        raise ValueError(
            "CUDA_VISIBLE_DEVICES must match the prepared GPU UUID exactly"
        )
    output = directory / "checkpoints"
    if resume:
        resume = resume.resolve()
        if resume.parent != output or not (resume / "trainer_state.json").is_file():
            raise ValueError("Resume only a saved Trainer checkpoint inside this run")
    elif output.exists():
        raise ValueError(
            "Output already exists; explicitly resume a checkpoint or prepare a new run"
        )
    for name, expected in config["packages"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError(f"Training dependency changed: {name}")
    base = Path(config["base_checkpoint"])
    for name, expected in config["checkpoint_files"].items():
        if HistoryStore.digest(base / name) != expected:
            raise ValueError(f"Base checkpoint changed: {name}")

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoConfig,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Qwen3_5ForCausalLM,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("Exactly one explicitly isolated CUDA GPU is required")
    free, total = torch.cuda.mem_get_info()
    if free < 34 * 1024**3:
        raise ValueError(
            "At least 34 GiB free on the selected GPU required; leave the serving GPU alone"
        )
    h = config["hyperparameters"]
    set_seed(h["seed"])
    status = {
        "phase": "loading_model",
        "training_started": False,
        "global_step": 0,
        "pid": os.getpid(),
        "gpu": config["gpu"],
        "gpu_name": torch.cuda.get_device_name(),
        "gpu_total_bytes": total,
        "started_at": utc_now().isoformat(),
        "config_sha256": HistoryStore.digest(directory / "run.json"),
        "deployed": False,
    }

    def save_status(**changes):
        status.update(changes)
        status["updated_at"] = utc_now().isoformat()
        HistoryStore.write(directory / "status.json", status)

    save_status()
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        save_status(stop_requested=True)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    class Progress(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            save_status(
                phase="training",
                training_started=state.global_step > 0,
                global_step=state.global_step,
                planned_steps=state.max_steps,
                epoch=state.epoch,
                peak_gpu_bytes=torch.cuda.max_memory_allocated(),
            )
            if state.global_step in {1, 2} or stop_requested:
                control.should_save = True
            if stop_requested:
                control.should_training_stop = True

        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                if any(
                    isinstance(value, (float, int)) and not math.isfinite(value)
                    for value in logs.values()
                ):
                    raise RuntimeError(
                        "Non-finite training metric; stopping without deployment"
                    )
                save_status(last_metrics=logs)
                with (directory / "metrics.jsonl").open("a") as stream:
                    stream.write(json.dumps({"step": state.global_step, **logs}) + "\n")

        def on_save(self, args, state, control, **kwargs):
            save_status(
                latest_checkpoint=str(output / f"checkpoint-{state.global_step}")
            )

    class AssistantLossTrainer(Trainer):
        def compute_loss(
            self, model, inputs, return_outputs=False, num_items_in_batch=None
        ):
            labels = inputs.pop("labels")
            first = int((labels != -100).nonzero()[:, 1].min())
            start = max(0, first - 1)
            # The large vocabulary need not produce logits for prompt-only tokens.
            outputs = model(
                **inputs, logits_to_keep=labels.shape[1] - start, use_cache=False
            )
            targets = labels[:, start + 1 :].contiguous()
            logits = outputs.logits[:, :-1].contiguous().float()
            loss = torch.nn.functional.cross_entropy(
                logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100
            )
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite assistant loss")
            return (loss, outputs) if return_outputs else loss

    try:
        text_config = AutoConfig.from_pretrained(
            base, local_files_only=True
        ).text_config
        text_config.use_cache = False
        model, loading = Qwen3_5ForCausalLM.from_pretrained(
            base,
            config=text_config,
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
            loading.get(key)
            for key in (
                "missing_keys",
                "unexpected_keys",
                "mismatched_keys",
                "error_msgs",
            )
        ):
            raise RuntimeError(f"Incomplete base checkpoint load: {loading}")
        HistoryStore.write(
            directory / "loading.json",
            {
                key: sorted(value) if isinstance(value, set) else value
                for key, value in loading.items()
            },
        )
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
        # These are frozen; keep the huge vocabulary matrices at BF16, not FP32.
        model.get_input_embeddings().to(torch.bfloat16)
        model.get_output_embeddings().to(torch.bfloat16)
        model = get_peft_model(
            model,
            LoraConfig(
                r=h["lora_rank"],
                lora_alpha=h["lora_alpha"],
                lora_dropout=h["lora_dropout"],
                target_modules="all-linear",
                bias="none",
                task_type="CAUSAL_LM",
            ),
        )
        trainable, all_parameters = model.get_nb_trainable_parameters()
        if trainable <= 0 or trainable >= all_parameters:
            raise RuntimeError("Invalid adapter parameter selection")
        save_status(
            phase="model_loaded",
            trainable_parameters=trainable,
            all_parameters=all_parameters,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            base, local_files_only=True, padding_side="right"
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        args = TrainingArguments(
            output_dir=str(output),
            per_device_train_batch_size=1,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=h["gradient_accumulation_steps"],
            num_train_epochs=h["epochs"],
            learning_rate=h["learning_rate"],
            warmup_steps=0.1,
            lr_scheduler_type="cosine",
            bf16=True,
            optim="adamw_torch",
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            max_grad_norm=1.0,
            logging_steps=1,
            save_strategy="steps",
            save_steps=12,
            eval_strategy="epoch",
            prediction_loss_only=True,
            report_to=[],
            push_to_hub=False,
            seed=h["seed"],
            data_seed=h["seed"],
            remove_unused_columns=False,
            dataloader_num_workers=0,
        )
        trainer = AssistantLossTrainer(
            model=model,
            args=args,
            train_dataset=Dataset.from_list(tokenized["train"]),
            eval_dataset=Dataset.from_list(tokenized["validation"]),
            processing_class=tokenizer,
            data_collator=DataCollatorForSeq2Seq(
                tokenizer, padding=True, label_pad_token_id=-100
            ),
            callbacks=[Progress()],
        )
        trainer.model_accepts_loss_kwargs = False
        metrics = trainer.train(resume_from_checkpoint=str(resume) if resume else None)
        if stop_requested:
            save_status(phase="stopped", global_step=trainer.state.global_step)
        else:
            final = directory / "adapter"
            trainer.save_model(str(final))
            tokenizer.save_pretrained(final)
            save_status(
                phase="completed",
                global_step=trainer.state.global_step,
                metrics=metrics.metrics,
                adapter=str(final),
            )
        return status
    except BaseException as error:
        save_status(phase="failed", error=f"{type(error).__name__}: {error}")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("dataset", type=Path)
    prep.add_argument("--checkpoint", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--gpu", required=True)
    prep.add_argument("--max-length", type=int, default=8192)
    start = commands.add_parser("train")
    start.add_argument("run", type=Path)
    start.add_argument("--execute", action="store_true")
    start.add_argument("--resume", type=Path)
    status = commands.add_parser("status")
    status.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(
            args.dataset,
            args.checkpoint,
            args.output,
            args.gpu,
            max_length=args.max_length,
        )
        print(
            json.dumps(
                {
                    "training_started": False,
                    "data": result["data"],
                    "run": str(args.output),
                }
            )
        )
    elif args.command == "train":
        print(json.dumps(train(args.run, execute=args.execute, resume=args.resume)))
    else:
        print((args.run / "status.json").read_text())


if __name__ == "__main__":
    main()
