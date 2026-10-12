import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from graphmine_agent.learning.serving_adapter import (
    SOURCE_PREFIX,
    TARGET_PREFIX,
    export,
    read_header,
)


@pytest.fixture
def text_adapter(tmp_path):
    source = tmp_path / "trained"
    source.mkdir()
    config = {
        "peft_type": "LORA",
        "r": 2,
        "rank_pattern": {},
        "target_modules": ["q_proj"],
    }
    (source / "adapter_config.json").write_text(json.dumps(config))
    prefix = SOURCE_PREFIX + "0.self_attn.q_proj."
    header = {
        "__metadata__": {"format": "pt"},
        prefix + "lora_A.weight": {
            "dtype": "F32",
            "shape": [2, 3],
            "data_offsets": [0, 24],
        },
        prefix + "lora_B.weight": {
            "dtype": "F32",
            "shape": [4, 2],
            "data_offsets": [24, 56],
        },
    }
    encoded = json.dumps(header).encode()
    payload = struct.pack("<14f", *[value / 1000 for value in range(14)])
    weights = source / "adapter_model.safetensors"
    weights.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)
    serving = tmp_path / "config.json"
    serving.write_text(
        json.dumps(
            {
                "model_type": "qwen3_5",
                "architectures": ["Qwen3_5ForConditionalGeneration"],
            }
        )
    )
    return source, serving, payload


def test_serving_export_changes_names_but_preserves_every_tensor_byte(
    tmp_path, text_adapter
):
    source, serving, payload = text_adapter
    original = (source / "adapter_model.safetensors").read_bytes()
    destination = tmp_path / "serving"
    receipt = export(source, destination, serving)
    header, offset = read_header(destination / "adapter_model.safetensors")
    assert set(header) == {
        "__metadata__",
        TARGET_PREFIX + "0.self_attn.q_proj.lora_A.weight",
        TARGET_PREFIX + "0.self_attn.q_proj.lora_B.weight",
    }
    assert (destination / "adapter_model.safetensors").read_bytes()[offset:] == payload
    assert (source / "adapter_model.safetensors").read_bytes() == original
    assert (source / "adapter_config.json").read_bytes() == (
        destination / "adapter_config.json"
    ).read_bytes()
    assert receipt["projection_count"] == 1 and receipt["parameters"] == 14
    assert receipt["source_weights_sha256"] != receipt["weights_sha256"]
    with pytest.raises(ValueError, match="new serving"):
        export(source, destination, serving)


@pytest.mark.parametrize(
    "mutation", ["unknown_prefix", "gap", "unpaired", "rank", "model"]
)
def test_serving_export_rejects_incompatible_or_incomplete_weights(
    tmp_path, text_adapter, mutation
):
    source, serving, payload = text_adapter
    path = source / "adapter_model.safetensors"
    header, _ = read_header(path)
    a = SOURCE_PREFIX + "0.self_attn.q_proj.lora_A.weight"
    b = SOURCE_PREFIX + "0.self_attn.q_proj.lora_B.weight"
    if mutation == "unknown_prefix":
        header["other.model.lora_A.weight"] = header.pop(a)
    elif mutation == "gap":
        header[b]["data_offsets"] = [28, 60]
    elif mutation == "unpaired":
        header.pop(b)
    elif mutation == "rank":
        header[a]["shape"] = [3, 2]
    else:
        serving.write_text('{"model_type":"another_model"}')
    encoded = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)
    destination = tmp_path / "bad-export"
    with pytest.raises(ValueError):
        export(source, destination, serving)
    assert not destination.exists()


@pytest.mark.parametrize("converted", [False, True])
def test_launcher_rejects_unmatched_names_before_model_loading(
    tmp_path, text_adapter, converted
):
    source, serving, _ = text_adapter
    if converted:
        destination = tmp_path / "exported"
        export(source, destination, serving)
        source = destination
    repo = tmp_path / "launcher-repo"
    (repo / "deploy").mkdir(parents=True)
    script = repo / "deploy/start-vllm.sh"
    shutil.copyfile(
        Path(__file__).resolve().parents[2] / "deploy/start-vllm.sh", script
    )
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(sys.executable)
    (repo / ".venv-vllm/bin").mkdir(parents=True)
    stub = repo / ".venv-vllm/bin/vllm"
    stub.write_text("#!/bin/sh\nprintf 'model-launch-reached\\n'\n")
    stub.chmod(0o700)
    (repo / "agent").mkdir()
    sha = hashlib.sha256(
        (source / "adapter_model.safetensors").read_bytes()
    ).hexdigest()
    settings = {
        "GRAPHMINE_LLM_GPU_UUID": "authored-cpu-fixture",
        "GRAPHMINE_LLM_MODEL": "Qwen/Qwen3.8-27B-FP8",
    }
    for stage in ("PLANNER", "ANALYST"):
        prefix = "GRAPHMINE_LLM_" + stage
        settings[prefix + "_MODEL"] = stage.lower()
        settings[prefix + "_ADAPTER_PATH"] = str(source)
        settings[prefix + "_ADAPTER_SHA256"] = sha
    (repo / "agent/.env").write_text(
        "\n".join(key + "=" + value for key, value in settings.items()) + "\n"
    )
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, check=False
    )
    if converted:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "model-launch-reached"
    else:
        assert result.returncode != 0
        assert "serving_adapter" in result.stderr
        assert "model-launch-reached" not in result.stdout
