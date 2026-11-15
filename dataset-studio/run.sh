#!/usr/bin/env bash
# Start Dataset Studio. Uses the GraphMine venv when present so edited outputs
# are validated against the agent's real Pydantic schemas.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_repo="$here/.."
if [[ ! -d "$default_repo/agent/graphmine_agent" ]]; then
  default_repo="$here/../graphMine-database-cypher"
fi
repo="${GRAPHMINE_REPO:-$default_repo}"
python="python3"
if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python"; fi
# Account commands (./run.sh users ...) take no server options.
if [[ "${1:-}" == "users" ]]; then exec "$python" "$here/studio.py" "$@"; fi
exec "$python" "$here/studio.py" --repo "$repo" "$@"
