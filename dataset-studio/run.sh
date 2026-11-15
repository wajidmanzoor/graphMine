#!/usr/bin/env bash
# Start Dataset Studio. Uses the GraphMine venv when present so edited outputs
# are validated against the agent's real Pydantic schemas.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${GRAPHMINE_REPO:-$here/../graphMine-database-cypher}"
python="python3"
if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python"; fi
# Account commands (./run.sh users ...) take no server options.
if [[ "${1:-}" == "users" ]]; then exec "$python" "$here/studio.py" "$@"; fi
exec "$python" "$here/studio.py" --repo "$repo" "$@"
