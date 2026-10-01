#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${repo_dir}/agent/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${repo_dir}/agent/.env"
  set +a
fi

: "${GRAPHMINE_LLM_GPU_UUID:?Set GRAPHMINE_LLM_GPU_UUID to the LLM GPU UUID}"
model="${GRAPHMINE_LLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"
api_key="${GRAPHMINE_LLM_API_KEY:-local-graphmine}"
vllm_executable="${GRAPHMINE_VLLM_EXECUTABLE:-${repo_dir}/.venv-vllm/bin/vllm}"
max_model_len="${GRAPHMINE_LLM_MAX_MODEL_LEN:-32768}"
max_num_seqs="${GRAPHMINE_LLM_MAX_NUM_SEQS:-64}"
gpu_memory_utilization="${GRAPHMINE_LLM_GPU_MEMORY_UTILIZATION:-0.88}"

if [[ ! -x "${vllm_executable}" ]]; then
  echo "vLLM is not installed. Run ${repo_dir}/deploy/setup-vllm.sh first." >&2
  exit 1
fi

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${GRAPHMINE_LLM_GPU_UUID}"

compat_dir="${repo_dir}/.cuda-compat-13-0/usr/local/cuda-13.0/compat"
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
  --enable-prefix-caching
