"""Versioned multi-stage QLoRA exports and local training for two adapters."""

from __future__ import annotations

import argparse
import fcntl
import importlib.metadata
import json
import os
import re
from collections import Counter
from pathlib import Path

from ..config import Settings
from ..history import HistoryStore
from ..llm import runtime_messages, runtime_schema
from ..models import LLMMode, utc_now
from .catalog_suite import digest
from .dual_review import VALIDATION_ERRORS, verified_target
from .dual_teacher import SCHEMAS
from .finetune import assistant_only_tokens, fit_adapter

VERSION = "dual-stage-qlora-v1"
PACKAGES = (
    "torch",
    "transformers",
    "peft",
    "bitsandbytes",
    "accelerate",
    "datasets",
    "flash-linear-attention",
)
IMPLEMENTATION_FILES = (
    "learning/dual_finetune.py",
    "learning/dual_teacher.py",
    "learning/dual_review.py",
    "learning/finetune.py",
    "llm.py",
    "models.py",
    "analysis.py",
)


def implementation():
    root = Path(__file__).resolve().parent.parent
    return {name: HistoryStore.digest(root / name) for name in IMPLEMENTATION_FILES}


def export(settings, root, destination, adapter):
    if destination.exists():
        raise ValueError("Exports are immutable; choose a new directory")
    rows = {"train": [], "validation": []}
    provenance = []
    rejected = []
    lineages = {}
    cases = json.loads((root / "corpus.json").read_text())["cases"]
    for case in cases:
        prior = lineages.setdefault(case["lineage"], case["split"])
        if prior != case["split"]:
            raise ValueError("A source lineage occurs in multiple splits")
    for path in sorted((root / "teacher-inputs").glob("*.json")):
        job = json.loads(path.read_text())
        if job["adapter"] != adapter:
            continue
        if job["split"] not in rows or lineages.get(job["lineage"]) != job["split"]:
            raise ValueError("Unknown source lineage or held-out contamination")
        target_path = root / "teacher-targets" / path.name
        if not target_path.exists():
            raise ValueError(f"Unfinished teacher generation: {path.name}")
        artifact = json.loads(target_path.read_text())
        if (
            artifact["input_sha256"] != job["sha256"]
            or digest({k: v for k, v in job.items() if k != "sha256"}) != job["sha256"]
        ):
            raise ValueError("Teacher input binding failed")
        try:
            target = verified_target(settings, root, job, artifact)
        except VALIDATION_ERRORS as error:
            rejected.append(
                {
                    "id": job["id"],
                    "reason": str(error),
                    "artifact_sha256": HistoryStore.digest(target_path),
                }
            )
            continue
        schema = SCHEMAS[job["schema"]]
        expected_messages = runtime_messages(
            mode=LLMMode(job["mode"]),
            schema=schema,
            user_payload=job["user_payload"],
            conversation=job["conversation"],
        )
        if (
            expected_messages != job["messages"]
            or runtime_schema(schema, job["user_payload"]) != job["output_schema"]
        ):
            raise ValueError("Teacher contract no longer matches production")
        row = {
            "messages": job["messages"]
            + [{"role": "assistant", "content": target.model_dump_json()}]
        }
        rows[job["split"]].append(row)
        provenance.append(
            {
                "id": job["id"],
                "case_id": job["case_id"],
                "split": job["split"],
                "lineage": job["lineage"],
                "stage": job["schema"],
                "row_sha256": digest(row),
                "input_sha256": job["sha256"],
                "teacher_sha256": HistoryStore.digest(target_path),
                "teacher_profile": artifact["profile"],
                "schema_sha256": digest(job["output_schema"]),
                "human_review": "unreviewed",
            }
        )
    if len(rows["train"]) < 32 or len(rows["validation"]) < 8:
        raise ValueError(
            "At least 32 accepted training and 8 source-separated validation rows required"
        )
    stages = {row["stage"] for row in provenance}
    required = (
        {"RouteDecision", "PlanDraft", "TurnDecision"}
        if adapter == "planner"
        else {"GroundedNarrative"}
    )
    if not required <= stages:
        raise ValueError(
            f"Missing required stage coverage: {sorted(required - stages)}"
        )
    destination.mkdir(parents=True, mode=0o700)
    files = {}
    for split, items in rows.items():
        path = destination / (split + ".jsonl")
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
        )
        files[split] = HistoryStore.digest(path)
    report = {
        "version": VERSION,
        "adapter": adapter,
        "created_at": utc_now().isoformat(),
        "files": files,
        "rows": provenance,
        "quarantined_excluded": rejected,
        "source_splits": lineages,
        "source_root": str(root.resolve()),
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
        "implementation": implementation(),
        "coverage": dict(Counter(item["stage"] for item in provenance)),
        "scope": "Supervised final structured targets from max-effort ChatGPT, checked against executed/reference evidence. No private reasoning traces or human feedback labels. Source/family separated validation; final test excluded.",
    }
    HistoryStore.write(destination / "provenance.json", report)
    return {
        "rows": {split: len(values) for split, values in rows.items()},
        "excluded": len(rejected),
        "coverage": report["coverage"],
    }


