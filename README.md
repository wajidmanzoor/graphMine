# GraphMine

GraphMine provides a standalone C++/CUDA graph library, a thin Python binding,
and an analysis workspace with Normal, Interactive and Expert modes. The native
catalog defines the algorithms, parameters, results and available backends.

- **70** formal graph-problem contracts with native CPU profiles
- **80** native operations, including seven record-query utilities
- **23** operations with evidence-admitted GPU profiles
- Canonical JSON graph input and structured JSON results

Start with the [native library guide](docs/NATIVE_CORE_MIGRATION.md),
[profile definitions](docs/NATIVE_COMPLETION_PROFILES.md), and
[analysis workspace guide](docs/ANALYTICS_WORKSPACE.md). Exact source, binary,
dependency and profile evidence controls what the application can execute.
GPU coverage applies to declared parameter profiles, not every CPU operation.
The [acceptance report](docs/NATIVE_ANALYTICS_ACCEPTANCE.md) records completed
checks, measured model accuracy and remaining limits.

The [repaired algorithm guide](library/docs/repaired_algorithms.md) documents the nine repaired integrations, their exact profiles, installation, and agent JSON contracts.

The [2026-10-04 expansion](docs/ALGORITHM_EXPANSION.md) explains the five new
executable profiles, all 17 new problem definitions, and routing without mandatory
retraining. The original V1 release scope and scores remain in
[`docs/V1.md`](docs/V1.md).

## Repository layout

- [`library/`](library/) contains the public headers, adapters, CLI, examples,
  tests, CMake package, and install rules.
- [`problems/`](problems/) contains all 70 authoritative `problem.json` files,
  the canonical graph schema, and the pinned source files required by the
  validated adapters.
- [`library/runtime/`](library/runtime/) is the shared native core;
  [`python/graphmine/`](python/graphmine/) transports its requests and results.
- [`catalog/native_runtime_coverage.json`](catalog/native_runtime_coverage.json)
  maps every formal contract to verified native profiles.
- [`graphmine_catalog.json`](graphmine_catalog.json) retains the original V1
  problem-first catalog for the legacy API.
- [`graphmine_manifest.json`](graphmine_manifest.json) is the compact runtime
  operation/CLI contract.
- [`validation/gpu_correctness/results/results.json`](validation/gpu_correctness/results/results.json)
  records the validation classifications and checks used by the catalog.
- [`validation/algorithm_repairs/`](validation/algorithm_repairs/) records
  sequential algorithm fixes, independent regression checks, and reproducible
  repair patches. All nine repaired profiles now have [library and agent integration evidence](validation/repaired_library/REPORT.md).
- [`docs/`](docs/) is the static documentation website.
- [`agent/`](agent/) contains the domain-aware planner/analyst service,
  private-LAN API, durable GPU job queue, and interactive web application.

## Build the shared native runtime

```bash
cmake -S library/runtime -B build/native-cpu -DCMAKE_BUILD_TYPE=Release
cmake --build build/native-cpu -j4
ctest --test-dir build/native-cpu --output-on-failure
build/native-cpu/graphmine-native catalog
```

The CPU build requires Boost.JSON, OpenSSL, LAPACK and ICU. It runs without
Python or CUDA. Optional native cuGraph/cuDF and research CUDA workers are
documented in the native guide. The application additionally requires matching
validation evidence; compiling a binary alone does not admit it for execution.

## Original V1 runner

```bash
python3 library/tools/prepare_repaired_workers.py --fetch --gpu 1
cmake -S library -B library/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGRAPHMINE_BUILD_CLI=ON
cmake --build library/build --parallel --target graphmine_cli

library/build/graphmine list --pretty
library/build/graphmine --version
library/build/graphmine run triangle-counting \
  --graph library/examples/data/triangle.json \
  --backend tot \
  --list-instances \
  --pretty
```

Compilation happens once. Later queries reuse the same executable and select
the operation and backend at runtime. See the [library guide](library/README.md)
for component-level C++ usage, optional dependencies, and tests.

## Original V1 LAN system

The original [agent service](agent/) adds a domain-first conversational layer
without moving correctness decisions into the language model. One local Qwen
instance produces schema-constrained plans and result interpretations; a
deterministic orchestrator validates every request against the problem catalog
and invokes the precompiled CLI on a separate GPU. The bundled browser UI
supports file uploads, streamed job progress, follow-up questions, and
analyst-selected interactive visualizations. Its source is
[`agent/graphmine_agent/static/`](agent/graphmine_agent/static/): `index.html`
is served at `/classic`, with behavior in `app.js` and presentation in `styles.css`.
The new default workspace is `analytics.html`, documented in the workspace guide above.
The [system architecture page](docs/system/) documents the full two-machine
flow, GPU isolation, planner/analyst boundary, and deployment sequence.

For an end-to-end local deployment on the two-GPU server:

```bash
deploy/validate-v1.sh
deploy/configure-v1.sh --origin http://GPU_SERVER_LAN_IP:8000
deploy/start-vllm.sh   # terminal 1
deploy/start-agent.sh  # terminal 2
deploy/smoke-v1.sh     # terminal 3, after Qwen is ready
```

Then open `http://GPU_SERVER_LAN_IP:8000` from the research computer and enter
the generated token through the UI settings button. Deployment scripts are
available in [`deploy/`](deploy/).

## Problem-first catalog

The global catalog embeds every local `problems/*/problem.json` object exactly,
including its problem statement, graph requirements, inputs and defaults,
required and optional outputs, solution semantics, validation rules, edge
cases, and evaluation metrics. Each problem record then states whether a
validated GraphMine operation exists.

For supported problems, the catalog connects that formal contract to:

- one or more runnable operations;
- typed C++ headers, option types, classes, and CMake components;
- exact CLI commands and optional-output flags;
- selectable backend capabilities and source provenance;
- the passing validation workload, checks, and notes.

For the other 15 problem definitions, the catalog explicitly returns
`no_validated_backend`; a query planner must not substitute a nearby problem.
Regenerate the catalog after changing a problem or library contract with:

```bash
node tools/build_catalog.mjs
```

## Documentation

The static documentation site lives in [`docs/`](docs/) and is ready to publish
with GitHub Pages from the `main` branch’s `/docs` directory:

<https://wajidmanzoor.github.io/graphMine/>

The site has no framework or build dependency. It reads the global problem
catalog at runtime to render the searchable validated-operation documentation.
It also includes a [low-level code reference](docs/reference/) for GraphMine's
public C++ API and adapters plus isolated function-by-function C/C++/CUDA
references for vendored research sources and provenance/build pages for the
seven externally prepared repair workers. Regenerate those
committed pages with `node tools/build_code_docs.mjs` when code changes.

## Research artifacts

GraphMine preserves the validated paths of third-party research artifacts.
Their original copyrights and license terms remain in force; see
[`THIRD_PARTY.md`](THIRD_PARTY.md) and the license files retained beside the
vendored sources.
