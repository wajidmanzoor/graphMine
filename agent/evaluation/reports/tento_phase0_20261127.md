# Tentō Phase 0 investigation

Date: 2026-11-27. Investigation completed; **the feasibility gate has not passed**.
The unmodified engine builds and executes semantic queries, but several fixed
integration requirements are unsupported by its current interfaces. Phase 1 and
product implementation have not started.

Sources and evidence:

- Tentō: `zacharyzhijun/francis`, commit
  `62e124217e2c0f82e327136b5888263e95671fae`; its working tree stayed unchanged.
- GraphMine baseline: `ce580ebc1363339cb96a4b5507b4786ab972d375`, `devlopment`.
- [Runnable probes](../../../deploy/tento/probe_phase0.py),
  [build/run instructions](../../../deploy/tento/README.md), and
  [recorded output](tento_phase0_20261127.json).
- [Draft author requests](../../../deploy/tento/AUTHOR_REQUESTS.md). Nothing has
  been sent externally and no Tentō patch has been applied.

All eight probe groups completed successfully as diagnostics. That includes
successful reproduction of unsupported behavior; it is not a passing product
acceptance result. Only synthetic data, mock models and loopback HTTP fixtures
were used. No live vLLM request, deployment or existing database change occurred.

## 1. Source build and function availability

**Verified.** Built Tentō's source with its own `build-pybind-subdir` target,
explicit `LBUG_SOURCE_DIR`, isolated Python 3.12.3 environment, NumPy 2.5.5 and
eight Ninja build workers. The full development-dependency target was skipped
with `-o requirements`; compilation was not skipped. The default C-API download
targets were not used.

