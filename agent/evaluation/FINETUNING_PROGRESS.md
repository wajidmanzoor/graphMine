# Fine-tuning progress

User objective: continue fine-tuning and document what was completed and what
remains after every major task. This log distinguishes actual model improvements
from infrastructure, application fixes, and training-loss measurements.

Current status, 2026-10-04 UTC: fine-tuning remains paused at the user's request.
Both adapter training runs are complete; the remaining evaluation queue was
stopped on October 3 at 23:41:16 UTC. Weights, completed results, partial calls
and logs are preserved. The user subsequently authorized deployment and UI/data
collection work. That separate phase is now complete: `business-v1-pilot.1` is
connected to the real app, with the original data preserved. No training or
unfinished evaluation queue was resumed. See the deployment milestone below and
the [deployment report](reports/pilot-deployment-2026-10-04.json).
The [stop/handoff report](reports/finetuning-user-stop-2026-10-03.json) records
the exact stopping point and rechecked artifact hashes.

The first adapter's original development comparisons are complete. The user
clarified that fine-tuning questions must
describe practical application and business needs in user language, without
spelling out the underlying GPU programs. The next candidate therefore uses a
separate business-question curriculum; the original artifacts remain preserved.

The revised curriculum contains 180 training, 68 validation and 124 evaluation
cards. They cover staffing, payment review, service planning, retail campaigns,
incident review and laboratory follow-ups. Broad goals train useful domain
clarifications. Split-specific wording has no exact question overlap; graph
families remain separated. These are authored synthetic questions, not collected
customer requests or independently reviewed teacher outputs. Source computation
contracts and saved native outputs were rechecked; 17 focused tests passed.
The 180/68/124 cards contain 61/59/61 distinct question strings respectively;
wording repeats across graphs within each split. Counts are task cards, not
independent customer questions.
The new export is `.graphmine-learning/business-routing-data-v1`. The separate
run `.graphmine-learning/finetune-qwen27b-business-v1` completed all 45 optimizer
steps at 22:17:55 UTC. Its 992 saved tensors are finite, and all 496 LoRA-B tensors
are nonzero and differ from the first candidate. Validation token loss is
0.01499837; this is not task accuracy. The serving reference passed 115/124
practical routing cases under the existing application-aware review and all
21 turns / nine practical application conversations. The matched NF4 comparison
completed all 248 calls at 23:26 UTC. Under the established application-aware
routing review, the business adapter passed 118/124 and the base 113/124, with
six improvements and one regression. Five improvements clean up clarification
metadata; one corrects an unnecessary clarification. The regression chooses
full account circles instead of every three-account set. This is routing
evidence, not a demonstrated complete-application gain. A saved-route application
replay completed at 23:40:22 UTC: the base produced all five requested account
triplets, while the business adapter's route led to a false unsupported response
and no computation. The planner prevented the wrong computation but did not
recover the routing mistake. This was a diagnostic, not fresh routing predictions.
The original-adapter business comparison stopped with 46/124 saved calls; its
child PID 75373 and queue MainPID 68553 were confirmed stopped. Both statuses now
say `stopped_by_user`, with prior status snapshots retained. Practical local
conversations and the revised adapter's retention/real-data checks never started.

The previous candidate's full application comparison passed 20/21 synthetic
turns for both local arms. Its real-data comparison finished with raw grades
22/22 for the base and 20/22 for the adapter. Both adapter failures solely compare
numeric `0.0` against `0` on otherwise identical filters; a separate audit records
the equivalent numeric meaning and preserves the original scores. No end-to-end
quality gain or production readiness is established. Earlier routing gains and
their wording/label limitations are documented below.

The user-testing app is deployed and ready for the requested manual trials.
The unfinished comparisons remain recorded as incomplete and will not resume
automatically. The final reserved source remains unused. Historical "Remaining"
sections below describe the plan at each milestone; later milestones supersede
them. Pilot deployment is not a claim that the unfinished quality gates passed.

## 2026-10-04 — User-testing deployment and feedback workflow completed

Completed under the user's explicit deployment/UI request:

- Connected the saved business adapter to the real app for `RouteDecision` only,
  using the same pinned base, NF4 decoding runtime, prompt and schema as its
  comparison. Startup and responses verify the adapter fingerprint. Planning,
  turn classification and answers retain the existing FP8 model. The original
  evaluation queue remains stopped and the final reserved source remains unused.
- Installed supervised user services for the API and loopback routing endpoint.
  Preserved the `.graphmine-v1` store, original sessions, files, jobs and results;
  saved an online database backup and the previous private configuration.
- Added separate Chat and Results pages, stable saved-result URLs, session
  restoration, a clearer responsive layout, sample team data and report downloads.
- Added observable stage summaries and an expandable display of reasoning
  actually returned by the local Qwen server. Verified the displayed planning text
  matches the saved 2,282-character response exactly. No reasoning is invented
  for the trained routing stage, which retains thinking-disabled decoding.
- Added browser feedback forms and `/feedback`, `/correct`, `/rate`, `/note`,
  `/help`, `/status`, `/export`, also accepting backslash prefixes. Commands never
  enter model prompts. Annotations retain target links, tester alias, deployment
  identity and the full conversation snapshot, including older pre-history chats.
  JSONL exports mark annotations unreviewed; session archives retain full evidence.
- Passed 295 Python tests, two browser acceptance scenarios, lint and JavaScript
  syntax checks. Browser checks cover separate result navigation, feedback,
  session reload/isolation, responsive layout and offline reports.
- Completed a live browser/native acceptance on authored sample data. The actual
  model stages were `graphmine-business-v1` for routing and the existing FP8 model
  for planning and narrative. The native computation returned both expected named
  collaboration groups. Local commands and saved feedback added no model calls.
  This acceptance is explicitly marked as assistant evaluation, not real-user data.

