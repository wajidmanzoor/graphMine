# Tentō source build and verification

GraphMine refines an owned database snapshot in a disposable in-memory Tentō
worker, publishes a separate immutable graph/table version, and retains its
parent hash, model settings and usage. Plain reads, explicit mocks and live
models are supported. Live mode and answer retention must be enabled by an
administrator; defaults remain explicit mocks and administrator-only access.

The user authorized the remaining fixes on 2026-11-27. The pinned submodule stays
at `62e124217e2c0f82e327136b5888263e95671fae`; a reviewed
[native patch](patches/0001-supervised-live-contracts.patch) is applied to an
isolated source export. Its SHA-256 is locked alongside the wheel version.
The [live verification report](../../agent/evaluation/reports/tento_fixes_20261127.md)
records the local-Qwen smoke, native control tests, real Neo4j/save/chat/CPU-solver
flow, and available paper workloads. Missing author datasets/reference judgments
remain visible. This is not a completed reproduction of all 24 paper workloads.

The [backend guide](../../docs/SEMANTIC_SNAPSHOT_BACKEND.md) documents the API,
query syntax and administration. Earlier reports preserve the phase checkpoints:
[0](../../agent/evaluation/reports/tento_phase0_20261127.md),
[1](../../agent/evaluation/reports/tento_phase1_20261127.md),
[2](../../agent/evaluation/reports/tento_phase2_20261127.md),
[3](../../agent/evaluation/reports/tento_phase3_20261127.md),
[4](../../agent/evaluation/reports/tento_phase4_20261127.md), and
[5](../../agent/evaluation/reports/tento_phase5_20261127.md).
[Upstream requests](AUTHOR_REQUESTS.md) are an unsent local draft.

## Build and install

Use Linux, CPython 3.12 with development headers, a C++20 compiler, OpenSSL 3
headers/libraries, CMake, Ninja, make and uv. Python 3.12 is the tested ABI;
3.13–3.14 are accepted by the builder but unverified. The private submodule uses
SSH. From the checkout, build into a new directory when changing patches:

```bash
git submodule update --init third_party/tento
uv venv --python /usr/bin/python3 .venv-semantic
deploy/tento/build.sh --python "$PWD/.venv-semantic/bin/python" \
  --build-dir "$PWD/build/tento-gm1" --install
uv pip install --python .venv-semantic/bin/python \
  --find-links build/tento-gm1/wheels -e 'agent[semantic]'
.venv-semantic/bin/python deploy/tento/smoke.py
```

The extra requires `graphmine-tento==0.1.0+62e124217e2c.gm1` from the local wheel
directory. It does not depend on the public `ladybug` distribution. Do not install
both into one environment. Ordinary application startup needs no native import.

The builder verifies the unchanged pin and patch hashes, exports the tracked
source into `<build-dir>/source`, applies the patches, and builds its
`build-pybind-subdir` target. Native artifacts, build-only dependencies, logs,
source identity, wheel and build evidence all stay outside the submodule. It
never calls `sync` or `bootstrap-capi` or downloads an upstream engine binary.
The default is eight compiler jobs; use `--jobs` to adjust it. A changed pin or
patch set requires a fresh build directory.

The wheel includes the commit, patch hashes, native SHA-256, license notices,
Python ABI and platform tag. The loader checks them before importing native code.
It is a local host build, not a portable manylinux wheel; compatible OpenSSL,
C++ runtime and libc are required. Rebuild for another ABI or host. The upstream
engine version string is unreliable at this pin, so use the recorded identities.

## Live controls and smoke

Each live HTTP attempt carries thinking off, temperature zero, a strict JSON
schema, and a 4,096-token output ceiling. A schema rejection fails the job; no
unconstrained retry follows. One atomic process budget covers every attempt,
including retries, planning and multiple expressions. Usage reads cannot reset
that budget. GraphMine runs exactly one job per disposable process.

The native engine makes its own HTTP requests. A private Unix socket lets the
supervisor reserve the existing shared planner/account quota and power leases
before every attempt, then settle provider usage. No model proxy or shared
vLLM-default changes are involved. The worker receives only its selected
provider's key. Every query step must use the selected configured alias.

With retention enabled, completed validated batches are written and fsynced to
an account-private answer file independent of graph storage. Fresh workers can
reuse answers after cancellation or a later request-limit failure. Cache identity
covers the snapshot, prompt/input/types, model/provider, relevant revisions,
credential rotation and strict/thinking contract. Turning reuse off bypasses
reads while retaining completed answers. Admin clear waits for active workers.

```bash
.venv-semantic/bin/python deploy/tento/smoke.py --live \
  --base-url http://127.0.0.1:8001/v1 --model Qwen/Qwen3.8-27B-FP8 \
  --output /tmp/tento-live.json
```

Use the actual served ID and endpoint. `GRAPHMINE_LLM_API_KEY` follows the local
launcher configuration, including its default for an empty value. The default
smoke sends no HTTP traffic. `--live` requires an explicit endpoint/model and
runs one supervised completion after the native mock. Exit 0 means the requested
checks passed, 1 means failure, and 2 means missing prerequisites. A successful
smoke does not measure paper-workload quality.

## Paper workload measurements

Preparation uses the author's loaders and supplied movie CSVs. Optional
OpenFlights downloads record an exact repository commit, input hashes and
license. Route exports retain the original values under the scorer's `src,dst`
column names. W19 starts with an empty database so its graph-building operation
can design the schema. Existing databases are never overwritten.

```bash
.venv/bin/python deploy/tento/prepare_data.py \
  --data-root /tmp/tento-paper-data --download-openflights
.venv/bin/python deploy/tento/acceptance.py \
  --model-id Qwen/Qwen3.8-27B-FP8 --data-root /tmp/tento-paper-data \
  --output /tmp/tento-prerequisites.json
.venv/bin/python deploy/tento/run_local.py \
  --data-root /tmp/tento-paper-data --output /tmp/tento-measurements \
  --base-url http://127.0.0.1:8001/v1 --model Qwen/Qwen3.8-27B-FP8 \
  --timeout 300 --call-limit 200
```

The inventory is read-only and never claims execution or validates database
contents. It exits 2. The local runner adds a runtime model configuration to the
author's runner without editing it. Queries, default setup, fresh-copy/cache
policies and original quality functions are retained. Every W1–W24 workload gets
a record, including missing inputs, missing quality references, timeouts and
failures. The timeout/request budget applies separately to each workload. Use
`--queries W9` for a bounded targeted run; unselected workloads stay explicit.
A partial report exits 2 and never promotes an absent score to success.

The author's LDBC SF0.1 sample, reference judgments, SemBench sf500 image assets
and vectors, and Visual Genome vg100 sample are not supplied here. W22 also
requires its vector extension. Image capability must be verified separately.
Several workloads have no quality score in the original systems table; those
are distinguished from unavailable references. Shared server weight revisions
are recorded only if exposed; a served model ID alone does not establish them.

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
