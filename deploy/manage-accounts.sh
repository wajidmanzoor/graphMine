#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${repo_dir}/agent/.env" ]]; then
  set -a
  source "${repo_dir}/agent/.env"
  set +a
fi
cd "${repo_dir}"
umask 077
export PYTHONPATH="${repo_dir}/agent${PYTHONPATH:+:${PYTHONPATH}}"
exec "${repo_dir}/.venv/bin/graphmine-agent" accounts "$@"
