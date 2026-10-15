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

cd "${repo_dir}"
# Prefer this checkout's code when an installed environment is shared by worktrees.
export PYTHONPATH="${repo_dir}/agent${PYTHONPATH:+:${PYTHONPATH}}"
exec "${repo_dir}/.venv/bin/graphmine-agent" serve
