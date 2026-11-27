# Tentō Phase 0 probes

These are investigation tools, not the semantic feature or its installer. The
[Phase 0 report](../../agent/evaluation/reports/tento_phase0_20261127.md) records
the findings and the reasons implementation cannot yet advance under the
unchanged brief. The proposed [author requests](AUTHOR_REQUESTS.md) are a local
draft; nothing has been sent to the Tentō author.

## Reproduce the build

The tested source is `zacharyzhijun/francis` at
`62e124217e2c0f82e327136b5888263e95671fae`. Access to that private repository is
required. The tested Linux host has Python 3.12.3 and its development headers,
GCC 13.3, CMake, Ninja, OpenSSL 3 headers/libraries, `make`, `uv`, and `gh`.
Run from the GraphMine repository root, using a fresh scratch location:

```bash
TENTO_PHASE0_ROOT="$PWD/../validation/tento-phase0-reproduction"
TENTO_SOURCE="$TENTO_PHASE0_ROOT/francis"
mkdir -p "$TENTO_PHASE0_ROOT"
gh repo clone zacharyzhijun/francis "$TENTO_SOURCE" -- --depth 1
git -C "$TENTO_SOURCE" fetch origin 62e124217e2c0f82e327136b5888263e95671fae
git -C "$TENTO_SOURCE" checkout --detach 62e124217e2c0f82e327136b5888263e95671fae

UV_CACHE_DIR="$TENTO_PHASE0_ROOT/uv-cache" \
  uv venv --python /usr/bin/python3 "$TENTO_PHASE0_ROOT/venv"
UV_CACHE_DIR="$TENTO_PHASE0_ROOT/uv-cache" \
  uv pip install --python "$TENTO_PHASE0_ROOT/venv/bin/python" 'numpy==2.5.5'

make -C "$TENTO_SOURCE/ladybug/tools/python_api" \
  -o requirements build-pybind-subdir \
  LBUG_SOURCE_DIR="$TENTO_SOURCE/ladybug" \
  PYTHON_BIN="$TENTO_PHASE0_ROOT/venv/bin/python" \
  CMAKE_BUILD_PARALLEL_LEVEL=8 \
  > "$TENTO_PHASE0_ROOT/build.log" 2>&1
```

`LBUG_SOURCE_DIR` must explicitly select Tentō's own `ladybug/` directory. The
Makefile's default assumes a different sibling layout. `-o requirements` skips
the convenience target that installs the full development stack, including
Torch and formatting tools. The isolated interpreter, vendored pybind11 and
source build suffice for these probes. It does not skip compilation.

Do not run `make sync`, `make build` or `bootstrap-capi` for this investigation:
those targets download an upstream C-API binary. No upstream engine wheel was
used in the verified build. The probe imports the native module from the given
source tree, forces the pybind backend and checks the semantic function list.

## Run the probes

```bash
"$TENTO_PHASE0_ROOT/venv/bin/python" deploy/tento/probe_phase0.py \
  --source "$TENTO_SOURCE" \
  --output "$TENTO_PHASE0_ROOT/probe-results.json"

# Run one small reproduction independently:
"$TENTO_PHASE0_ROOT/venv/bin/python" deploy/tento/probe_phase0.py \
  --source "$TENTO_SOURCE" --case limits
```

| Case | Evidence |
| --- | --- |
| `functions` | Exact imported artifact/hash, required function names, `mock:echo` |
| `values` | Nodes, relationships, paths, scalars, logical types, IDs, multiple labels, relationship key syntax, bulk COPY |
| `providers` | Alias endpoint/model routing, missing credentials, environment-key precedence, outbound request fields, rejected thinking controls |
| `limits` | Per-expression limits, schema fallback, HTTP retries and reset-on-read usage counters |
| `cache` | Reuse within one memory database, fresh processes, temporary disk-backed positive control, public answer-summary columns |
| `explain` | Model calls during EXPLAIN, behavior with model planning disabled, PROFILE output |
| `interrupt` | Python interruption, query timeout, live usage through a second connection, hard termination and process reaping |
| `license` | Engine license text/hash and Python package license declaration |

All model traffic stays in mock execution or synthetic loopback HTTP fixtures.
The runner removes inherited `OPENROUTER_API_KEY` and `LLM_API_KEY`; the fixtures
use invented credentials and record only which fixture value was selected, never
the authorization header. No production snapshot, model service or account is
accessed. Databases use a 128 MiB buffer pool and two compute threads. The cache
positive control uses a temporary disk database and deletes it on exit; it is
evidence of the storage distinction, not a proposed production workaround.

Each case runs in a separate process with a 45-second observation deadline.
The cancellation probe deliberately blocks its fake provider and kills only its
own child. Fixture shutdown releases blocked handlers. A complete eight-case
run took about seven seconds on the inspected host.

`probe_status: completed` means the diagnostic ran and its observations matched
the pinned revision. Several diagnostics deliberately reproduce integration
blockers. It does **not** mean the feature is ready or that Phase 0's feasibility
gate passed. When evaluating an author fix, review and update the expected
observations rather than treating these reproductions as a product acceptance
suite.
