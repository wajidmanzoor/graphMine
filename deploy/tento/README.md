# Tentō source build and verification

Phase 1 provides a pinned submodule, a local wheel builder, a lazy optional-engine
loader and a bounded mock smoke. It does not enable semantic queries in the app.
The user authorized this installation work after Phase 0; author fixes remain
required before live acceptance and Phase 2. The
[Phase 0 report](../../agent/evaluation/reports/tento_phase0_20261127.md) records
the unsupported contracts. The [author requests](AUTHOR_REQUESTS.md) are a local
draft; nothing has been sent to the author.

The [Phase 1 report](../../agent/evaluation/reports/tento_phase1_20261127.md)
records the installed artifact, startup/mock verification and regression limits.

## Phase 1 installation

Use Linux, CPython 3.12 with development headers, a C++20 compiler, OpenSSL 3
development files, CMake, Ninja, make, and uv. Python 3.12 is the tested ABI.
The builder also accepts 3.13–3.14 but those ABIs have not been validated. The
pinned build-time NumPy requires Python 3.12 or newer; GraphMine without the
semantic extra retains its existing Python requirement.
Access to the private GitHub repository is required; the submodule uses SSH.
Run from the GraphMine checkout:

```bash
git submodule update --init third_party/tento
uv venv --python /usr/bin/python3 .venv-semantic
deploy/tento/build.sh --python "$PWD/.venv-semantic/bin/python"
uv pip install --python .venv-semantic/bin/python \
  --find-links build/tento/wheels -e 'agent[semantic]'
.venv-semantic/bin/python deploy/tento/smoke.py
```

The `semantic` extra requires `graphmine-tento==0.1.0+62e124217e2c`, supplied by
the local wheel directory. It intentionally does not depend on the public
`ladybug` package. Without the local wheel, the extra cannot resolve. A regular
`agent` installation has no Tentō dependency. Do not install both distributions
that provide `ladybug` into one environment.

`build.sh` builds the unchanged submodule's `build-pybind-subdir` target with
explicit `LBUG_SOURCE_DIR`, bypassing only its heavyweight `requirements` target.
It never calls `sync`, `bootstrap-capi`, or downloads an upstream engine binary.
Eight compiler jobs are used by default; `--jobs` adjusts this. Build tools live
in a separate virtualenv. Packaging copies the Python sources, compiled extension
and license notices into a temporary staging directory outside the submodule.
No source patch is applied.

The resulting wheel carries the commit, native SHA-256, Python ABI and platform
tag. It is a local host build, not a portable manylinux distribution; compatible
OpenSSL 3, C++ runtime and libc are still required. A different Python ABI or host
requires a new build. The engine's reported version is unreliable at this commit;
the source commit and binary hash identify it instead.

`--build-dir /scratch/tento-build` puts the build-only virtualenv, wheels, log and
`build-evidence.json` elsewhere. Native CMake artifacts stay in ignored build
directories within the submodule. `--install` additionally installs the wheel
into the specified virtualenv; the agent and its extra are still installed with
the command above. Use disposable or development environments, never a pinned
production/testing runtime. Existing GraphMine services do not need a restart.

`graphmine_agent.semantic_engine` is safe to import without Tentō. Its
`load_engine()` function loads the native extension only on demand, checks its
distribution, commit, location and hash, and raises the standard `AnalyticsError`
with HTTP 503 and an installation instruction when missing or incompatible.
Phase 2 will call it in the disposable worker. No semantic execution route or UI
is exposed in Phase 1.

## Smoke and live gate

```bash
.venv-semantic/bin/python deploy/tento/smoke.py --output /tmp/tento-mock.json
.venv-semantic/bin/python deploy/tento/smoke.py --live --output /tmp/tento-live.json
```

The default smoke imports the installed wheel, verifies all six required
functions, and runs `mock:echo` over a one-row in-memory graph query. It runs in a
child with a 45-second timeout, disables semantic planning calls, removes model
credentials and uses an unreachable loopback provider URL. No model server is
contacted.

At this pinned revision, `--live` runs the mock then exits **2 (blocked)** with
`semantic_controls_unsupported` and zero model requests. Thinking-off controls
and strict JSON without an unconstrained retry are not supported. This is a
visible failed acceptance gate, not a successful live test. An author revision
must supply that contract before the real local-Qwen invocation can be added
and verified. The shared vLLM defaults are not changed to compensate.

Exit **0** means the requested mock checks passed; **1** means a build/import/
smoke failure. A mock pass does not establish live readiness, answer persistence,
the total call budget or correct multi-label mapping. Those remain documented
author dependencies in `semantic_engine.lock.json` and `AUTHOR_REQUESTS.md`.

For an author update, review the new commit, update the submodule, lock and exact
`semantic` dependency together, rebuild, rerun Phase 0 acceptance checks, and
implement the verified live-request controls in the smoke. Merely removing the
blocker flags cannot enable live calls.

## Reproduce the Phase 0 investigation build

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
