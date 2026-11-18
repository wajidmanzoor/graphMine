#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${GRAPHMINE_ENV_FILE:-${repo_dir}/agent/.env}"
if [[ ! -f "${env_file}" ]]; then
  echo "Configured GRAPHMINE_ENV_FILE does not exist: ${env_file}" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a
cd "${repo_dir}"
export CUDA_VISIBLE_DEVICES=''
export PYTHONPATH="${repo_dir}/agent:${GRAPHMINE_RUNTIME_REPOSITORY:-${repo_dir}}/python/graphmine"
exec "${repo_dir}/.venv/bin/python" -m graphmine_agent.backend_learning.model_cli train
