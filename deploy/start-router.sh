#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${repo_dir}/agent/.env" ]]; then
  set -a
  source "${repo_dir}/agent/.env"
  set +a
fi
export GRAPHMINE_ROUTER_SUITE="${GRAPHMINE_ROUTER_SUITE:-${repo_dir}/.graphmine-learning/adapter-business-suite-new-v1}"
export GRAPHMINE_ROUTER_MODEL="${GRAPHMINE_ROUTER_MODEL:-graphmine-business-v1}"
export GRAPHMINE_ROUTER_ADAPTER_SHA256="${GRAPHMINE_ROUTER_ADAPTER_SHA256:-dd7017735094300c4a89f217cb094c0d8b9981d1c7d86182596a7a6f7ef5f4d6}"
export GRAPHMINE_LLM_API_KEY="${GRAPHMINE_LLM_API_KEY:-local-graphmine}"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${GRAPHMINE_GRAPH_GPU_UUID:?Set the compute GPU UUID}"
compat_dir="${repo_dir}/.cuda-compat-13-0/usr/local/cuda-13.0/compat"
if [[ -d "${compat_dir}" ]]; then
  export LD_LIBRARY_PATH="${compat_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi
export HF_HUB_OFFLINE=1
cd "${repo_dir}"
exec "${repo_dir}/.venv-training/bin/python" -m uvicorn \
  graphmine_agent.adapter_server:create_router_app --factory \
  --host 127.0.0.1 --port "${GRAPHMINE_ROUTER_PORT:-8002}" --workers 1
