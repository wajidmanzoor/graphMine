"""Export text-only Qwen3.5 LoRA names for its conditional-generation wrapper.

Tensor payload bytes remain identical. No base model, GPU or training package is
required. The original adapter remains the authoritative training artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
from pathlib import Path

from ..history import HistoryStore

SOURCE_PREFIX = "base_model.model.model.layers."
TARGET_PREFIX = "base_model.model.model.language_model.layers."
PROJECTIONS = {
    "self_attn": {"q_proj", "k_proj", "v_proj", "o_proj"},
    "linear_attn": {"in_proj_a", "in_proj_b", "in_proj_qkv", "in_proj_z", "out_proj"},
    "mlp": {"gate_proj", "up_proj", "down_proj"},
}


def mapped_name(name):
    if not name.startswith(SOURCE_PREFIX):
        raise ValueError("Expected a text-only Qwen adapter tensor: " + name)
    suffix = name.removeprefix(SOURCE_PREFIX)
    match = re.fullmatch(
        r"([0-9]+)\.([a-z_]+)\.([a-z_]+)\.(lora_A|lora_B)\.weight", suffix
    )
    if not match or match[3] not in PROJECTIONS.get(match[2], set()):
        raise ValueError("Unexpected Qwen adapter module: " + name)
    return TARGET_PREFIX + suffix


def read_header(path):
    with path.open("rb") as stream:
        size_bytes = stream.read(8)
        if len(size_bytes) != 8:
            raise ValueError("Incomplete safetensors header")
        size = struct.unpack("<Q", size_bytes)[0]
        if not 0 < size <= 64 * 1024 * 1024:
            raise ValueError("Unexpected safetensors header size")
        header = json.loads(stream.read(size))
    return header, 8 + size


def export(source, destination, serving_config):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Choose a new serving adapter directory")
    model_config = json.loads(serving_config.read_text())
    if model_config.get(
        "model_type"
    ) != "qwen3_5" or "Qwen3_5ForConditionalGeneration" not in model_config.get(
        "architectures", []
    ):
        raise ValueError(
            "This export requires the Qwen3.5 conditional-generation wrapper"
        )
    config_path = source / "adapter_config.json"
    config = json.loads(config_path.read_text())
    rank = config.get("r", 0)
    if (
        config.get("peft_type") != "LORA"
        or not 1 <= rank <= 16
        or config.get("rank_pattern")
    ):
        raise ValueError("Expected a uniform-rank LoRA adapter of rank at most 16")
    weights = source / "adapter_model.safetensors"
    header, offset = read_header(weights)
    renamed = {}
    mapping = {}
    intervals = []
    inventory = {}
    parameters = 0
    for name, info in header.items():
        if name == "__metadata__":
            renamed[name] = info
            continue
        target = mapped_name(name)
        shape = info["shape"]
        if len(shape) != 2 or any(
            type(value) is not int or value < 1 for value in shape
        ):
            raise ValueError("Expected two-dimensional LoRA tensors")
        side = name.rsplit(".", 2)[1]
        if shape[0 if side == "lora_A" else 1] != rank:
            raise ValueError("Tensor shape disagrees with configured LoRA rank")
        width = {"F32": 4, "BF16": 2, "F16": 2}.get(info["dtype"])
        start, end = info["data_offsets"]
        if not width or end - start != math.prod(shape) * width:
            raise ValueError("Invalid tensor payload size or dtype")
        intervals.append((start, end))
        inventory.setdefault(name.rsplit(".", 2)[0], set()).add(side)
        parameters += math.prod(shape)
        renamed[target] = info
        mapping[name] = target
    if not mapping or any(
        sides != {"lora_A", "lora_B"} for sides in inventory.values()
    ):
        raise ValueError("Each projection must have both LoRA matrices")
    cursor = 0
    for start, end in sorted(intervals):
        if start != cursor:
            raise ValueError("Tensor payload has gaps or overlaps")
        cursor = end
    if offset + cursor != weights.stat().st_size:
        raise ValueError("Safetensors payload length mismatch")
    destination.mkdir(parents=True)
    target_weights = destination / weights.name
    header_bytes = json.dumps(renamed, separators=(",", ":")).encode()
    header_bytes += b" " * (-len(header_bytes) % 8)
    payload_hash = hashlib.sha256()
    with weights.open("rb") as original, target_weights.open("xb") as converted:
        original.seek(offset)
        converted.write(struct.pack("<Q", len(header_bytes)))
        converted.write(header_bytes)
        while chunk := original.read(8 * 1024 * 1024):
            payload_hash.update(chunk)
            converted.write(chunk)
    with target_weights.open("rb") as stream:
        stream.seek(8 + len(header_bytes))
        copied_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if copied_hash != payload_hash.hexdigest():
        raise RuntimeError("Export changed the tensor payload")
    shutil.copyfile(config_path, destination / config_path.name)
    receipt = {
        "version": "qwen3-5-serving-namespace-v1",
        "source": str(source),
        "destination": str(destination),
        "source_weights_sha256": HistoryStore.digest(weights),
        "weights_sha256": HistoryStore.digest(target_weights),
        "config_sha256": HistoryStore.digest(config_path),
        "serving_config_sha256": HistoryStore.digest(serving_config),
        "tensor_payload_sha256": copied_hash,
        "tensor_count": len(mapping),
        "projection_count": len(inventory),
        "parameters": parameters,
        "mapping": mapping,
        "scope": "Only safetensors header names changed; tensor bytes and adapter hyperparameters are identical. Training quality and runtime activation require separate checks.",
    }
    HistoryStore.write(destination / "serving_export.json", receipt)
    return {key: value for key, value in receipt.items() if key != "mapping"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serving-config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output, args.serving_config), indent=2))


if __name__ == "__main__":
    main()
