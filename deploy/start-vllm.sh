#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${GRAPHMINE_ENV_FILE:-${repo_dir}/agent/.env}"
if [[ -n "${GRAPHMINE_ENV_FILE:-}" && ! -f "${env_file}" ]]; then
  echo "Configured GRAPHMINE_ENV_FILE does not exist: ${env_file}" >&2
  exit 1
fi
if [[ -f "${env_file}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${env_file}"
  set +a
fi

: "${GRAPHMINE_LLM_GPU_UUID:?Set GRAPHMINE_LLM_GPU_UUID to the LLM GPU UUID}"
model="${GRAPHMINE_LLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"
api_key="${GRAPHMINE_LLM_API_KEY:-local-graphmine}"
vllm_executable="${GRAPHMINE_VLLM_EXECUTABLE:-${repo_dir}/.venv-vllm/bin/vllm}"
max_model_len="${GRAPHMINE_LLM_MAX_MODEL_LEN:-32768}"
max_num_seqs="${GRAPHMINE_LLM_MAX_NUM_SEQS:-2}"
gpu_memory_utilization="${GRAPHMINE_LLM_GPU_MEMORY_UTILIZATION:-0.88}"
revision_args=()
if [[ -n "${GRAPHMINE_LLM_REVISION:-}" ]]; then
  if [[ ! "${GRAPHMINE_LLM_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "GRAPHMINE_LLM_REVISION must be an exact model repository commit." >&2
    exit 1
  fi
  revision_args=(--revision "${GRAPHMINE_LLM_REVISION}" --tokenizer-revision "${GRAPHMINE_LLM_REVISION}")
fi
adapter_args=()
if [[ -n "${GRAPHMINE_LLM_PLANNER_MODEL:-}${GRAPHMINE_LLM_ANALYST_MODEL:-}" ]]; then
  : "${GRAPHMINE_LLM_PLANNER_MODEL:?Set the planner adapter alias}"
  : "${GRAPHMINE_LLM_ANALYST_MODEL:?Set the analyst adapter alias}"
  : "${GRAPHMINE_LLM_PLANNER_ADAPTER_PATH:?Set the trained planner adapter path}"
  : "${GRAPHMINE_LLM_ANALYST_ADAPTER_PATH:?Set the trained analyst adapter path}"
  : "${GRAPHMINE_LLM_PLANNER_ADAPTER_SHA256:?Set the planner safetensors fingerprint}"
  : "${GRAPHMINE_LLM_ANALYST_ADAPTER_SHA256:?Set the analyst safetensors fingerprint}"
  "${repo_dir}/.venv/bin/python" - <<'PY'
import hashlib
import json
import os
import struct
from pathlib import Path

aliases = []
for stage in ("PLANNER", "ANALYST"):
    prefix = "GRAPHMINE_LLM_" + stage
    aliases.append(os.environ[prefix + "_MODEL"])
    directory = Path(os.environ[prefix + "_ADAPTER_PATH"])
    config = json.loads((directory / "adapter_config.json").read_text())
    if config.get("peft_type") != "LORA" or config.get("r", 0) > 16:
        raise SystemExit("Expected a LoRA adapter of rank at most 16")
    with (directory / "adapter_model.safetensors").open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != os.environ[prefix + "_ADAPTER_SHA256"]:
        raise SystemExit(stage.lower() + " adapter fingerprint mismatch")
    if os.environ.get("GRAPHMINE_LLM_MODEL", "Qwen/Qwen3.8-27B-FP8") == "Qwen/Qwen3.8-27B-FP8":
        with (directory / "adapter_model.safetensors").open("rb") as stream:
            size = struct.unpack("<Q", stream.read(8))[0]
            if not 0 < size <= 64 * 1024 * 1024:
                raise SystemExit("Invalid adapter tensor header")
            names = json.loads(stream.read(size))
        tensors = [name for name in names if name != "__metadata__"]
        if not tensors or any(not name.startswith("base_model.model.model.language_model.layers.") for name in tensors):
            raise SystemExit("Export text-only Qwen adapters with graphmine_agent.learning.serving_adapter before serving the conditional-generation wrapper.")
if len(set(aliases)) != 2:
    raise SystemExit("Planner and analyst aliases must differ")
PY
  adapter_args=(
    --enable-lora
    --lora-modules
    "${GRAPHMINE_LLM_PLANNER_MODEL}=${GRAPHMINE_LLM_PLANNER_ADAPTER_PATH}"
    "${GRAPHMINE_LLM_ANALYST_MODEL}=${GRAPHMINE_LLM_ANALYST_ADAPTER_PATH}"
    --max-loras 2 --max-cpu-loras 2 --max-lora-rank 16 --lora-dtype bfloat16
  )
fi

if [[ ! -x "${vllm_executable}" ]]; then
  echo "vLLM is not installed. Run ${repo_dir}/deploy/setup-vllm.sh first." >&2
  exit 1
fi

# JIT helpers such as ninja live beside vLLM in its virtual environment.
# Service managers do not activate that environment before running this script.
export PATH="$(dirname "${vllm_executable}"):${PATH}"

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${GRAPHMINE_LLM_GPU_UUID}"

compat_dir="${GRAPHMINE_CUDA_COMPAT_DIR:-${repo_dir}/.cuda-compat-13-0/usr/local/cuda-13.0/compat}"
if [[ -d "${compat_dir}" ]]; then
  export VLLM_ENABLE_CUDA_COMPATIBILITY=1
  export VLLM_CUDA_COMPATIBILITY_PATH="${compat_dir}"
  export LD_LIBRARY_PATH="${compat_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

exec "${vllm_executable}" serve "${model}" \
  --host 127.0.0.1 \
  --port 8001 \
  --api-key "${api_key}" \
  --tensor-parallel-size 1 \
  --max-model-len "${max_model_len}" \
  --max-num-seqs "${max_num_seqs}" \
  --gpu-memory-utilization "${gpu_memory_utilization}" \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --language-model-only \
  --enable-prefix-caching \
  "${revision_args[@]}" \
  "${adapter_args[@]}"
