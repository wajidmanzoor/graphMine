# Tentō remaining fixes — supervised live verification

Date: 2026-11-27. Branch: `devlopment`. Base commit: `adcf0f5f`.
Implementation through `95aabcfb5487716d48019fda3f6ae5b64020df45`.

The remaining local engine/integration fixes are implemented and verified. Live
Qwen refinement, independent answer retention, shared admission, browser controls,
and real Neo4j → save/chat → CPU-solver execution pass. **Full W1–W24 paper
reproduction remains incomplete**: nine workloads lack inputs and seven reached
the 300-second observation deadline. The [machine-readable evidence](tento_fixes_20261127.json)
records every workload and its actual status, metrics, usage and duration.

The user's “fix the rest of the things whatever is needed” authorized local fixes
after the author-only deferral. The submodule remains unchanged at
`62e124217e2c0f82e327136b5888263e95671fae`. The locked patch is applied to an isolated exported source
tree, packaged as `graphmine-tento==0.1.0+62e124217e2c.gm1`, and verified before
native import. No service deployment, push, author message or shared vLLM
configuration change was performed.

## Implemented behavior

- Every live native HTTP attempt requires thinking off, temperature zero,
  strict JSON schema and a 4,096-token output ceiling. Schema rejection cannot
  trigger an unconstrained retry. Invalid final answers fail without publication.
- An atomic process-wide HTTP budget spans expressions, planning and retries.
  Reading usage cannot reset it. The application runs one job per disposable
  process and records actual attempts separately from completed evaluations.
- A private Unix socket admits each native request through existing planner/account
  token reservations and power leases. The engine sends HTTP directly. Tests
  verify real account charging and rejection before inference when quota is short.
- Account-private answer files are independent of graph persistence. Completed
  batches are fsynced before subsequent requests, survive hard process termination
  and budget failure, and can be reused by fresh workers. Changed inputs/prompts,
  expired entries and reuse-disabled requests miss the cache. Provider/model,
  revision and credential identity also participate in the key namespace.
- Live/cache admin controls, alias selection, answer reuse and clear are enabled
  for the verified installation. Defaults remain mocks, cache off and administrator
  access. All model steps use the selected configured alias. Provider keys stay out
  of API responses and provenance. Empty local-model credentials now follow the
  launcher's existing default consistently.

The cache's maximum age controls reuse eligibility; retained bytes remain until
cleared. Estimates and a per-input judgments table still need additional engine
APIs. These capabilities are explicitly unavailable in the UI.

## Artifact identity

| Artifact | SHA-256 / identity |
| --- | --- |
| Native patch | `c711e4c782ae05bb0e7218689027bf989a901f6853970c4bb5425550728388fe` |
| Native extension | `eaf1a5a0dccc3dc7cca09b16a4f055679fb34c7bbd1005f5a6f233c87d495bb0` |
| Wheel | `4d774169d2be9a7322b6de12fb572ab50eb230797b042f24f90ca1c942935f90` |

[Build and reproduction instructions](../../../deploy/tento/README.md) explain
how to reproduce the patched wheel without editing the submodule. The original
Phase 0 diagnostics remain evidence for the unpatched pin; their assertions are
not substituted for the new positive acceptance checks.

## Real Neo4j, Qwen and CPU-solver flow

An isolated authenticated Neo4j 5.26.32 instance was seeded with two movies and
six real reviews from the supplied movie CSVs. Sentiment ground truth was kept
outside the graph and never sent to the model. The normal database query API
created an eight-vertex, six-edge immutable snapshot. A live native semantic
filter on review text selected five reviews, creating a seven-vertex, five-edge
snapshot. Classification matched **5/6 labels (83.3%)**; this tiny integration
sample is not a general model-quality estimate.

