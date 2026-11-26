#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${script_dir}/.." && pwd)"
python_bin="${GRAPHMINE_PYTHON:-${repo_dir}/.venv/bin/python}"
if [[ ! -x "${python_bin}" ]]; then
  python_bin=python3
fi
export PYTHONPATH="${repo_dir}/agent${PYTHONPATH:+:${PYTHONPATH}}"
exec "${python_bin}" -m graphmine_agent.neo4j_local "$@"
