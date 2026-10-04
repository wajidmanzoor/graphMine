#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment_file="${repo_dir}/agent/.env"
public_origin="http://127.0.0.1:8000"
api_port=8000
data_root="${repo_dir}/.graphmine-agent"
force=0

usage() {
  cat <<'EOF'
Usage: deploy/configure-v1.sh [options]

Options:
  --origin URL       Browser origin allowed to call the API.
  --port PORT        API/UI listen port (default: 8000).
  --data-root PATH   Persistent SQLite, upload, log, and result directory.
  --output PATH      Environment file to create (default: agent/.env).
  --force            Replace an existing environment file.
  -h, --help         Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --origin)
      public_origin="${2:?--origin requires a URL}"
      shift 2
      ;;
    --port)
      api_port="${2:?--port requires a port number}"
      shift 2
      ;;
    --data-root)
      data_root="${2:?--data-root requires a path}"
      shift 2
      ;;
    --output)
      environment_file="${2:?--output requires a path}"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "${api_port}" =~ ^[0-9]+$ ]] || ((api_port < 1 || api_port > 65535)); then
  echo "--port must be an integer between 1 and 65535" >&2
  exit 2
fi
if [[ ! "${public_origin}" =~ ^https?://[^[:space:]]+$ ]]; then
  echo "--origin must be one HTTP(S) origin without whitespace" >&2
  exit 2
fi
if [[ "${data_root}" =~ [[:space:]] || "${environment_file}" =~ [[:space:]] ]]; then
  echo "V1 environment and data-root paths must not contain whitespace" >&2
  exit 2
fi

if [[ -e "${environment_file}" && "${force}" -ne 1 ]]; then
  echo "Refusing to replace ${environment_file}; pass --force to rotate it." >&2
  exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi is required to discover stable GPU UUIDs." >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate the API token." >&2
  exit 1
fi

mapfile -t gpu_uuids < <(
  nvidia-smi --query-gpu=uuid --format=csv,noheader | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
)
if ((${#gpu_uuids[@]} < 2)); then
  echo "GraphMine v1 requires two visible GPUs; found ${#gpu_uuids[@]}." >&2
  exit 1
fi

mkdir -p "$(dirname "${environment_file}")" "${data_root}"
umask 077
api_token="$(openssl rand -hex 32)"
cat >"${environment_file}" <<EOF
GRAPHMINE_API_HOST=0.0.0.0
GRAPHMINE_API_PORT=${api_port}
GRAPHMINE_API_TOKEN=${api_token}
GRAPHMINE_ALLOWED_ORIGINS=http://localhost:${api_port},http://127.0.0.1:${api_port},${public_origin}

GRAPHMINE_LLM_GPU_UUID=${gpu_uuids[0]}
GRAPHMINE_GRAPH_GPU_UUID=${gpu_uuids[1]}
GRAPHMINE_LLM_ENABLED=true
GRAPHMINE_LLM_BASE_URL=http://127.0.0.1:8001/v1
GRAPHMINE_LLM_API_KEY=local-graphmine
GRAPHMINE_LLM_MODEL=Qwen/Qwen3.8-27B-FP8
GRAPHMINE_LLM_MAX_MODEL_LEN=32768
GRAPHMINE_LLM_MAX_NUM_SEQS=64
GRAPHMINE_LLM_GPU_MEMORY_UTILIZATION=0.88
GRAPHMINE_LLM_ROUTE_REASONING_EFFORT=none
GRAPHMINE_LLM_PLAN_REASONING_EFFORT=medium
GRAPHMINE_LLM_ANALYST_REASONING_EFFORT=medium
GRAPHMINE_LLM_ROUTE_MAX_TOKENS=768
GRAPHMINE_LLM_PLAN_MAX_TOKENS=3072
GRAPHMINE_LLM_ANALYST_MAX_TOKENS=3072

GRAPHMINE_AGENT_DATA_ROOT=${data_root}
GRAPHMINE_BINARY=${repo_dir}/library/build/graphmine
GRAPHMINE_BACKEND_POLICY=${repo_dir}/agent/backend_policy.json
GRAPHMINE_MAX_UPLOAD_BYTES=2147483648
GRAPHMINE_JOB_TIMEOUT_SECONDS=86400
GRAPHMINE_RESULT_SUMMARY_ITEMS=50

# Keep model and compilation caches in the writable service-state tree. This is
# required by the hardened systemd unit, which cannot read a service user's home.
HF_HOME=${data_root}/huggingface
XDG_CACHE_HOME=${data_root}/cache
VLLM_CACHE_ROOT=${data_root}/vllm-cache
EOF
chmod 600 "${environment_file}"

echo "Created ${environment_file} with mode 0600."
echo "LLM GPU:   ${gpu_uuids[0]}"
echo "Graph GPU: ${gpu_uuids[1]}"
echo "Allowed browser origin: ${public_origin}"
echo "API/UI port: ${api_port}"
echo "The API token is stored only in the environment file."
