# GraphMine

GraphMine 1.0.0 is a C++17/CUDA library interface for graph-mining implementations
that passed the project’s GPU correctness validation. It provides one canonical
graph model, typed problem APIs, runtime backend selection, and a build-once
JSON command-line runner.

- **37** complete graph-problem contracts for problem identification
- **22** problems with validated library support
- **24** runnable library operations
- **38** registered backend choices
- Canonical JSON graph input and structured JSON results

The [repaired algorithm guide](library/docs/repaired_algorithms.md) documents the nine repaired integrations, their exact profiles, installation, and agent JSON contracts.

The [2026-10-04 expansion](docs/ALGORITHM_EXPANSION.md) explains the five new
executable profiles, all 17 new problem definitions, and routing without mandatory
retraining. The original V1 release scope and scores remain in
[`docs/V1.md`](docs/V1.md).

## Repository layout

- [`library/`](library/) contains the public headers, adapters, CLI, examples,
  tests, CMake package, and install rules.
- [`problems/`](problems/) contains all 37 authoritative `problem.json` files,
  the canonical graph schema, and the pinned source files required by the
  validated adapters.
- [`graphmine_catalog.json`](graphmine_catalog.json) is the problem-first global
  context used to interpret a user request and choose a supported operation,
  backend, parameters, and optional outputs.
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

## Build once, run many queries

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

## Intelligent LAN system

The [agent service](agent/) adds a domain-first conversational layer
without moving correctness decisions into the language model. One local Qwen
instance produces schema-constrained plans and result interpretations; a
deterministic orchestrator validates every request against the problem catalog
and invokes the precompiled CLI on a separate GPU. The bundled browser UI
supports file uploads, streamed job progress, follow-up questions, and
analyst-selected interactive visualizations. Its source is
[`agent/graphmine_agent/static/`](agent/graphmine_agent/static/): `index.html`
is the entry point, with behavior in `app.js` and presentation in `styles.css`.
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
