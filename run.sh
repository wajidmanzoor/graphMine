#!/usr/bin/env bash
# Start Dataset Studio. Uses the GraphMine venv when present so edited outputs
# are validated against the agent's real Pydantic schemas.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${GRAPHMINE_REPO:-$here/../graphMine-repo}"
python="python3"
if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python"; fi
exec "$python" "$here/studio.py" --repo "$repo" "$@"