Relevant source:
[Makefile, line 28](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/Makefile#L28)
and [pybind build target, line 55](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/Makefile#L55);
[build script](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/scripts/build_pybind_from_subdir.sh#L16).

Probe: `--case functions`. `CALL show_functions()` includes `LLM`, `LLM_SCORE`,
`LLM_AGG`, `LLM_PATH_AGG`, `LLM_SG_AGG` and `SUBGRAPH`. `mock:echo` returns
`["alpha"]` as the serialized input for the synthetic scalar query. The Python
package and native module were loaded from the requested Tentō source build;
their paths and the native SHA-256 are in the JSON evidence.

Build log on this workspace:
`/home/wajid/projects/graphDatabaseAgent/validation/tento-phase0-20261127/build.log`.

The built engine reports version `2.13.1`, while the source declares `0.21.0`.
The standalone build's CMake cache has `CMAKE_PROJECT_VERSION=2.13.1`, and
[the engine embeds that variable](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/CMakeLists.txt#L548).
Pin the commit and artifact hash; the reported version alone is misleading.

## 2. Python value shapes and graph mapping

**Verified.** Probe: `--case values`. Source:
[Python conversion, line 267 onward](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/src_cpp/py_query_result.cpp#L267).

| Returned value | Python shape and driver logical type |
| --- | --- |
| Node | `dict` with `_ID: {offset, table}`, `_LABEL`, then properties; logical type `NODE` |
| Relationship | `dict` with `_SRC`, `_DST`, `_LABEL`, `_ID`, then properties; logical type `REL` |
| Named path | `dict` with `_NODES` and `_RELS`; logical type `RECURSIVE_REL` |
| Recursive relationship variable | Also `RECURSIVE_REL`, but `_NODES` can be empty even when `_RELS` contains edges |
| Scalar row | Python `list` of values; integers, floats, bools, `None`, lists and property dictionaries retain their types |

For example, a returned node is:

```json
{"_ID":{"offset":0,"table":1},"_LABEL":"Person","gm_id":"p:1","name":"Ada","tags":["reader","critic"]}
```

Internal `{table, offset}` IDs are engine identities, not original GraphMine IDs.
Keep the source ID separately and preserve a loaded identity map to resolve
relationship endpoints. Parallel relationships preserved distinct `gm_id`
properties. CSV `COPY` loaded the synthetic graph data correctly, including
quoted commas. The integer `9007199254740993` survived exactly as a Python int.

Use `get_column_data_types()` when collecting values: graph values and scalar
STRUCTs are both Python dictionaries. A scalar STRUCT can contain `_ID` and
`_LABEL` without being a node. Named paths can pad properties from other node
tables with nulls; do not overwrite the original snapshot's attributes blindly.

**Mapping constraints:** creating a node with both independent labels fails,
while `MATCH (p:Person:Review)` returned all three Review nodes and the Person
node, rather than an intersection. Source:
[multiple-label create check](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/binder/bind/bind_updating_clause.cpp#L215).
A relationship `PRIMARY KEY(gm_id)` declaration fails parsing. Node primary keys
are supported ([DDL transformation](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/parser/transform/transform_ddl.cpp#L42)).
The brief's one-table-per-label and edge-primary-key wording therefore needs a
verified representation or author support before a lossless loader is promised.

## 3. Aliases, providers and keys

**Verified, with a configuration clarification.** Probe: `--case providers`.
`CREATE MACRO qwen() AS {model: 'phase0/qwen', temperature: 0, base_url: ...}`
routes to the alias endpoint and sends the configured model ID. A model string
without an alias uses the connection's `llm_base_url`. The HTTP path is
`/v1/chat/completions` when the base URL ends in `/v1`.

Sources:
[alias fields](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_functions.cpp#L61),
[configuration resolution](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_functions.cpp#L836),
[key loading](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/prompt_template.cpp#L416).

No key causes a bind-time failure even for the loopback fixture; no request is
sent. `OPENROUTER_API_KEY` takes precedence over `LLM_API_KEY`. Keys are
process-environment scoped rather than fields of an alias. A worker must clear
unrelated provider-key variables before setting its own credential.

GraphMine's [launcher](../../../deploy/start-vllm.sh) already passes `--api-key`,
and [configuration](../../../agent/graphmine_agent/config.py) provides
`GRAPHMINE_LLM_API_KEY`. Thus “no key” for the default provider should be clarified
as “no additional user-entered key”: reuse the configured local server secret
privately. The investigation did not read or log its actual value. The fixture
only used invented test values and recorded their selection as booleans.

## 4. Thinking and structured output

**The required controls are not supported as specified.** Probe:
`--case providers`, plus the `schema_fallback` observation in `--case limits`.

The engine rejects alias fields `reasoning_effort`, `enable_thinking` and
`chat_template_kwargs`. Captured requests contain only `model`, `temperature`,
`messages` and `response_format`; the engine does not transmit a thinking-off
control. Sources: the alias-field allowlist above and
[request construction](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_runtime.cpp#L1344).

Structured output initially uses `response_format.type=json_schema`, with
`json_schema.strict=true` and the generated schema. That is the mechanism the
existing GraphMine client also uses to request constrained JSON. However, the
fixture's HTTP 400 causes a second request with no `response_format`.
[The fallback is unconditional for 400 with a schema](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_runtime.cpp#L1367).

This does not satisfy enforced JSON output or thinking off for semantic calls.
Do not change the shared server's global behavior to compensate. Add explicit
provider controls and a strict schema policy in an approved engine revision,
then verify them against the real local vLLM. Live vLLM guided decoding was not
claimed or tested by the loopback fixture.

## 5. Interruption and live counters

**Python interruption exists; hard process cancellation remains necessary.**
Probe: `--case interrupt`. Sources:
[Python interrupt method](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/src_py/connection.py#L1040)
and [native binding](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/tools/python_api/src_cpp/py_connection.cpp#L175).

Against a provider deliberately withholding its response:

- `conn.interrupt()` left the query running for the next 400 ms. Once the
  fixture released its response, the query returned `Interrupted.`.
- A 100 ms query timeout likewise did not end the blocked HTTP operation within
  400 ms. It returned `Interrupted.` after the provider was released.
- Killing the separate worker returned signal exit `-9` and reaped it within
  milliseconds. The fake provider was still processing until separately released.
  Killing a client therefore does not establish cancellation of server-side GPU work.

A second connection to the same memory database successfully read usage while
the first connection was blocked. Aggregate progress collection is possible in
this arrangement. **Usage reads reset process-wide counters**, as shown by a
second immediate read of zeros and
[the implementation](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_table_functions.cpp#L113).
A worker must have one counter consumer and sum successive readings; it must
not subtract a previous reading as though these were cumulative counters.

Do not label `llm_rows` as completed judgments. It is incremented for uncached
inputs before reserving calls. The limit-error probe reported `llm_rows=2` with
`calls=0`. Source:
[input accounting and reservation](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_runtime.cpp#L594).
Exact completed-row progress needs additional evidence/events. Four distinct
engine phase notifications were not established by these counters.

## 6. Dry run and estimation

**EXPLAIN is available; a free exact call estimate is not established.** Probe:
`--case explain`. A two-predicate query over three synthetic rows made two
provider requests and evaluated six inputs during default `EXPLAIN` alone.
Sources:
[planning calls](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/docs/llm_semantic_operators.md#L979)
and [selectivity sampling](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/docs/llm_semantic_operators.md#L999).

With `semantic_selectivity_samples=0`, `semantic_path_decomposition=false` and
`semantic_join_decomposition=false`, the same EXPLAIN produced a plan with zero
requests. That is evidence for this query/configuration, not an exact forecast
for every semantic path, join, aggregate or cache state. `PROFILE` provides
operator metrics after executing a query. Do not expose default EXPLAIN as an
action that promises no model calls. Estimate calls remains a conditional feature.

## 7. Answer persistence and judgment inspection

**The required retention across disposable memory workers is unsupported.**
Probe: `--case cache`. The same query produced these results:

| Execution | Calls | Stored hits |
| --- | ---: | ---: |
| First connection to a memory database | 1 | 0 |
| New connection to the same live memory database | 0 | 1 |
| Fresh worker with a new memory database, first run | 1 | 0 |
| Another fresh worker, same input and prompt | 1 | 0 |
| Reopened temporary file database, positive control | 0 | 1 |

The memory database gets an empty answer-store path in
[Database::getLlmAnswerStore](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/main/database.cpp#L188).
[The store](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_answer_store.cpp#L160)
keeps such answers in memory. File databases use a `.llm_answers` sidecar. No
public setting for an independent answer-store path was found in the inspected
configuration/API. Using a permanent graph database would violate the brief;
that workaround has not been implemented.

`CALL llm_answers()` returns `question`, `model`, `instruction`, `answers`
(a count), `oldest`, `newest` and `path`. It does **not** return one row per
judgment or the original entity/input for each answer. Source:
[answer summary binding](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_table_functions.cpp#L209).
See the judgments therefore remains unsupported through this public API.
Re-executing a modified query is not proof of the original run's judgments.

## 8. License

**Engine license verified.** Probe: `--case license`.
[ladybug/LICENSE](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/LICENSE#L1)
is MIT, with Kùzu and Ladybug copyright notices. The Python package also declares
MIT. The complete license and SHA-256 are preserved in the evidence. This check
identifies the engine's license; it is not a distribution-wide third-party
notice audit. Preserve the applicable notices during later packaging.

## Additional required correction: a query-wide call budget

Probe: `--case limits`. `llm_max_calls=1` produced two calls when a query had two
different model expressions. A single expression also made two HTTP attempts
after a schema rejection, and two after a simulated HTTP 503.

[reserveCalls](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_runtime.cpp#L467)
uses a runtime-local counter. The
[HTTP retry loop](https://github.com/zacharyzhijun/francis/blob/62e124217e2c0f82e327136b5888263e95671fae/ladybug/src/function/llm/llm_runtime.cpp#L1339)
counts actual attempts in usage but does not re-reserve that budget for each
attempt. Polling usage and killing after an overrun cannot enforce an exact
before-request cap. The user-facing total call limit requires an approved
query-wide enforcement mechanism.

## Phase gate and next action

Keep the source build and probes as the baseline. The next step is to resolve
the [author requests](../../../deploy/tento/AUTHOR_REQUESTS.md): independent
answer persistence, query-wide request accounting, non-thinking/strict-JSON
provider controls, and a verified identity/label mapping. Estimation and per-row
judgment UI can remain conditional as the original brief allows.

The supplied brief says, “If a decision above turns out impossible, stop and
explain why with evidence; don't work around it.” It also requires approval
between phases. This report is that review point: the full integration goal
remains unfinished, and no Phase 1 submodule or product backend/UI has been added.

User decision after review, 2026-11-27: **keep the plan and use fixes from Tentō's
author**. The remote `main` head was rechecked and remains
`62e124217e2c0f82e327136b5888263e95671fae`; no newer candidate was available there.
The author-request draft has not been sent. The next dependency is an
author-provided revision addressing the required contracts, followed by a fresh
source review, build and verification of those fixes. No engine patches or
integration workarounds are authorized by this decision.