def read_export(directory):
    provenance = json.loads((directory / "provenance.json").read_text())
    if (
        provenance["version"] != VERSION
        or provenance["implementation"] != implementation()
    ):
        raise ValueError(
            "Export version or implementation changed; re-export and prepare"
        )
    rows = {}
    seen = set()
    for split in ("train", "validation"):
        path = directory / (split + ".jsonl")
        if HistoryStore.digest(path) != provenance["files"][split]:
            raise ValueError("Training export changed")
        rows[split] = [json.loads(line) for line in path.read_text().splitlines()]
        sources = [row for row in provenance["rows"] if row["split"] == split]
        if len(rows[split]) != len(sources):
            raise ValueError("Row provenance count differs")
        for row, source in zip(rows[split], sources, strict=True):
            if (
                source["id"] in seen
                or digest(row) != source["row_sha256"]
                or provenance["source_splits"][source["lineage"]] != split
            ):
                raise ValueError("Duplicate, modified, or leaked training row")
            seen.add(source["id"])
            messages = row["messages"]
            if (
                messages[0]["role"] != "system"
                or messages[-2]["role"] != "user"
                or messages[-1]["role"] != "assistant"
            ):
                raise ValueError("Invalid supervised conversation structure")
            SCHEMAS[source["stage"]].model_validate_json(messages[-1]["content"])
    return provenance, rows


def prepare(dataset, checkpoint, destination, gpu, *, max_length=16384, epochs=2):
    from transformers import AutoTokenizer

    if destination.exists():
        raise ValueError("Training runs are immutable; choose a new directory")
    if not re.fullmatch(r"GPU-[0-9a-f-]{36}", gpu):
        raise ValueError("An explicit GPU UUID is required")
    if not 1 <= epochs <= 5 or not 2048 <= max_length <= 32768:
        raise ValueError("Unsupported pilot epoch count or sequence limit")
    provenance, rows = read_export(dataset)
    base = checkpoint.resolve()
    model_config = json.loads((base / "config.json").read_text())
    if (
        model_config.get("model_type") != "qwen3_5"
        or "quantization_config" in model_config
    ):
        raise ValueError(
            "Use the original unquantized Qwen text checkpoint for NF4 training"
        )
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    encoded = {
        split: [
            assistant_only_tokens(tokenizer, row["messages"], max_length)
            for row in values
        ]
        for split, values in rows.items()
    }
    destination.mkdir(parents=True, mode=0o700)
    data = {}
    for split, items in encoded.items():
        path = destination / (split + ".tokens.json")
        HistoryStore.write(path, items)
        lengths = [len(item["input_ids"]) for item in items]
        data[split] = {
            "path": path.name,
            "sha256": HistoryStore.digest(path),
            "rows": len(items),
            "min_tokens": min(lengths),
            "max_tokens": max(lengths),
            "supervised_tokens": sum(
                sum(label != -100 for label in item["labels"]) for item in items
            ),
        }
    print("Hashing the pinned local checkpoint...", flush=True)
    files = {
        p.name: HistoryStore.digest(p)
        for p in sorted(base.iterdir())
        if p.suffix in {".json", ".safetensors", ".jinja", ".model"}
    }
    run = {
        "version": VERSION,
        "adapter": provenance["adapter"],
        "created_at": utc_now().isoformat(),
        "implementation": implementation(),
        "dataset": str(dataset.resolve()),
        "dataset_provenance_sha256": HistoryStore.digest(dataset / "provenance.json"),
        "base_checkpoint": str(base),
        "base_model": "Qwen/Qwen3.8-27B",
        "base_revision": base.name,
        "checkpoint_files": files,
        "gpu": gpu,
        "data": data,
        "max_sequence_length": max_length,
        "packages": {name: importlib.metadata.version(name) for name in PACKAGES},
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": 1,
            "gradient_accumulation_steps": 4,
            "learning_rate": 0.00005,
            "lora_rank": 16,
            "lora_alpha": 32,
            "lora_dropout": 0.05,
            "save_total_limit": 3,
            "seed": 20261007,
        },
        "training_started": False,
        "scope": provenance["scope"],
    }
    HistoryStore.write(destination / "run.json", run)
    return {"adapter": run["adapter"], "data": data, "run": str(destination)}