The run used `Qwen/Qwen3.8-27B-FP8` at the local server and made one native HTTP
request (408 prompt tokens,
53 completion tokens). The served ID was
verified by successful inference; the server does not expose a weight revision.
A fresh worker reused all six answers, made zero HTTP requests, and reproduced
the same graph hash. Retention and reuse are measured, not inferred from a saved
graph. The original snapshot remained byte-for-byte unchanged.

The derived snapshot was saved and attached to chat through the normal APIs.
The native CPU densest-subgraph solver selected a four-vertex, three-edge set
with density **0.75** and reported **exact** quality. Independent enumeration of
all 127 nonempty subsets of the derived graph confirmed that optimum. Model input
provenance remains separate from the solver's quality guarantee.

| Disposable artifact | Identifier / SHA-256 |
| --- | --- |
| Original version | `dataset_version_a02dab8c24b74732a311ba7ab84211de` |
| Original hash | `36fd0469ec46a2e8d81eff67861509ace08bc59801cfd0e54f058c1def5a808b` |
| Refined version | `dataset_version_5b67316b81c44806b4d672a31e206dca` |
| Refined hash | `f6827046c59153597efec03aa72e40b3cd863647ed3268394a1fad5e88b5a376` |
| Solver workflow | `eaf6d27b-3240-4fd8-8a02-a8078abb2412` |

The evidence directory contains `validate_live_flow.py`, its logs and
`live-flow/report.json`. The disposable Neo4j process was stopped after the run.
These identifiers are test artifacts, not deployed application links.

## Verification

| Check | Result |
| --- | --- |
| Full `agent/tests deploy/tests -n 4 --dist=loadfile` | **2,245 passed**, 53 skipped, no failures/errors; 436.20s |
| Final native/live controls and workload preflight | **17 passed** |
| Live/cache admin browser controls | **2 passed** |
| Refinement, result-context and roundtrip browser group | **47 passed**, 4 prerequisites skipped |
| Live-provider browser flow plus native tests | **26 passed** |
| Final isolated live browser and shared native fixtures | **1 browser / 14 native passed** |
| Corrected workload preparation and original scorer compatibility | **4 passed** |
| Frontend | Types, **35 tests**, and contracts for **181 API paths** pass |
| Final local-Qwen smoke | Passed; one constrained HTTP request |

Native tests cover schema rejection, retry/multiple-expression budgets, usage
reset resistance, independent reuse, changed inputs/prompts, expiry, cancellation,
quota admission, account isolation, clear exclusion and parent settlement failure.
Browser tests use controlled loopback providers and actual native workers; the
separate live flow and smoke use the real local Qwen server. An isolated browser import collision was repaired by moving the shared HTTP
fixture into its own module; native tests and the isolated live browser test
were rerun successfully afterward. The live reuse screenshot was inspected. These test groups overlap and should not be summed.

The first full run exposed one obsolete blocked-engine expectation and detected
source edits during verification. The expectation was updated and the final full
run used stable application sources. Existing GPU/external-service skips remain
explicit. Browser roundtrip demo skips are supplemented by the separate real
Neo4j/Qwen/save/chat/CPU run, which covers the semantic acceptance flow.
The subsequent preparation fixes were checked with their focused deployment
suite, the unchanged original route scorer, and a real W19 rerun.

## Paper workloads

The author movie loader produced 4,999 movies, 178,472 people, 279,903 worked-on
edges and 91,258 reviews. OpenFlights inputs came from exact commit
`a438edcb869bd882506add5abdb9ff1f4aae1ae7` under ODbL, producing 6,072 airports and
37,041 routes. Preparation records hashes for all input/export/database files.
The five prepared databases are `semantic_movies`, `kg`, `flights`,
`flights_country` and `flights_code`.

The local adapter invokes the author's runner with its original queries,
default setup, fresh-copy/cache policies and quality functions. It supplies an
explicit local model configuration and the supervised native controls. Each
workload has one measured attempt, a **300-second** timeout and **200-request**
budget; W19 also has a retained failed attempt before its preparation fix.
The author runner defaults to a 120-minute limit per run. These shorter
measurements exercise integration and report bounded failures; they are not the
paper's repeated-run comparative experiment. Token counts for a timed-out run include only provider
responses received before termination.

