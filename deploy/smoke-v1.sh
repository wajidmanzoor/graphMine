#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "${repo_dir}/agent/.env" ]]; then
  echo "Missing agent/.env; run deploy/configure-v1.sh first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source "${repo_dir}/agent/.env"
set +a
cd "${repo_dir}"
exec .venv/bin/graphmine-agent smoke-test "$@"

