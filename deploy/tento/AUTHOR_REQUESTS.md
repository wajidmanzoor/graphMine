# Tentō integration requests — draft for review

Prepared 2026-11-27 against `zacharyzhijun/francis` commit
`62e124217e2c0f82e327136b5888263e95671fae`. This is a local draft, not a message
sent to the author. [Report and measurements](../../agent/evaluation/reports/tento_phase0_20261127.md)
and [reproduction instructions](README.md) accompany every request.

GraphMine needs transient in-memory graphs, one query per disposable worker,
retained answers, a total query-call limit, thinking off and enforced structured
output. No source modifications or proxy workarounds have been made.

## Required for the supplied integration contract

### 1. An answer store independent of graph persistence

`Database::getLlmAnswerStore()` gives an in-memory database an empty answer-store
path. A fresh process repeats the model call; only another connection to the
same live database reuses its answer. Killing the worker loses that store.

Please expose a configurable answer-store location or persistence interface for
an in-memory graph, without requiring a persistent Ladybug database. Confirm
durability of completed answers on cancellation/call-limit failure and behavior
when workers share an answer store. GraphMine will supply an account-scoped
location and restrictive filesystem permissions.

Acceptance: query a memory database, terminate its worker, create another memory
database over the same snapshot and reuse the committed answer without another
provider call. Changed input/model/prompt must miss the cache; age, clear and
reuse-disabled behavior must remain explicit. Reproduce today with `--case cache`.

### 2. One query budget covering all outbound requests

`llm_max_calls=1` allows two distinct expressions to make two requests. One
expression can also make two HTTP requests when a schema is rejected or a
transient error is retried, despite that limit being one.

Please expose an atomic query-wide budget checked before **every** HTTP attempt,
including planning/selectivity calls, schema negotiation, content retries and
transport retries. The final usage should distinguish attempted requests,
completed answers and inputs selected for evaluation. Existing per-expression
limits can remain separately available.

Acceptance: with a budget of one, the fixture receives at most one request
across two expressions, a 400 schema response or a 503 response. The query must
return an identifiable budget error before a second request is sent. Reproduce
today with `--case limits`; planning calls are shown by `--case explain`.

### 3. Explicit provider controls for thinking and structured output

Model aliases reject `reasoning_effort`, `enable_thinking` and
`chat_template_kwargs`. The request body carries none of these controls.
`response_format: json_schema` is sent initially, but any HTTP 400 causes a retry
without it.

Please support approved provider-specific non-thinking settings and a strict
structured-output mode that fails instead of removing the schema. Record the
effective controls in the model configuration and relevant cache identity.
GraphMine must not change the shared vLLM server's global thinking defaults to
compensate for one feature.

Acceptance: the captured local-vLLM request contains its verified thinking-off
control and a JSON schema; rejection of the required schema surfaces a structured
error with no unconstrained retry. Reproduce today with `--case providers` and
`--case limits`. Live Qwen verification follows once this contract is supported.

### 4. Clarify or support lossless label and relationship identity mapping

Creating a node with two independent labels is rejected. `MATCH
(n:Person:Review)` returns nodes from either table. A relationship `PRIMARY KEY`
declaration is rejected, although an ordinary `gm_id` property is retained.

Please confirm the intended representation for Neo4j vertices with several
labels and stable external relationship IDs. The integration brief currently
says one table per label with vertex/edge IDs as primary keys. Duplicating one
vertex across tables changes topology, and silently selecting one label loses
query semantics. An explicit approved mapping or engine support is needed.

Acceptance: a multiply labeled source vertex remains one vertex; both label
selections and traversals resolve to that same identity; parallel edges retain
distinct external IDs. Document how edge-ID uniqueness is enforced. Reproduce
today with `--case values`.

## Optional UI support and clarifications

- **Judgment inspection:** `llm_answers()` returns summaries per question, not
  individual answers with their inputs. A per-input/answer export or event API
  is needed for a faithful judgments table, including excluded rows. It should
  identify the step/question and input without exposing credentials.
- **Estimation:** default `EXPLAIN` can ask the model. An explicit no-model-call
  explain mode with documented estimated input cardinalities would support an
  honest estimate action. Exact future request counts need not be promised.
- **Progress:** a second connection can read process-wide usage during a blocked
  call, but reads reset counters and `llm_rows` can count inputs whose request
  was never sent after budget failure. Non-destructive counters or completed-row
  events would support precise UI labels. Current consumers must accumulate
  reads and avoid calling this count completed judgments.
- **Local authentication:** non-mock binding requires an environment key even
  for loopback. GraphMine's launcher already configures local authentication;
  the integration can inherit that server secret without a new browser key
  field. Please document support for genuinely unauthenticated local providers
  if that is intended.
- **Version metadata:** the standalone source pybind build reports engine
  version `2.13.1`, matching `CMAKE_PROJECT_VERSION` from pybind11, while
  `ladybug/CMakeLists.txt` declares `0.21.0`. Use the engine's own project version
  for `LBUG_CMAKE_VERSION`. Until corrected, GraphMine should identify the engine
  by commit and artifact hash, not this reported version alone.
