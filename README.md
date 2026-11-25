# GraphMine

GraphMine provides a standalone C++/CUDA graph library, a thin Python binding,
and an analysis workspace with Normal and Expert modes. The native
catalog defines the algorithms, parameters, results and available backends.

- **70** formal graph-topic contracts with native CPU profiles
- **80** native problems, including seven record-query utilities
- **23** problems with evidence-admitted GPU profiles
- Canonical JSON graph input and structured JSON results

## Live app and demo

- **Use GraphMine:** [graphmine.autographmine.com](https://graphmine.autographmine.com/#)
- **Watch the demo:** [GraphMine walkthrough on YouTube](https://youtu.be/F5bJvpa3gdQ)
- **Request an account:** email [wajidm36@rowan.edu](mailto:wajidm36@rowan.edu).

Accounts are created by the administrator; there is no public signup form.
Once you receive your credentials, open the live app and sign in. You do not
need to install anything to use the hosted system.

## How to use GraphMine

1. **Start a conversation.** Choose a domain that matches your data, or use the
   general domain. The domain helps GraphMine understand the terminology in
   your questions.
2. **Add your data.** Open **Data** or the **+** button in the composer. Upload a
   graph, use sample data, or select a configured database connection. Review
   the preview and choose the input you want to analyze. For database work,
   see the [database and Cypher guide](docs/DATABASE_CYPHER_WORKSPACE.md).
3. **Choose a mode.** In **Normal**, ask a question, answer any clarification,
   and select a proposed calculation. In **Expert**, inspect or edit the
   workflow and its parameters, then explicitly approve it before execution.
   Expensive calculations can also require confirmation in Normal mode.
4. **Ask a concrete question.** For example: “How many triangles are in this
   graph?”, “Find the largest clique and list its members”, or “Which vertices
   have the most connections?” Supply any requested vertices, weights or
   other parameters. Calculations depend on the selected graph and its
   available attributes.
5. **Inspect the results.** Read the answer in chat, then open **Results** or
   **View results & visualizations** to explore the graph, inspect tables and
   download the full result. Check the reported method, solution quality and
   completeness when interpreting an answer.
6. **Continue your analysis.** Ask a follow-up question or reopen the
   conversation from the sidebar. Conversations retain their uploaded inputs
   and saved analyses under your account.

The [workspace guide](docs/ANALYTICS_WORKSPACE.md) covers data preparation,
workflows, visualization, exports and account limits in more detail.

## Install and run locally

The following setup uses Linux and Bash. It builds the CPU runtime and starts
the web workspace with local accounts. You can build workflows in Expert mode
without a language model; natural-language planning requires the optional
model-server setup below. CUDA is optional for CPU calculations.

### 1. Install dependencies and clone `main`

You need Python 3.11 or newer, a C++17 compiler, CMake 3.24 or newer,
Boost.JSON, OpenSSL, LAPACK and ICU. For example, on Ubuntu 24.04:

```bash
sudo apt update
sudo apt install -y git build-essential cmake python3-dev python3-venv \
  libboost-json-dev libssl-dev liblapack-dev libicu-dev

git clone --branch main https://github.com/wajidmanzoor/graphMine.git
cd graphMine
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e 'python/graphmine[reference,test]' -e 'agent[databases]'
```

The `reference` and `test` extras supply the independent validation tools used
below; calculations themselves run in the native library. The `databases`
extra installs the Neo4j and PostgreSQL clients, not database servers. Run all
remaining commands from the repository root with `.venv` activated.

### 2. Build and check the native runtime

```bash
cmake -S library/runtime -B build/native-cpu -DCMAKE_BUILD_TYPE=Release
cmake --build build/native-cpu -j4
ctest --test-dir build/native-cpu --output-on-failure
build/native-cpu/graphmine-native catalog
build/native-cpu/graphmine-native run triangle-counting \
  library/examples/data/triangle.json --device cpu
```

The example graph contains one triangle. Reduce `-j4` if compilation uses too
much memory. The standalone runtime can also be used directly from C, C++ or
Python; see the [native library guide](docs/NATIVE_CORE_MIGRATION.md).

### 3. Generate validation evidence for your build

The web application admits calculations only when validation evidence matches
the local binary, sources and linked dependencies. Reports committed from
another machine do not replace validation of your own build. Run the CPU
oracle suites and completion tests, then generate the local evidence record:

```bash
mkdir -p validation/local-cpu
python - <<'PY'
from pathlib import Path
from tools.validate_native_runtime import validate

validate(
    Path("build/native-cpu").resolve(),
    "cpu",
    0,
    Path("validation/local-cpu").resolve(),
)
PY

CUDA_VISIBLE_DEVICES="" GRAPHMINE_EVIDENCE_DEVICE=cpu \
  GRAPHMINE_NATIVE_CPU_BUILD="$PWD/build/native-cpu" \
  python -m pytest -q \
  library/tests/test_native_extended.py \
  library/tests/test_native_learning.py \
  library/tests/test_native_record_queries.py \
  library/tests/test_native_application_contracts.py \
  library/tests/test_native_table_projection.py \
  --junitxml=validation/local-cpu/completion.xml

python tools/build_native_execution_evidence.py \
  --build build/native-cpu \
  --reports validation/local-cpu \
  --junit validation/local-cpu/completion.xml
```

Continue only after validation passes. Keep `validation/local-cpu` and the
updated `catalog/native_execution_evidence.json` with this checkout. Regenerate
the evidence after changing native sources, rebuilding the runtime or changing
its linked dependencies. The Python snippet selects only the CPU part of the
validation harness; its full command-line entry point also expects two GPUs.

### 4. Configure the local workspace

For a fresh clone, create `agent/.env` with the following settings. If you
already have that file, merge these settings into it instead of replacing it.
Run this block from the repository root so the paths resolve to your checkout:

```bash
cat > agent/.env <<EOF
GRAPHMINE_API_HOST=127.0.0.1
GRAPHMINE_API_PORT=8000
GRAPHMINE_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
GRAPHMINE_ACCOUNTS_ENABLED=true
GRAPHMINE_ACCOUNT_COOKIE_SECURE=false
GRAPHMINE_AGENT_DATA_ROOT="$PWD/.graphmine-agent"
GRAPHMINE_NATIVE_LIBRARY="$PWD/build/native-cpu/libgraphmine_runtime.so"
GRAPHMINE_NATIVE_BINARY="$PWD/build/native-cpu/graphmine-native"
GRAPHMINE_ANALYTICS_PYTHON="$PWD/.venv/bin/python"
GRAPHMINE_BACKEND_DATA_DIR="$PWD/../graphmine-local-data/backend-data"
GRAPHMINE_BACKEND_MODEL_DIR="$PWD/../graphmine-local-data/backend-models"
GRAPHMINE_GRAPH_GPU_UUID=
GRAPHMINE_LLM_GPU_UUID=
GRAPHMINE_ANALYTICS_GPU_UUIDS=
GRAPHMINE_LLM_ENABLED=false
GRAPHMINE_GOOGLE_SEARCH_ENABLED=false
EOF
chmod 600 agent/.env
```

Backend telemetry and model files use the sibling `graphmine-local-data`
directory. These two paths must be writable and outside any Git repository
and `/tmp`; the application creates them at startup.

The cookie setting above is for local HTTP. Use
`GRAPHMINE_ACCOUNT_COOKIE_SECURE=true` when serving through HTTPS. Additional
settings are documented in [`agent/.env.example`](agent/.env.example).

### 5. Create an account and start the app

```bash
deploy/manage-accounts.sh create admin --admin
deploy/start-agent.sh
```

The account command prompts for a password of 12–128 characters. Open
[http://127.0.0.1:8000](http://127.0.0.1:8000) and sign in with the account you
created. Your local accounts are separate from accounts on the hosted site.
Use **Expert** to build a workflow, or use the calculation picker in the
composer. Start with [`triangle.json`](library/examples/data/triangle.json)
as a small canonical JSON upload and choose **CPU only** in calculation
settings. The default workspace does not require the legacy V1 CLI build.

Stop the server with Ctrl+C. On later runs, use `deploy/start-agent.sh` from
the same checkout; keep `.graphmine-agent` to retain accounts and saved work.
See [accounts and daily limits](docs-internal/ACCOUNTS_AND_QUOTAS.md) for user
management, quotas and backups.

### 6. Optional: enable chat planning and GPU execution

For natural-language questions, run a compatible chat-completions model server
with structured JSON output support. Edit `agent/.env` to enable it and supply
the URL, served model name and API key for your server:

```dotenv
GRAPHMINE_LLM_ENABLED=true
GRAPHMINE_LLM_BASE_URL=http://127.0.0.1:8001/v1
GRAPHMINE_LLM_MODEL=your-served-model-name
GRAPHMINE_LLM_API_KEY=your-model-server-key
GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET=
GRAPHMINE_ANALYTICS_ROUTE_THINKING_TOKEN_BUDGET=
```

Restart the app after editing the configuration. Leave the thinking-budget
extensions blank for servers that do not support them. GraphMine includes
[`deploy/setup-vllm.sh`](deploy/setup-vllm.sh) and
[`deploy/start-vllm.sh`](deploy/start-vllm.sh) for its local Qwen deployment;
that option needs an NVIDIA GPU with enough memory for the selected model.
Set `GRAPHMINE_LLM_GPU_UUID` to your device's UUID from `nvidia-smi -L`, and
configure the model before running those scripts.

GPU graph calculations require a CUDA-enabled native build and validation
evidence for the GPU and supported problem profiles. Follow the
[native build guide](docs/NATIVE_CORE_MIGRATION.md) before changing
`GRAPHMINE_NATIVE_LIBRARY`, `GRAPHMINE_NATIVE_BINARY` and
`GRAPHMINE_GRAPH_GPU_UUID`. The [deployment guide](docs-internal/ENVIRONMENTS.md)
covers managed testing and production installations.

## Further guides

Start with the [native library guide](docs/NATIVE_CORE_MIGRATION.md),
[profile definitions](docs/NATIVE_COMPLETION_PROFILES.md), and
[analysis workspace guide](docs/ANALYTICS_WORKSPACE.md). Exact source, binary,
dependency and profile evidence controls what the application can execute.
GPU coverage applies to declared parameter profiles, not every CPU problem.
The [acceptance report](docs-internal/NATIVE_ANALYTICS_ACCEPTANCE.md) records completed
checks, measured model accuracy and remaining limits.

For a shared server, see [accounts and daily limits](docs-internal/ACCOUNTS_AND_QUOTAS.md).
Login is enabled by default; the server operator creates accounts. Both web
workspaces enforce private user data, persistent 24-hour AI token budgets and
shared calculation limits.

[Dataset Studio](dataset-studio/README.md) is included in this repository.
See the [development, testing, and production workflow](docs-internal/ENVIRONMENTS.md)
for the shared branches, isolated app environments, and deployment commands.

The [repaired algorithm guide](library/docs/repaired_algorithms.md) documents the nine repaired integrations, their exact profiles, installation, and agent JSON contracts.

The [2026-10-04 expansion](docs-internal/ALGORITHM_EXPANSION.md) explains the five new
executable profiles, all 17 new topic definitions, and routing without mandatory
retraining. The original V1 release scope and scores remain in
[`docs-internal/V1.md`](docs-internal/V1.md).

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
  topic-first catalog for the legacy API.
- [`graphmine_manifest.json`](graphmine_manifest.json) is the compact runtime
  problem/CLI contract.
- [`validation/gpu_correctness/results/results.json`](validation/gpu_correctness/results/results.json)
  records the validation classifications and checks used by the catalog.
- [`validation/algorithm_repairs/`](validation/algorithm_repairs/) records
  sequential algorithm fixes, independent regression checks, and reproducible
  repair patches. All nine repaired profiles now have [library and agent integration evidence](validation/repaired_library/REPORT.md).
- [`docs/`](docs/) is the static documentation website.
- [`agent/`](agent/) contains the domain-aware planner/analyst service,
  private-LAN API, durable GPU job queue, and interactive web application.

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
the problem and backend at runtime. See the [library guide](library/README.md)
for component-level C++ usage, optional dependencies, and tests.

## Original V1 LAN system

The original [agent service](agent/) adds a domain-first conversational layer
without moving correctness decisions into the language model. One local Qwen
instance produces schema-constrained plans and result interpretations; a
deterministic orchestrator validates every request against the topic catalog
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
deploy/manage-accounts.sh create alice
# For this local HTTP preview only, set GRAPHMINE_ACCOUNT_COOKIE_SECURE=false
# in agent/.env. Keep it true when using an HTTPS domain/tunnel.
deploy/start-vllm.sh   # terminal 1
deploy/start-agent.sh  # terminal 2
```

Then open `http://GPU_SERVER_LAN_IP:8000` from the research computer and sign in
with the account you created. See the account guide for migration of existing
conversations and API/smoke-test credentials. Deployment scripts are available
in [`deploy/`](deploy/).

## Topic-first catalog

The global catalog embeds every local `problems/*/problem.json` object exactly,
including its topic statement, graph requirements, inputs and defaults,
required and optional outputs, solution semantics, validation rules, edge
cases, and evaluation metrics. Each topic record then states whether a
validated GraphMine problem exists.

For supported topics, the catalog connects that formal contract to:

- one or more runnable problems;
- typed C++ headers, option types, classes, and CMake components;
- exact CLI commands and optional-output flags;
- selectable backend capabilities and source provenance;
- the passing validation workload, checks, and notes.

For the other 15 topic definitions, the catalog explicitly returns
`no_validated_backend`; a query planner must not substitute a nearby topic.
Regenerate the catalog after changing a topic or library contract with:

```bash
node tools/build_catalog.mjs
```

## Documentation

Read the [public documentation](https://wajidmanzoor.github.io/graphMine/) for the app guide, formal topic families, runnable problems, research references, and native library APIs. The site retains the original GraphMine design.

Reader-facing source lives in [`docs-src/`](docs-src/), with the homepage and shared original-design templates in [`overrides/`](overrides/). MkDocs builds the site through GitHub Actions. Internal working records are kept separately in [`docs-internal/`](docs-internal/).

The family pages and backend table are generated from the catalog and a source-bound native snapshot. The [code reference](https://wajidmanzoor.github.io/graphMine/library/code-reference/) combines declarations extracted from current C++/CUDA sources with reviewed descriptions of every function, its parameters, return values, and ownership. It uses the same site layout, with searchable functions and expandable implementation excerpts. See [documentation build instructions](docs-internal/PUBLIC_DOCS_BUILD.md) for checks and regeneration.

## Research artifacts

GraphMine preserves the validated paths of third-party research artifacts.
Their original copyrights and license terms remain in force; see
[`THIRD_PARTY.md`](THIRD_PARTY.md) and the license files retained beside the
vendored sources.