def train(directory, *, execute=False, resume=None):
    directory = directory.resolve()
    with (directory / ".trainer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another trainer owns this run") from error
        config = json.loads((directory / "run.json").read_text())
        if config["version"] != VERSION or config["implementation"] != implementation():
            raise ValueError("Training implementation changed; prepare a new run")
        dataset = Path(config["dataset"])
        if (
            HistoryStore.digest(dataset / "provenance.json")
            != config["dataset_provenance_sha256"]
        ):
            raise ValueError("Dataset provenance changed")
        read_export(dataset)
        tokenized = {}
        for split, info in config["data"].items():
            path = directory / info["path"]
            if path.parent != directory or HistoryStore.digest(path) != info["sha256"]:
                raise ValueError("Prepared tokens changed")
            tokenized[split] = json.loads(path.read_text())
        if not execute:
            return {
                "training_started": False,
                "adapter": config["adapter"],
                "data": config["data"],
            }
        if os.environ.get("CUDA_VISIBLE_DEVICES") != config["gpu"]:
            raise ValueError("CUDA_VISIBLE_DEVICES must equal the prepared GPU UUID")
        output = directory / "checkpoints"
        if resume:
            resume = resume.resolve()
            if resume.parent != output or not (resume / "trainer_state.json").is_file():
                raise ValueError("Resume only a saved checkpoint from this run")
        elif output.exists():
            raise ValueError(
                "Training already started; explicitly resume its checkpoint"
            )
        for name, expected in config["packages"].items():
            if importlib.metadata.version(name) != expected:
                raise ValueError(f"Training dependency changed: {name}")
        for name, expected in config["checkpoint_files"].items():
            if HistoryStore.digest(Path(config["base_checkpoint"]) / name) != expected:
                raise ValueError(f"Base checkpoint changed: {name}")
        return fit_adapter(directory, config, tokenized, resume=resume)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exp = commands.add_parser("export")
    exp.add_argument("root", type=Path)
    exp.add_argument("--output", type=Path, required=True)
    exp.add_argument("--adapter", choices=["planner", "analyst"], required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("dataset", type=Path)
    prep.add_argument("--checkpoint", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--gpu", required=True)
    prep.add_argument("--max-length", type=int, default=16384)
    prep.add_argument("--epochs", type=int, default=2)
    run = commands.add_parser("train")
    run.add_argument("run", type=Path)
    run.add_argument("--execute", action="store_true")
    run.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        result = export(Settings.from_env(), args.root, args.output, args.adapter)
    elif args.command == "prepare":
        result = prepare(
            args.dataset,
            args.checkpoint,
            args.output,
            args.gpu,
            max_length=args.max_length,
            epochs=args.epochs,
        )
    else:
        result = train(args.run, execute=args.execute, resume=args.resume)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
