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
if [[ $# != 1 || ! "$1" =~ ^(sleep|wake|status)$ ]]; then
  echo "Usage: deploy/vllm-power.sh sleep|wake|status" >&2
  exit 2
fi
export PYTHONPATH="${repo_dir}/agent${PYTHONPATH:+:${PYTHONPATH}}"
exec "${repo_dir}/.venv/bin/python" -m graphmine_agent.llm_power "$1"