**8 completed; 7 failed or timed out;
9 blocked by missing inputs.** A dash is unmeasured or
not scored by the original systems table, never a fabricated zero.

| Workload | Execution | Seconds | HTTP attempts | Original metric | Score |
| --- | --- | ---: | ---: | --- | ---: |
| W1 | completed | 291.04 | 38 | Review sentiment accuracy | 0.9157 |
| W2 | timeout | 300.01 | 31 | Genre accuracy | — |
| W3 | timeout | 300.00 | 42 | One minus relative error of negative-review counts | — |
| W4 | blocked | — | 0 | Precision against reference-model athlete judgments | — |
| W5 | timeout | 300.00 | 19 | Mean genre and reference-year accuracy | — |
| W6 | completed | 18.29 | 1 | — | — |
| W7 | completed | 282.34 | 39 | Negative-review precision at five | 1.0000 |
| W8 | timeout | 300.01 | 37 | Pairwise movie-ranking accuracy | — |
| W9 | completed | 3.82 | 1 | MPAA rating-set F1 | 1.0000 |
| W10 | timeout | 300.01 | 14 | Airport-country pair F1 | — |
| W11 | completed | 221.45 | 28 | Negative-review ID F1 | 0.9628 |
| W12 | timeout | 300.00 | 61 | End-airport F1 against reference model | — |
| W13 | timeout | 300.00 | 39 | Reachable-airport F1 | — |
| W14 | completed | 287.20 | 57 | Route F1 | 0.8810 |
| W15 | blocked | — | 0 | Reply-path state F1 | — |
| W16 | blocked | — | 0 | Friendship-structure predicate accuracy | — |
| W17 | blocked | — | 0 | — | — |
| W18 | completed | 97.75 | 19 | Airport-country accuracy | 0.2973 |
| W19 | completed | 24.41 | 4 | — | — |
| W20 | blocked | — | 0 | — | — |
| W21 | blocked | — | 0 | Company country and central-member accuracy | — |
| W22 | blocked | — | 0 | Description-image pair F1 | — |
| W23 | blocked | — | 0 | Image-pair F1 | — |
| W24 | blocked | — | 0 | — | — |

The selected results total **430 native HTTP attempts**;
including the preserved first W19 attempt gives
**433 measurement attempts**.
Four additional diagnostic attempts are recorded separately. Timed-out workers
have no final effective-settings record; completed worker records agree on the
strict, thinking-off controls shown in the JSON.

Two preparation defects were corrected without changing the original queries
or scorers. W14's route export now uses the scorer's expected `src,dst` headers;
rescoring the unchanged result gives **0.8810 F1**. W19 originally collided with
an obsolete quickstart schema. Starting its schema-generation task from an empty
database completed in **24.41 seconds and four requests**. Its first failure and
both database hashes remain in the evidence. W19 has no original quality metric;
it returned three universities and four professors, so execution completion is
not a claim that the prompt's requested six professors were correctly supplied.

W18's **29.7% airport-country accuracy** is retained. A bounded diagnostic captured
Qwen returning `United States` for all 16 airport codes in a batch, matching the
native stored values. No prompt tuning or truth substitution was used to improve
the reported score. Seven workloads reached the 300-second observation deadline;
their quality remains unmeasured.

Original metric names, missing reference paths, failure codes, and complete usage
are in the JSON report. Missing author LDBC samples/reference judgments and
SemBench/Visual Genome image assets remain external prerequisites. W22 additionally
requires its original embedding vectors and vector extension. No synthetic truth,
replacement embedding model or alternate benchmark is used to fill these gaps.

Raw logs, XML, source/hash metadata and measurements are under
`/home/wajid/projects/graphDatabaseAgent/validation/tento-fixes-20261127` beside the checkout. Earlier phase reports remain historical checkpoints.
