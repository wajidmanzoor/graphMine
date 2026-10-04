#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_dir}"

if [[ -f agent/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source agent/.env
  set +a
fi
if [[ -n "${GRAPHMINE_GRAPH_GPU_UUID:-}" ]]; then
  export CUDA_DEVICE_ORDER=PCI_BUS_ID
  export CUDA_VISIBLE_DEVICES="${GRAPHMINE_GRAPH_GPU_UUID}"
fi

if [[ "$(tr -d '[:space:]' < VERSION)" != "1.0.0" ]]; then
  echo "VERSION must contain 1.0.0" >&2
  exit 1
fi

cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build --parallel
test "$(library/build/graphmine --version)" = "GraphMine 1.0.0"
ctest --test-dir library/build --output-on-failure

if [[ ! -x .venv/bin/pytest ]]; then
  echo "Missing .venv. Install with: python3 -m venv .venv && .venv/bin/pip install -e 'agent[test]'" >&2
  exit 1
fi
.venv/bin/pytest agent/tests -q
.venv/bin/pytest agent/browser_tests -q
node --check agent/graphmine_agent/static/app.js
for script in deploy/*.sh; do
  bash -n "${script}"
done

GRAPHMINE_LLM_ENABLED=false .venv/bin/graphmine-agent check

generated_before="$(mktemp)"
generated_after="$(mktemp)"
trap 'rm -f "${generated_before}" "${generated_after}"' EXIT
snapshot_generated_contracts() {
  sha256sum graphmine_catalog.json graphmine_manifest.json \
    library/manifests/*.json agent/schemas/*.json | sort -k2
}
snapshot_generated_contracts >"${generated_before}"
node tools/build_catalog.mjs
.venv/bin/graphmine-agent export-schemas agent/schemas
snapshot_generated_contracts >"${generated_after}"
if ! diff -u "${generated_before}" "${generated_after}"; then
  echo "Generated catalogs or schemas were stale before validation." >&2
  exit 1
fi

echo "GraphMine v1 static, contract, API, and native acceptance gates passed."
