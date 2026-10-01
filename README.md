# GraphMine

GraphMine is a C++17/CUDA library interface for graph-mining implementations
that passed the project’s GPU correctness validation. It provides one canonical
graph model, typed problem APIs, runtime backend selection, and a build-once
JSON command-line runner.

- **20** complete graph-problem contracts for problem identification
- **12** problems with validated library support
- **13** runnable library operations
- **26** selectable validated backends
- Canonical JSON graph input and structured JSON results

## Repository layout

- [`library/`](library/) contains the public headers, adapters, CLI, examples,
  tests, CMake package, and install rules.
- [`problems/`](problems/) contains all 20 authoritative `problem.json` files,
  the canonical graph schema, and the pinned source files required by the
  validated adapters.
- [`graphmine_catalog.json`](graphmine_catalog.json) is the problem-first global
  context used to interpret a user request and choose a supported operation,
  backend, parameters, and optional outputs.
- [`graphmine_manifest.json`](graphmine_manifest.json) is the compact runtime
  operation/CLI contract.
- [`validation/gpu_correctness/results/results.json`](validation/gpu_correctness/results/results.json)
  records the validation classifications and checks used by the catalog.
- [`docs/`](docs/) is the static documentation website.

## Build once, run many queries

```bash
cmake -S library -B library/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGRAPHMINE_BUILD_CLI=ON
cmake --build library/build --parallel --target graphmine_cli

library/build/graphmine list --pretty
library/build/graphmine run triangle-counting \
  --graph library/examples/data/triangle.json \
  --backend tot \
  --list-instances \
  --pretty
```

Compilation happens once. Later queries reuse the same executable and select
the operation and backend at runtime. See the [library guide](library/README.md)
for component-level C++ usage, optional dependencies, and tests.

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

For the other eight problem definitions, the catalog explicitly returns
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
references for all 24 validated research source artifacts. Regenerate those
committed pages with `node tools/build_code_docs.mjs` when code changes.

## Research artifacts

GraphMine preserves the validated paths of third-party research artifacts.
Their original copyrights and license terms remain in force; see
[`THIRD_PARTY.md`](THIRD_PARTY.md) and the license files retained beside the
vendored sources.