Evidence: [deployment report](reports/pilot-deployment-2026-10-04.json),
`.graphmine-learning/pilot-deployment-v1/live-acceptance.json`,
`reasoning-ui-acceptance.json`, `before.json`, `cutover.json`, and saved screenshots.
Exact feature instructions and collection guidance are in the
[user guide](../README.md#user-testing-pilot-business-v1-pilot1); service operations
and rollback are in the [deployment guide](../../deploy/README.md#business-adapter-user-testing-pilot).

Remaining limitations: the known exact-size grouping false refusal, unfinished
candidate comparisons, large-graph/concurrent-load validation and actual user
trials. The existing shared-token pilot has no per-user session isolation. User
annotations need human review before training. A successful deployment acceptance
does not establish a general end-to-end fine-tuning gain.

## 2026-10-03 — Completed pilot verified

Completed:

- Re-read the authoritative run configuration, status, metrics, training export,
  and saved adapter for `.graphmine-learning/finetune-qwen27b-v3`.
- Confirmed 48/48 optimizer steps and one epoch on 192 training examples, with
  72 validation examples. Completion was 08:53:06 UTC. Mean training loss was
  0.1254744; validation token loss was 0.000753677. These are not task accuracy.
- Verified the final adapter contains 992 finite tensors and all 496 LoRA-B
  tensors are nonzero. Recorded its SHA-256 and size (467,047,680 bytes).
- Revalidated training export provenance and confirmed the routing prompt still
  matches training. The adapter trains routing only; the application continues
  to serve the original FP8 model.
- Confirmed the second RTX 6000 Ada GPU is free. Added pinned XGrammar 0.2.8 and
  apache-tvm-ffi 0.1.14.post1 to the isolated training environment; all existing
  pinned training packages were retained.

Evidence: [completion verification](reports/finetune-completion-2026-10-03.json),
the run's `status.json`, `metrics.jsonl`, and final `adapter/` directory.

Remaining, in order:

1. Build and test a reproducible generation-based comparison. Both local arms
   must share the exact base weights, NF4 quantization, prompt, JSON schema,
   tokenizer, and decoding settings; only adapter activation differs.
2. Validate the harness on development cases, then evaluate all 132 reserved
   synthetic test cases. Their graph families are held out, but their wording
   templates are shared with training; report that limitation explicitly.
3. Compare separately with the serving FP8 model, and evaluate new wording,
   changed attributes/thresholds, clarification, unsupported requests, and
   multi-turn scope changes. Preserve an untouched final holdout when using
   evaluation findings to improve training.
4. Address demonstrated weaknesses with reviewed additional training examples
   and retraining where warranted. Re-run the relevant comparisons.
5. Validate the chosen adapter in the complete application for computed results,
   explanations, presentation, and latency before any production promotion.

Reference methods: [PEFT adapter disabling](https://huggingface.co/docs/peft/package_reference/peft_model#peft.PeftModel.disable_adapter)
and [XGrammar Transformers integration](https://xgrammar.mlc.ai/docs/latest/start/quick_start.html).

## 2026-10-03 — Comparison harness and development smoke test completed

Completed:

- Added the `graphmine_agent.learning.adapter_eval` prepare/compare commands,
  documented in [CLI.md](../CLI.md#compare-a-completed-routing-adapter).
- Both local arms load the same verified base checkpoint, use the same NF4/BF16
  configuration and required-field JSON grammar, and alternate adapter activation.
  Each generation starts a fresh cache. The serving FP8 reference is separate.
- Preserved immutable suite inputs, hashes, raw case outputs, semantic failures,
  process progress, and paired comparisons. Added locking and explicit resume.
- All 14 evaluator/training tests passed. They exercise wrong attributes, false
  empty-result refusals, lost weight requirements, filter inheritance/clearing,
  equivalent temporal units, invalid JSON and incomplete comparison detection.
- Completed all 12 calls for four validation cases across three arms. The adapter
  passed 4/4; the matched NF4 base and serving FP8 reference each passed 3/4.
  Every arm returned valid JSON without truncation. This is a harness smoke test,
  not an accuracy estimate: all four question strings also occur in training.
- Inspected the single difference: all models correctly refused unsupported
  cost-weighted routing, but the adapter also preserved the requested formal
  problem ID. There is no evidence here of a newly fixed unsafe execution.

Evidence: [smoke report](reports/adapter-validation-smoke-2026-10-03.json),
`.graphmine-learning/adapter-validation-smoke-v1/evaluator.py`, and the raw calls
under `.graphmine-learning/adapter-validation-comparison-v1/`.

Remaining: run the complete 132-case synthetic test split, separate behavior
correctness from exact identity/requirement preservation in the aggregate report,
and test language/contextual regressions beyond shared templates. Complete
application validation and any needed retraining remain pending. No adapter has
been deployed.

## 2026-10-03 — Full comparison and broader development challenges prepared

Completed:

- Froze `.graphmine-learning/adapter-test-suite-v2`: all 132 reserved test cases,
  with evaluator source, dependency hashes, unchanged adapter hash and saved
  prompts/schema. 130/132 question strings also occur in training, despite the
  graph-family separation. This measures template transfer to other graphs.
- Added separate behavior, semantic-requirement, and unsafe-execution counts;
  fixed resume scoring so a truncated response cannot become a pass. The 16
  tests for this version passed; evidence is `adapter-eval-tests-v2.xml`.
- Started supervised jobs `graphmine-adapter-test-v2.service` (same-precision
  base/adapter) and `graphmine-adapter-reference-v2.service` (serving FP8 reference).
  Both were confirmed live by systemd MainPID/ActiveState while outputs advanced.
  Results are in `.graphmine-learning/adapter-test-nf4-v2/` and
  `.graphmine-learning/adapter-test-fp8-v2/`; neither job changes deployment.
- Froze `.graphmine-learning/adapter-challenge-suite-v1`: 53 cases with zero
  exact question overlap with training. These cover eight new operation wordings,
  four changed-filter cases, empty selections, filtering versus weighting,
  weighted refusals, changed time units, unsupported patterns, six contextual
  scope changes, multiple analyses, ambiguity, all 13 operations, and 12 existing
  safety regressions. The builder is `evaluation/build_adapter_challenges.py`.
- Challenge labels were specified before inference and checked for internal
  consistency. They use validation graphs and manual semantic contracts, not
  blinded human/teacher review. Existing safety wording is adapted to the actual
  fixture vocabulary where necessary; source hashes and adaptations are saved.

Remaining: finish the active comparisons; evaluate the frozen challenge suite;
review failures and decide what additional training is needed. Then validate the
candidate in complete application workflows and preserve a new final holdout.
The OpenFlights source holdout has not been called by these evaluations.

## 2026-10-03 — Grading review implemented; original results preserved

Early outputs showed two overly strict checks: a static clique answer can
legitimately populate optional pattern fields, and the production prompt permits
bounded read-only inspections. The application only consumes temporal pattern
and time-window fields for temporal mining. Counting these differences as wrong
computations would overstate the adapter's improvement.

Completed:

- Added `graphmine_agent.learning.adapter_review`, a separate report generator
  that reads every saved response and keeps the original strict scores beside
  a score that ignores these irrelevant fields and records inspections separately.
- Preserved model, decoding settings, case set, and all running evaluation code.
  No examples are deleted, and no generation is repeated to select a better answer.
- The review explicitly states that these grading corrections followed inspection
  of early outputs. It verifies input/case hashes and requires complete result
  sets, so partial progress cannot be presented as a finished benchmark.
- All 18 evaluation/training tests passed (`adapter-eval-tests-v3.xml`), including
  checks that a wrong selected operation and a wrong temporal pattern still fail.

Remaining: apply this review once the full outputs are complete. A requested
inspection is only recorded at routing stage; its successful resolution still
needs complete-application testing. Do not claim usability or final deployment
readiness from either routing score.

## 2026-10-03 — Complete-application evaluation path implemented

Completed:

- Added `graphmine_agent.learning.adapter_workflows`. It starts a fresh embedded
  application for each comparison arm and runs the existing conversation or
  real-data workflow evaluator with its native-result and presentation checks.
- Only `RouteDecision` is dispatched to the local NF4 base/adapter. Turn
  resolution, executable planning and answer writing retain the serving FP8
  model. Routing preserves the same last-12-message serialization as production.
- Local application routing allows a recorded 16,384-token input budget for
  conversation history (the static comparison uses 8,192). Inputs are never
  silently truncated. Generation and adapter activation are serialized.
- Added raw routing-call history, explicit stage/model provenance, separate
  per-arm stores/reports, and a summary requiring each evaluated arm to finish.
  This creates no public endpoint and does not mutate the deployed application.
- Six tests passed, including a real embedded application lifecycle with the
  existing test binary, routing-only dispatch, preserved history, explicit
  failure for truncated/invalid output, and rejection of a live-store/remote-API
  destination. Evidence: `.graphmine-learning/adapter-workflow-tests-v2.xml`.

Remaining: run GPU workflow smoke tests after the current comparisons release
the GPU, then run the full development conversation and real-data comparisons.
These six tests verify the integration code; they do not establish trained-model
workflow accuracy. The real-data evaluator retains its development-only source
selection, so the OpenFlights holdout is still reserved.

## 2026-10-03 — Full FP8 reference comparison completed

Completed:

- All 132 reference generations finished at 18:42:25 UTC with valid JSON and no
  token-budget truncation. The process exited and its transient systemd unit
  was collected; this is a terminal result, not a stale running-status file.
- Original strict score: 115/132. After the documented static-pattern correction,
  the routing/requirement score is 123/132. All 132 had the correct top-level
  execution/clarification/refusal behavior, with zero unsafe executions proposed.
- Inspected every remaining failure: eight correctly refused cost-weighted
  requests omitted the formal problem ID, and one correctly refused four-host
  chain omitted its requested pattern edges. These are preservation defects in
  refusal metadata, not evidence that the reference executed unsafe substitutes.
- Saved all raw-response hashes and both score sets in
  [the FP8 reference review](reports/adapter-test-fp8-review-2026-10-03.json).
- Started the 53-case challenge reference as
  `graphmine-adapter-challenge-reference-v1.service`, writing to
  `.graphmine-learning/adapter-challenge-fp8-v1/`. The matched NF4 base/adapter
  comparison is still running; it was not restarted.

Remaining: finish and review the matched comparison, run both NF4 arms on the
frozen challenges when their GPU is free, then perform complete-application
comparison. The FP8 result alone establishes no fine-tuning gain, since the
trained-adapter comparison and the harder development questions are pending.

## 2026-10-03 — Challenge reference completed and fixture limitations audited

Completed:

- All 53 serving-model reference generations finished at 18:54:54 UTC with valid
  JSON and no token-budget truncation. The transient systemd unit was collected;
  the matched NF4 comparison remains live and was not restarted.
- Saved the unchanged strict score (46/53), documented application review
  (49/53), all response hashes and every case score in
  [the challenge reference review](reports/adapter-challenge-fp8-review-2026-10-03.json).
- Inspected all four remaining cases. Dynamic triangle counting, graph motifs,
  and subgraph isomorphism ask about attached inputs that the routing fixtures
  do not actually supply. The model chose the correct operation and requested
  those missing inputs. These three execution-label mismatches do not establish
  a model regression; their labels need a separate, explicit fixture-aware audit.
  The motif response also asks about induced mode despite the question already
  specifying it, so the clarification wording is not entirely precise.
- The fourth case, "Find the important groups in this graph," chose community
  detection plus a supporting analysis where the development label requires
  clarification. The scorer calls this an unsafe execution proposal; it is a
  routing-only result, and no graph computation was performed by this benchmark.
- At 18:56 UTC the matched comparison had saved 164/264 calls. Both arms had
  correct top-level behavior on all 82 cases assessed per arm. Strict scores
  were 82/82 for the adapter and 67/82 for the base; those unreviewed scores must
  not be used to claim the final improvement because some strict differences
  are irrelevant static-pattern metadata.

Remaining: complete the matched comparison, evaluate the adapter on the harder
suite, audit the incomplete-fixture labels without overwriting original results,
and validate complete application workflows and the reserved final holdout.
Do not add these three execution labels to training without correcting their
missing-input context. No additional training or deployment has occurred.

## 2026-10-03 — Production behavior and missing-input label audit completed

Completed:

- Updated only the separate review module; all frozen generation code, inputs,
  model weights, and running jobs remain unchanged. The v1 review source is
  preserved as `.graphmine-learning/adapter-review-v1.py`.
- The v2 review derives behavior from the actual production `route_blocker`.
  Unsupported capabilities outrank missing inputs, and a missing operation ID
  cannot count as execution. It does not infer capabilities from the gold answer.
- Added a [three-case label audit](reports/adapter-challenge-label-audit-2026-10-03.json)
  bound to the frozen suite and case hashes. Each correction records the missing
  attachment evidence and changes only the expected behavior to clarification.
  All original cases, labels and outputs remain available; none are removed.
- Saved the [audited challenge reference](reports/adapter-challenge-fp8-audit-v2-2026-10-03.json):
  46/53 strict, 49/53 application review, and 52/53 with the separate label audit.
  The one remaining ambiguous-request case is unchanged. The report explicitly
  records that these corrections followed reference-output inspection; this is
  development evidence, not a newly untouched benchmark.
- All 26 evaluation/training tests passed, including production gate precedence,
  missing operation identity, unchanged original labels, and rejection of wrong
  suite/case hashes, duplicate corrections and unexplained changes. Ruff passed.
  Test evidence: `.graphmine-learning/adapter-eval-tests-v4.xml`.

Remaining: finish the matched 132-case comparison and then run the NF4 challenge
arms, applying this same audit to both. Resolve demonstrated model weaknesses,
complete application comparisons, and evaluate the chosen candidate on the
reserved final holdout before deciding whether it is ready for promotion.

## 2026-10-03 — Final reserved-source evaluation path prepared

Completed:

- Added `adapter_holdout` and the explicit `adapter_workflows --final-holdout`
  option. It selects every reserved case, verifies the graph/source split,
  rejects development question files or case subsets, and reuses the existing
  independent result, attribute and presentation checks in isolated app stores.
- The final report records consumption before the first attempted question.
  Failed answers remain in the report without sending oracle feedback into the
  model's conversation. The enclosing protocol binds the adapter, base suite,
  routing environment and unchanged models for other application stages.
- The original development evaluator and its source-selection rules were not
  modified. Final mode uses the original contract questions; source separation
  does not imply independently authored language or unseen task types.
- All 11 application/holdout checks passed using local test fixtures, including
  source-boundary rejection, complete case selection, consumption logging, and
  absence of oracle feedback after a failed answer. Ruff passed and the actual
  training environment successfully imported the CLI. Evidence:
  `.graphmine-learning/adapter-application-tests-v3.xml`.

Remaining: finish development comparisons and any justified retraining, freeze
the candidate, and then run this final path. No actual reserved-source model
calls have occurred. If final results inform further tuning, a new independent
holdout will be needed for an untouched evaluation of that later candidate.

## 2026-10-03 — Complete matched 132-case comparison reviewed

Completed:

- All 264 paired generations completed at 19:19:04 UTC. The original process
  exited, its transient unit was collected, and GPU inspection confirmed it
  released the second GPU before another evaluation was started.
- Saved the [complete three-arm review](reports/adapter-test-review-2026-10-03.json),
  with hashes of every raw response and a snapshot of the review source.
  Scores are:

  | Arm | Original strict | Application review | Correct top-level behavior |
  | --- | --- | --- | --- |
  | Matched NF4 base | 110/132 | 123/132 | 131/132 |
  | Same NF4 base plus trained adapter | 132/132 | 132/132 | 132/132 |
  | Serving FP8 reference | 115/132 | 123/132 | 132/132 |

- Every arm returned valid, untruncated JSON. No arm proposed executing a case
  labeled unsupported or needing clarification in this suite.
- After excluding irrelevant static-pattern descriptions and recording bounded
  inspections separately, there are nine matched improvements and no regressions.
  Eight preserve the formal centrality problem ID during an otherwise correct
  refusal of weighted computation. The ninth fixes a false k-core refusal:
  `barbell-02-q02`. The base confused `domain_relevant: false` with unavailability,
  despite the input explicitly listing a validated k-core backend. The adapter
  selected that backend correctly.
- The base requested five bounded inspections. Their successful follow-through
  is not established by this routing benchmark and still needs app evaluation.
- Started the harder frozen 53-case comparison as
  `graphmine-adapter-challenge-nf4-v1.service`, writing 106 calls to
  `.graphmine-learning/adapter-challenge-nf4-v1/`. Its process was confirmed live
  as MainPID 4144295, using only the freed second GPU.

Interpretation: the pilot improves route/identity preservation on these graph
families, but 130/132 question strings occur in training. The result supports a
limited template-transfer claim; it does not prove generalization to new wording,
complete workflow accuracy, faster responses, or deployment readiness.

Remaining: complete and review the 53-case matched challenge, run complete
synthetic and real-data development workflows, address demonstrated weaknesses,
and perform the final reserved-source evaluation for the chosen candidate.

## 2026-10-03 — Existing application-reference evidence revalidated

Completed:

- Verified `.graphmine-learning/real-world-student-v2.json` against the current
  result protocol, application replay contract, corpus, screened questions,
  complete case list, model name and recorded inference settings. Every recorded
  check matches. Its 44/44 turns across 32 workflow trials remain useful as a
  historical serving-FP8 reference.
- The older synthetic conversation reference differs in application source,
  generated workflow cases and planning settings, so it cannot replace a fresh
  synthetic reference run for this comparison.
- Saved the [reference audit](reports/adapter-application-reference-audit-2026-10-03.json)
  with all artifact/contract hashes and the limitation that the earlier real-data
  report records a model name rather than a separately verified serving-weight
  fingerprint. It is not a newly generated third comparison arm.

Remaining: run fresh matched NF4 base/adapter application workflows. Use a fresh
serving-FP8 synthetic reference, and label the earlier real-data FP8 evidence as
historical. No model calls or final-holdout consumption occurred in this audit.

## 2026-10-03 — Fresh complete-application reference started

Completed setup:

- Confirmed the six synthetic workflows contain 21 turns, with graphs of only
  8–10 vertices and 8–23 edges. GPU 0 had 7,472 MiB free while the serving model
  was idle. Its small native jobs can run there independently of the matched
  routing comparison on GPU 1.
- Added a recorded, canonical-UUID `--reference-native-gpu` option restricted to
  a separate serving-FP8 reference. Matched local arms cannot use this override.
  All 13 integration/holdout checks passed (`adapter-application-tests-v5.xml`)
  and Ruff passed.
- The first reference launch had an extra digit in its native-GPU argument. It
  was explicitly stopped and retained in `.graphmine-learning/adapter-workflow-fp8-v1/`
  with an `abort.json` explaining the configuration error and one completed turn.
  This is not model-quality evidence. The malformed-UUID preflight now prevents
  this error before any model call or evaluation output is created.
- Launched a fresh run using the exact GPU UUID read from `nvidia-smi`:
  `graphmine-adapter-workflow-reference-v2.service`, MainPID 4146826. Its outputs
  are `.graphmine-learning/adapter-workflow-fp8-v2/`, including the verified GPU
  placement in `protocol.json`. Both this service and the original challenge
  comparison were confirmed live; the challenge job was not restarted.

Remaining: inspect the 21-turn reference results and finish the 53-case matched
routing comparison. Then run the matched local models through the complete
application on the freed evaluation GPU. FP8 reference latency has a different
GPU-sharing arrangement and cannot be used as a causal fine-tuning speed result.

## 2026-10-03 — Harder routing comparison completed; stage boundary checked

Completed:

- All 106 matched challenge calls completed at 19:45:28 UTC. The supervised
  process exited and released GPU 1. Every arm produced valid, untruncated JSON.
- Saved the [complete challenge comparison](reports/adapter-challenge-review-2026-10-03.json)
  with all original scores, the documented application review, the separate
  three-case attachment audit, and a snapshot of the review code:

  | Arm | Original strict | Application review | Early-clarification label audit |
  | --- | --- | --- | --- |
  | Matched NF4 base | 43/53 | 46/53 | 49/53 |
  | Same base plus adapter | 52/53 | 52/53 | 49/53 |
  | Serving FP8 reference | 46/53 | 49/53 | 52/53 |

- Under the recorded label audit, the adapter improves three cases: retaining
  both year filtering and cost weighting, removing only the requested region
  restriction while retaining the year, and preserving the formal problem ID
  during a cost-weighted refusal. The first two are substantive requirement
  preservation improvements, not static-pattern formatting differences.
- Three regressions under that audit select the correct operation and proceed
  to planning instead of immediately asking for an absent attachment. All arms
  also choose analyses for the vague "important groups" request where the
  development label expects clarification. No unfavorable cases were removed.
- Inspected the stage contract: routing receives no available-files list;
  `_draft` receives it and the executable validator requires matching auxiliary
  inputs. A route marked supported therefore does not establish a ready plan or
  native execution. The scorer's `unsafe_execution` field is a routing proposal
  relative to its labels, not a count of jobs actually executed.
- Replayed the three saved adapter routes on their exact verified source graphs
  through fresh isolated applications with live unchanged FP8 planning. All
  three returned `needs_information` and created zero jobs. Preserved the
  [gate diagnostic](reports/adapter-auxiliary-diagnostic-2026-10-03.json), source
  script `.graphmine-learning/adapter-auxiliary-diagnostic-v1.py`, routing-output
  hashes and complete runtime histories. This is a gate check with replayed
  routes, not three fresh adapter predictions or an accuracy correction.

Remaining: keep the stage-sensitive scores visible and evaluate fresh complete
application behavior. Do not automatically turn the attachment timing differences
into training labels: attached-file availability belongs to the later context,
and positive cases with supplied files must also remain functional. The shared
vague-intent failure remains a limitation for follow-up curriculum decisions.

## 2026-10-03 — Fresh application reference complete; local comparison started

Completed:

- The FP8 reference finished all 21 turns at 19:47:11 UTC: 20/21 turns passed,
  with 5/6 complete workflows passing. Saved the
  [reference summary](reports/adapter-workflow-reference-2026-10-03.json), binding
  the full report, protocol, case hash, GPU placement and failed-turn evidence.
- Inspected the failure: after enumerating every maximal group, the user asked
  for one largest group again. The conversation decision referred to the earlier
  maximum result, but the application presented its latest maximal-groups result.
  That turn called only `TurnDecision` and `GroundedNarrative`; routing was never
  invoked. This is a conversation/result-selection limitation outside the routing
  adapter stage, rather than evidence that its fine-tuned weights failed.
- Retokenized 12 saved reference routing requests with the local tokenizer.
  The largest was 11,538 tokens, below the 16,384-token local input budget.
  Evidence: `.graphmine-learning/adapter-context-preflight-v1.json`. This is a
  partial context preflight; later/local histories can differ and still reject
  excessive length rather than silently truncate it.
- Launched `graphmine-adapter-workflows-nf4-v1.service`, MainPID 4149471, using
  the freed second GPU and isolated stores. It will cover all six workflows and
  21 turns for each matched local arm; the first workflow also exercises GPU
  integration with conversation history and native execution. Outputs are in
  `.graphmine-learning/adapter-workflows-nf4-v1/`.

Remaining: review all local application outcomes and distinguish routing changes
from unchanged planning/conversation stages. Compare the local arms on screened
real-data development questions, then evaluate the chosen frozen candidate on
the reserved source. No new training run or deployment has occurred.

## 2026-10-03 — Complete-application comparison review prepared

Completed:

- Added `adapter_workflow_review`, a read-only comparison for finished synthetic,
  screened real-data and final-source application runs. It preserves original
  grades and requires every case, repetition and turn to be present exactly once,
  with unchanged questions, matching case hashes and internally consistent totals.
- The review requires a complete matched NF4 pair and identical recorded case,
  source and inference contracts. It also checks identical native placement and
  local routing environments between the matched arms; FP8 reference placement
  remains explicitly recorded and separate.
- Paired improvements/regressions retain workflow, repetition and turn identity.
  Failed turns include hashes of the recorded stage requests. Stage participation
  is not automatically labeled as the cause of a failure. Reports also retain
  original turn durations and their interpretation limits.
- All 11 focused review tests passed, covering incomplete and altered reports,
  missing/duplicate turns, contradictory grades, changed inference contracts,
  screened question sequences and stage evidence. Ruff passed. Evidence:
  `.graphmine-learning/adapter-application-review-tests-v1.xml`.
- Confirmed that the live local run and completed fresh FP8 reference have no
  differences in the recorded case/code/inference comparison fields. At 20:06
  UTC, the local base had passed 16/17 completed turns. Its sole failure so far
  is the largest-group result-reuse case also seen in the FP8 reference. The
  original application process remains active; it has not been restarted.

Remaining: let both matched arms finish and apply this review, then run the
screened real-data comparison and final reserved-source test for the selected
candidate. The in-progress local scores are not a completed comparison.

## 2026-10-03 — Complete matched application comparison reviewed

Completed:

- Both local arms finished all 21 turns; the adapter arm completed at 20:25:12
  UTC. The original supervised process exited and released the second GPU.
- Applied the coverage/contract checks and saved the
  [three-arm application comparison](reports/adapter-workflow-comparison-2026-10-03.json),
  including unchanged grades, exact paired identities, request-stage evidence,
  source snapshots and hashes of every report/protocol.

  | Arm | Turns passed | Whole workflows passed | Median turn time |
  | --- | --- | --- | --- |
  | Matched NF4 base | 20/21 | 5/6 | 46.2 seconds |
  | Same base plus adapter | 20/21 | 5/6 | 49.4 seconds |
  | Fresh serving FP8 reference | 20/21 | 5/6 | 38.6 seconds |

- There are 20 paired passes and one paired failure, with no matched improvements
  or regressions on these complete workflows. Every arm fails the same final
  largest-group follow-up. Its trace calls `TurnDecision` and `GroundedNarrative`
  without `RouteDecision`, so the routing adapter is not called on that turn.
- The comparison demonstrates application compatibility on these workflows,
  not a measured end-to-end quality improvement. The local adapter's median was
  about 3.2 seconds longer in this one trial. FP8 has a different inference
  engine/precision, routing completion budget, and native GPU-sharing arrangement;
  its timing is a separate serving reference, not a causal adapter speed result.

Remaining: compare the local arms on screened real-data workflows and the final
reserved source. The conversation/result-selection limitation remains visible;
it must not be described as fixed by routing fine-tuning or hidden by regrading.

## 2026-10-03 — Supplied-file counterpart and stage audit completed

Completed:

- Checked the three attachment cases with the required file actually supplied.
  The same saved adapter routes produced validated ready plans that bound the
  uploaded file IDs; induced motif semantics, per-vertex participation, query
  labels and requested embeddings were preserved where applicable.
- These were plan-only replays, so no native jobs were executed. Together with
  the earlier missing-file checks, each saved route reached `needs_information`
  when its file was absent and a ready plan when the file was present.
- Preserved the [first supplied-file attempt](reports/adapter-auxiliary-positive-2026-10-03.json):
  the updates case passed, then a hand-written motif fixture failed upload schema
  validation because of an unsupported root `schema_version` field. That error
  occurred before a motif model call. Corrected and prevalidated the two graph
  fixtures in a [separate run](reports/adapter-auxiliary-positive-v2-2026-10-03.json);
  both remaining cases passed. The successful updates case was not rerun.
- Saved a [stage audit](reports/adapter-attachment-stage-audit-2026-10-03.json)
  binding all six missing/supplied outcomes to the same original route and graph
  hashes. The earlier audit's requirement for clarification during routing was
  more specific than the application's stage contract: routing has no file
  inventory, while planning checks it. The three timing mismatches must not be
  equated with unsafe jobs or automatically used as corrective training labels.
  All original benchmark scores remain unchanged; this creates no new accuracy
  score or claim of fresh adapter predictions/native algorithm verification.

Remaining: use complete-application evidence when assessing those stage timing
differences. Continue to test ambiguity and actual requirement preservation;
the shared vague "important groups" routing limitation remains unresolved.

## 2026-10-03 — Matched real-data development evaluation started

Completed setup:

- Retokenized all 44 saved historical development routing requests. The largest
  was 13,945 tokens, within the same 16,384-token budget used for both new local
  arms. No truncation or model call was used by this preflight. Evidence:
  `.graphmine-learning/adapter-real-context-preflight-v1.json`.
- Started `graphmine-adapter-realworld-nf4-v1.service`, MainPID 4158288, using
  `.graphmine-learning/real-world-corpus-v5` and the unchanged screened questions
  in `.graphmine-learning/real-world-questions-v3/questions.json`.
- The run covers every admitted development case: 16 workflows / 22 turns per
  arm, with one fresh trial per arm. Outputs are in
  `.graphmine-learning/adapter-realworld-nf4-v1/`. The historical FP8 reference
  remains separately labeled; it is not being presented as a fresh third arm.
- At 20:38 UTC the original service was live and the first five base turns had
  passed. The report records zero holdout model calls.

Remaining: finish both arms, apply the application comparison review, inspect
any new failures, and then evaluate the chosen frozen candidate on the reserved
source. The pilot has not been deployed and its original weights are unchanged.

## 2026-10-03 — First candidate's real-data comparison completed

Completed:

- Both matched arms finished all 22 turns / 16 workflows; the adapter completed
  at 21:13:28 UTC and its process released GPU 1. The
  [comparison](reports/adapter-realworld-comparison-2026-10-03.json) preserves
  raw scores: base 22/22 turns and 16/16 workflows; adapter 20/22 and 14/16.
  Median turn times were 51.45 and 60.19 seconds respectively.
- Investigated both flagged adapter turns. Workplace `contact_intervals == 0`
  and protein `score == 0` became the same field/operator with numeric `0.0`.
  The checker serializes filters before comparing, distinguishing the numeric
  representations. All other checks for those turns passed. The
  [numeric-filter audit](reports/adapter-realworld-numeric-filter-audit-2026-10-03.json)
  records this evidence without changing either original grade or producing a
  replacement aggregate score.
- The historical serving reference remains separately labeled. No new model
  calls used the reserved source, and no model was deployed.

Remaining: the user's practical-question requirement changes the next candidate's
curriculum. Keep this comparison as first-candidate evidence, and use explicit
numeric-semantic filter comparison in new application evaluations.

## 2026-10-03 — Practical business-question curriculum prepared and launched

Completed:

- Recorded the user's requirement: questions should describe application and
  business needs, without spelling out the underlying GPU programs. Technical
  operation identities remain in internal labels, not in the user questions.
- Added the [authored question bank](../graphmine_agent/learning/business_questions.py)
  and [curriculum builder/exporter](../graphmine_agent/learning/business_curriculum.py).
  Scenarios cover project staffing, investigation leads, service ownership,
  customer bundle campaigns, incident review and laboratory follow-ups.
- Added broad requests such as important teams or investigation priorities with
  domain-language clarification targets. A business goal alone does not justify
  silently selecting a particular computation. Questions with sufficient
  criteria retain their checked computation, filter and numeric requirements.
- Built `.graphmine-learning/business-curriculum-v1`: 180 train, 68 validation
  and 124 evaluation cases. The split-specific wording banks have zero exact
  question overlap and retain the source graph-family separation. Recorded 48
  excluded source tasks without a suitable authored business scenario, including
  confidence-as-distance requests. Twenty-four broad-goal cases were added.
- Revalidated all 372 unchanged computation contracts and, for executable
  cases, the saved native outputs. No redundant GPU jobs were needed. This is
  authored synthetic supervision, not independent language review or collected
  customer data; the jargon screen alone cannot establish semantic correctness.
- Exported only train/validation cases to
  `.graphmine-learning/business-routing-data-v1`. All 17 curriculum/training
  tests and focused Ruff checks passed. Evidence:
  `.graphmine-learning/business-curriculum-tests-v1.xml`.
- Prepared the fresh adapter run from the same verified base checkpoint and
  hyperparameters. Training has 180 rows / 45 planned optimizer steps;
  validation has 68 rows. Maximum tokenized length is 7,333, below 8,192, with
  assistant-only loss and no truncation. The unit above was confirmed active
  with its model loaded. The earlier adapter was not overwritten or resumed.

Remaining: verify real optimizer progress, complete this training, compare the
new candidate with the same NF4 base and previous adapter on practical questions,
and test full business conversations and clarification. Correct numeric filter
grading for new evaluations while preserving old scores. Select the candidate
before using the reserved source; no production promotion is implied.

Optimizer updates subsequently verified: the new run completed step 2 and saved
`checkpoints/checkpoint-2`, then reached step 6. The
[curriculum checkpoint](reports/business-question-curriculum-2026-10-03.json)
records representative practical questions, counts, source hashes, limitations
and that observed state. Base revision/files, hyperparameters, sequence budget,
training code, prompt and pinned package versions match the original run.

The [practical suite builder](../graphmine_agent/learning/business_eval.py) passed
seven additional tests covering full coverage, changed identities, actual
training-text overlap and premature binding to incomplete weights. It froze all
124 evaluation cards in `.graphmine-learning/adapter-business-suite-old-v1`;
case SHA-256 is `8e6d1621fa20141509d069ada3c2b2b25f8affb172cbe8682b8156a706a97c59`.
The same cards will bind to the revised weights after training completes.
`graphmine-adapter-business-reference-v1.service` was launched to collect the
serving reference in `.graphmine-learning/adapter-business-fp8-v1` while the
independent training GPU continues. These are practical development comparisons;
the final reserved source remains unused.

## 2026-10-03 — Practical conversation evaluation prepared

Completed:

- Added [business conversation evaluation](../graphmine_agent/learning/business_workflows.py)
  and froze `.graphmine-learning/business-workflow-suite-v1` before model calls:
  nine workflows / 21 turns across the six application domains. Case SHA-256:
  `b6d1b9870d7e1c690946dcd04b914bbc2030a671d844cc5f6fc51e0133f0292b`.
- Scenarios cover one versus several project teams, year corrections, an
  investigation goal followed by clarification, cost-based ranking versus an
  exact cost-tier selection, service-pool eligibility, campaign audience size,
  incident timing and unsupported relays, assay clarification/empty selections,
  and outreach groups. Questions use application language throughout.
- Kept existing independent native/requirement checks and added the existing
  presentation checks. The new grading policy treats numerically equal filter
  values such as `0` and `0.0` alike, while preserving field/operator differences,
  strings, booleans and every other failure. Original grader findings remain in
  each turn record. No old reports were regraded.
- An initial cost-threshold scenario exposed the source oracle's equality-only
  filter support before any model call. Changed that new scenario to an exact
  cost-tier review; the source oracle and frozen prior evaluators were retained.
- The new conversation loop sends no oracle feedback to the model, even after
  failures. It records complete coverage, stage histories, code/case hashes,
  actual turn durations and isolated application stores. Ten focused tests and
  Ruff passed; evidence is `.graphmine-learning/business-workflow-tests-v1.xml`.
- These are authored development conversations on validation graphs. Some first
  turns use validation-token-loss wording; they establish application behavior
  on these scenarios, not unseen-language accuracy or real-user business value.

Remaining: finish the live 45-step business-question training and 124-case
serving reference. Evaluate both adapters and the matched base on the frozen
practical questions and conversations, inspect failures, then choose the candidate
for the reserved-source evaluation. Deployment remains unchanged.

## 2026-10-03 — Practical-question serving reference completed

Completed:

- `graphmine-adapter-business-reference-v1.service` completed all 124 calls at
  21:54:46 UTC and exited. The separate business training process remains active;
  its last verified optimizer count was 31/45 at 21:55 UTC.
- Applied the existing routing review, saving the
  [practical reference report](reports/adapter-business-fp8-review-2026-10-03.json)
  and review-source snapshot. Original strict score is 102/124; the established
  application-aware review is 115/124. All 124 responses are schema-valid and
  untruncated; typed semantic requirements match in all 124. These are routing
  results, not complete application answers or executed native jobs.
- The nine application-review failures comprise four wrong operation choices
  on payment-review pool/trio questions, four broad goals where the authored
  contract expects clarification before choosing an analysis, and one
  clarification that retains a speculative formal problem ID. The broad-goal
  expectations are authored task-design judgments, not independent user ratings;
  the route scorer's execution labels do not establish unsafe executed jobs.
- No data, training labels or evaluation questions were changed in response to
  this reference. The revised run continues on its frozen 180-row export.

Remaining: finish training and verify the saved adapter, bind these identical
124 questions to it, and compare the NF4 base, revised adapter and original
adapter. Run the frozen practical conversations, then choose the candidate for
the still-unused reserved source. No quality gain from the revised weights has
yet been measured, and no adapter has been deployed.

## 2026-10-03 — Business-question training completed and verified

Completed:

- The new run finished all 45/45 optimizer steps and one epoch on 180 training
  rows, with 68 validation rows, at 22:17:55 UTC. Its transient service exited
  and released GPU 1 before the next evaluation started.
- Revalidated the training/export/source hashes, split exclusions, pinned
  packages, current routing prompt and matched base/hyperparameters. All saved
  loss and gradient measurements are finite. Mean training loss is 0.14274561;
  validation token loss is 0.01499837. Different data wording prevents treating
  a comparison with the first pilot's loss as a quality comparison.
- Read every saved adapter tensor: all 992 are finite, all 496 LoRA-B tensors
  are nonzero, and all 496 differ numerically from the first adapter. Adapter
  SHA-256: `dd7017735094300c4a89f217cb094c0d8b9981d1c7d86182596a7a6f7ef5f4d6`.
  Evidence: [completion verification](reports/business-finetune-completion-2026-10-03.json).
- Bound the same 124 frozen questions to the completed weights in
  `.graphmine-learning/adapter-business-suite-new-v1`. Its cases hash matches
  the original-adapter suite exactly. Prompt, schema, input/output budgets,
  decoding and packages match; run and adapter bindings remain distinct.
- Launched the paired comparison in `.graphmine-learning/adapter-business-nf4-v1`
  at 22:22:43 UTC. It alternates two-case batches with the adapter disabled and
  enabled on the same loaded NF4 base. The service was live at 22:34 UTC with
  44/248 calls complete. The prior pilot's weights and results are preserved.

Remaining: finish and review the paired practical routing comparison, evaluate
the original adapter on those identical cases, and compare both adapters in
the frozen practical conversations. Check the revised candidate against the
existing operation/context challenges and screened real-data workflows before
selecting a candidate for the untouched source evaluation. Those are development
regressions, not additional independent test sets. No adapter has been deployed.

## 2026-10-03 — Practical application serving reference completed

Completed:

- A fresh serving-model trial finished all nine workflows / 21 turns at
  22:16:58 UTC. All native-result, requirement and presentation checks passed;
  no numeric-filter equivalence corrections were needed. Median full-turn
  time was 41.52 seconds, maximum 63.68 seconds.
- Verified the actual request records: 21 routing, 17 planning, 17 narrative
  and nine turn-resolution calls all used `Qwen/Qwen3.8-27B-FP8`. No adapter was
  loaded. Evidence: [reference review](reports/business-workflows-fp8-review-2026-10-03.json)
  and `.graphmine-learning/business-workflows-fp8-v1/`.
- Preserved the reference's original-adapter suite binding. Because it uses no
  adapter, that binding does not turn it into an adapter trial. Native execution
  shared GPU 0 with serving; the local comparisons use GPU 1 for routing/native
  execution. Cross-precision/placement latency differences remain confounded.
- Tokenized all 21 actual routing requests without additional model calls:
  maximum input length 10,219 is below the 16,384-token application budget.
  Evidence: `.graphmine-learning/business-workflow-context-preflight-v1.json`.
  Local conversation histories can differ; overlength input still fails rather
  than being silently truncated.

Remaining: run the matched base and revised adapter, then the original adapter,
on these same practical conversations. A perfect reference score on these small,
authored validation scenarios is not evidence of fine-tuning benefit or broad
business usefulness. No oracle feedback or reserved-source model calls were used.

## 2026-10-03 — Remaining development comparisons prepared and sequenced

Completed:

- Bound the unchanged 53-case operation/context challenge to the revised adapter
  in `.graphmine-learning/adapter-business-retention-suite-v1`. Verified identical
  case bytes, prompt, decoding, base and hyperparameters, with zero exact overlap
  against the revised training questions. The existing early-clarification audit
  retains every prior correction in a separately bound file. The
  `binding-report.json` records these checks and zero new model calls.
- This retention set intentionally preserves earlier technical development
  questions. It checks whether practical-question training loses prior coverage;
  it is neither additional training data nor a claim to satisfy the user's
  business-language requirement by renaming technical questions.
- Prepared a fixed sequence: finish/review the running matched routing pair;
  evaluate the first adapter on the identical 124 business cases; run the new
  matched pair on all 21 practical conversation turns; run the first adapter on
  the same 21 turns; run the revised adapter on all 53 prior challenges and all
  22 screened real-data turns. Each result directory is new.
- Started `graphmine-business-evaluation-queue-v1.service` at 22:38:53 UTC,
  MainPID 68553. It was confirmed live and waiting for MainPID 12177 at 22:39.
  The supervisor checks terminal process state and full result coverage before
  proceeding, preserves per-job logs, stops on infrastructure/integrity failure,
  and performs no automatic retry. Its frozen plan is
  `.graphmine-learning/business-evaluation-queue-v1/plan.json`, SHA-256
  `aee41bb32c0a4327d31a2c7e1961e645c12fd40efd3f0d5c7efc5587044ab24e`.
- After each completed task, the queue records a checkpoint with its result,
  established review where applicable, and the remaining tasks under
  `.graphmine-learning/business-evaluation-queue-v1/checkpoints/`. Current state
  is in that directory's `status.json`; GPU-job progress remains in each result
  directory. The queue does not select a candidate or consume the final source.

Remaining: let the recorded development comparisons finish, inspect their
cross-candidate differences and any failures, then freeze candidate selection
before the full reserved-source comparison. Record the final bounded-pilot
outcome and remaining application limitations. Completion of the queue alone
does not complete the fine-tuning goal or authorize deployment.

## 2026-10-03 — Cross-candidate review prepared

Completed:

- Prepared `.graphmine-learning/review-business-candidates-v1.py` to join the
  completed practical routing and conversation results. It gives the original
  and business adapters distinct names while preserving their respective suite
  bindings, every original grade, and the serving-only reference's binding.
- The review requires complete identical case coverage, the same local base,
  prompt, schema, decoder and packages, matching local GPU placement, unchanged
  raw routing evidence, and consistent application contracts. It verifies actual
  model identities for every recorded application stage and reports per-case
  improvements/regressions without inferring stage causality from participation.
- Its preflight rechecked the 124 identical routing cases and all 21 completed
  reference turns, including the 64 actual stage requests. Evidence:
  [review preflight](reports/business-candidate-review-preflight-v1.json).
  No model calls or grading changes were made. Combined candidate reports cannot
  yet be produced because those evaluations are still running or queued.

Remaining: after the corresponding results finish, run the script with `routing`
and `application`, each with a new `--output` report path. Inspect all changed
cases, not just total pass counts. Prioritize complete business answers and
correct filters, supported capabilities, clarification and conversation scope;
keep formal identity differences, training loss and latency separate. Review the
unchanged operation/context and screened real-data checks before recording the
candidate choice. A tie or inconclusive result is reportable; no positive quality
gain or production recommendation is implied by completed training.

Prepared the separate diagnosis
`.graphmine-learning/audit-application-filter-representations-v1.py` for the
upcoming real-data and final-source reviews. It reuses the tested numeric-filter
rule, verifies complete saved application coverage and candidate binding, and
retains every failed turn, other issue and raw score. Its
[replay verification](reports/numeric-filter-audit-replay-v1.json) exactly
reproduced both earlier integer-zero/floating-zero findings, including the
expected and actual filters, while preserving 20/22 and making zero model calls.
It creates no replacement aggregate and changes no frozen evaluator. Apply it to
completed new results when relevant; this replay is preparation, not new evidence
of adapter improvement.

## 2026-10-03 — Matched practical routing comparison completed

Completed:

- Both local arms finished all 124 questions, 248 calls total, at 23:26:18 UTC.
  The original process exited and its unit was collected. The queue saved
  `checkpoints/01-business-new-pair.json`, applied the existing routing review,
  and started the original-adapter comparison only after that process exited.
- The [complete review](reports/adapter-business-new-review-v1.json) records
  strict scores of 99/124 for the NF4 base and 118/124 for the business adapter.
  Under the established application-aware review, scores are 113/124 and 118/124:
  112 cases pass for both, six improve, one regresses, and five fail for both.
  All 248 generations are schema-valid and untruncated. Both arms preserve all
  typed semantic requirements under that review.
- Inspected every changed case. The
  [case audit](reports/business-routing-change-audit-v1.json) distinguishes five
  metadata gains in routes that already ask for clarification from the one
  corrected false clarification about a protein-panel starting pool. These are
  not six newly successful complete business answers.
- The new regression is `business-barbell-02-q08`: the request explicitly keeps
  every three-account payment set, including sets inside larger circles. The base
  selects the exact-size operation; the revised adapter selects maximal circles.
  The strict scorer also penalized irrelevant temporal fields in the base route,
  which is why the original strict score alone hid this substantive regression.
- Four revised-adapter operation failures remain across two payment-review
  wordings and two graphs: full eligibility pools versus mutually complete
  circles, and every three-account set versus maximal circles. Two other failures
  concern service-team goals where the authored contract expects clarification.
  Those goal expectations are not independent user judgments. Each arm has two
  route execution proposals against those clarification labels; this comparison
  ran no native jobs and does not establish executed unsafe work.
- Median amortized batch time is 12.71 seconds for the base and 17.28 seconds
  for the adapter. These are static-generation measurements, not user turn times
  or evidence of a latency improvement.

Remaining: finish the original-adapter comparison, both candidates' practical
conversations and the revised candidate's retention/real-data checks. Diagnose
the new operation regression in the application before candidate selection;
the frozen nine-workflow set does not directly exercise this payment-trio wording.
Decide whether further training is warranted from the combined evidence, then
evaluate the chosen frozen candidate on the reserved source. No adapter has been
selected for that final evaluation or deployed.

## 2026-10-03 — Payment-group regression diagnosed in the application

Completed before the user stop:

- Replayed the unchanged saved base and business-adapter routes for
  `business-barbell-02-q08` in fresh isolated application stores, using the
  existing FP8 planning/answer stages. The request asks for every three-account
  mutual-payment set, including sets within larger circles.
- The base route produced the five expected groups through the native exact-size
  computation and passed all workflow checks. The business-adapter route led to
  `unsupported`, no native job, and no result. Its answer incorrectly refused a
  capability that the application has.
- This establishes the observed consequence of that saved routing error: a false
  refusal. The planner prevented the wrong computation but did not repair the
  route. No fresh local routing predictions, oracle feedback, reserved-source
  calls or deployment were involved. The diagnostic completed at 23:40:22 UTC.

Evidence: [application replay](reports/business-payment-regression-replay-v1.json)
and the preserved per-arm application histories linked in that report.

## 2026-10-03 — User-requested stop and handoff

Completed:

- Stopped `graphmine-business-evaluation-queue-v1.service` at 23:41:16 UTC and
  confirmed both its process and original-adapter comparison child were gone.
  The separate diagnostic had already completed. The serving application/model
  was not requested to stop; no new deployment was made.
- Preserved 46/124 original-adapter business routing calls without reporting a
  complete score. Saved each previous status as `status-before-user-stop-v1.json`
  and recorded `stopped_by_user` in both live status files.
- Rechecked both saved adapter hashes against their completion reports. The
  original 48/48-step and business 45/45-step weights are intact. Training data,
  evaluation evidence, logs and prepared comparison tools remain available.
- Wrote the [handoff record](reports/finetuning-user-stop-2026-10-03.json), linking
  the completed work, partial results, limitations and artifact hashes. The
  underlying process-stop evidence is
  `.graphmine-learning/business-evaluation-user-stop-v1.json`.

Incomplete at this stopping point: the original adapter's remaining 78 business
routing calls; both adapters' practical local conversations; the business
adapter's 53-case retention and 22-turn real-data checks; candidate selection;
the unused final reserved-source evaluation; and integration for the user's own
end-to-end test. None of these is marked complete or scheduled to resume.
The latest adapter improves the reviewed static routing count from 113/124 to
118/124, but an overall end-to-end improvement has not been demonstrated.
