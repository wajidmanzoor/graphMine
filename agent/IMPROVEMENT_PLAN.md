# Plan to make GraphMine usable without graph-mining knowledge

The [application evaluation](evaluation/APPLICATION_USABILITY_REPORT.md) shows
that the first investment should be in preserving the user's intent, grounding
the answer, and completing the conversation. Adding more algorithms or training
on unreviewed traces would not resolve the observed orchestration defects.

## User-testing deployment — 2026-10-04 UTC

The user explicitly authorized deployment of the saved candidate, a revised UI,
visible local-model reasoning, a separate results page and local feedback capture.
Those changes are now deployed as `business-v1-pilot.1`, using the business adapter
for routing and the retained FP8 model for other stages. Existing application data
is preserved; the remaining fine-tuning evaluation queue stays stopped.

The UI now has Chat/Results navigation, activity summaries, expandable reasoning
actually returned by Qwen, session restoration, tester aliases, answer-specific
feedback, local commands, JSONL feedback export, session archives and offline
reports. Feedback is stored with a conversation snapshot and model identity and
does not enter model prompts or trigger automatic training. The first live
acceptance returned both expected collaboration groups from the sample data and
verified the actual adapter/base stage assignments. All 295 Python tests and two
browser scenarios passed. A separate browser check verified the displayed Qwen
reasoning matches the saved response exactly, with no additional model call.

See the [user guide](README.md#user-testing-pilot-business-v1-pilot1) and
[deployment evidence](evaluation/reports/pilot-deployment-2026-10-04.json). The
exact-size grouping false refusal and incomplete comparison gates remain recorded;
the pilot's successful deployment is not evidence of a broad end-to-end gain.
The next useful evidence is actual user feedback, reviewed before any future
training. Shared-token access remains a shared workspace rather than private
per-user accounts.

## Fine-tuning continuation — 2026-10-03 UTC

This is the historical stop checkpoint before the separately authorized deployment above.

Paused at the user's request at 23:41:16 UTC. Both training runs completed; the
remaining evaluation queue is stopped and all artifacts are preserved. The
user requested a final status before setting up their own end-to-end test.
That test integration is pending. See the
[stop/handoff report](evaluation/reports/finetuning-user-stop-2026-10-03.json).
Historical next-step lists below do not authorize automatic continuation.

Progress and remaining work are recorded after each major task in the
[fine-tuning log](evaluation/FINETUNING_PROGRESS.md). The original handoff below
is historical: the first adapter subsequently completed all 48 training steps.
The complete 132-case comparison scored 132/132 for the adapter and 123/132 for
the matched base under the documented application review. Eight improvements
preserve refusal metadata and one corrects a false refusal; most question wording
is shared with training. The harder 53-case comparison is complete: under the
recorded early-clarification audit, both matched arms score 49/53, with three
improvements and three attachment-stage differences. All three saved adapter
routes correctly requested missing inputs during a live planning-gate replay,
without creating jobs; those were replay diagnostics, not fresh predictions.
The full synthetic application comparison passed 20/21 turns for every arm,
with the same non-routing result-reuse failure and no matched pass/fail changes.
The local adapter's median turn time was 49.4 seconds versus 46.2 for the base.
Both missing-file and supplied-file planning gates passed using the saved
adapter routes; the early-clarification timing differences do not establish
executed unsafe jobs. Matched real-data evaluation is complete: raw grades are
22/22 for the base and 20/22 for the adapter. Both flagged adapter cases preserve
the requested filters but express numeric zero as `0.0`; an audit retains the
original grades and records that numeric equivalence.

The user subsequently clarified that training must use practical application
and business questions, with technical operation mapping kept in the labels.
The separate `business-curriculum-v1` has 180 training, 68 validation and 124
evaluation cases with different wording banks and separated graph families.
It includes goal-only requests that need domain-language clarification and
explicit exclusions for source tasks without a sensible authored business
scenario. Its computation labels reuse revalidated native evidence; its language
is authored synthetic supervision, not independently reviewed teacher data.
The revised run completed all 45 training steps in
`.graphmine-learning/finetune-qwen27b-business-v1`; all saved tensors are finite
and its 496 LoRA-B tensors differ from the first candidate. The matched practical
routing comparison is complete: reviewed scores are 113/124 for the base and
118/124 for the revised adapter, with six improvements and one regression. Five
improvements clean up clarification metadata; one corrects a false clarification.
The regression selects the wrong account-group computation. A completed saved-route
application replay found that the base returns all five requested account triplets,
while the business adapter's route causes an incorrect unsupported response and no
computation. The planner prevents the wrong computation but does not recover the
routing error; this is a diagnostic, not fresh routing accuracy evidence.
The serving reference passed 115/124 practical routing cases and all 21 turns /
nine practical conversations. At the user stop, the original adapter's business
routing comparison had 46/124 saved calls. Both candidates' practical local
conversations and the revised candidate's operation/context and screened real-data
checks had not started. Candidate selection and the final reserved-source
evaluation remain incomplete; that source is still unused. No adapter has been
promoted to the serving application, and overall end-to-end improvement remains
unproven. The next requested phase is user testing after the status handoff.

## Post-real-data fixes and local-training pilot — 2026-10-03 UTC

The follow-up implementation separates unchecked planner assumptions from
displayed facts, records exact-field filter statistics, and explicitly describes
attribute filtering as an application capability independent of kernel weights.
Empty selections are completed answers. A bounded model review can correct an
incorrect refusal, but does not bypass the weight, direction or pattern gates.
Weight attributes/use are now typed separately so they cannot hide behind a
false boolean flag.

Answers now use source entity names, readable membership/attribute tables,
answer-only networks with application attribute colors, and validated follow-up
actions. Numerical/behavioral checks and presentation-contract checks are
separate. Actual screenshots still need inspection; neither checker certifies
that a novice will find the interface useful. Both revised real-data trials
passed: 44/44 turns across 32 scenario runs, using the deployed reasoning
profile. The 220 Python and two browser tests also pass. Code/data hashes,
deployment status and actual training evidence are indexed by the
[checkpoint report](evaluation/reports/real-world-fixes-finetune-2026-10-03.json).
The API has been restarted with its existing store; the serving model is unchanged.

The new `synthetic-v2` curriculum contains 48 distinct graphs and 396 cases:
288 native computations checked against independent references and 108 explicit
clarification/refusal contracts. The export has 192 training and 72 validation
rows, with 132 test-family cases excluded. It adds exact-size groups, empty
vertex/edge selections, score/ascore distinctions, explicit cost/score weighting,
and combined filtering-plus-weighting refusals. Production and export now share
the routing prompt and input builder. Old corpora and failed baselines remain
preserved; they are not silently relabeled or treated as current review evidence.

Per the user's request, the next model step is a bounded **local routing-adapter
pilot**, not production promotion. The [training CLI](CLI.md#local-qwen-adapter-training)
pins Qwen/Qwen3.8-27B base weights and dependencies, trains assistant tokens only,
isolates the spare GPU, saves optimizer/checkpoint evidence and never changes the
serving model. Its labels are oracle-gated synthetic supervision, not distilled
Codex reasoning. The real-data teacher/reviewer questions remain evaluation-only.
The pilot has now started: the saved step-2 adapter contains 496 nonzero LoRA-B
tensors and all 992 adapter tensors are finite. The handoff report captured four
optimizer steps; live progress is in the run's `status.json`. This verifies a
real weight update, not improved task accuracy or a completed training run.

Remaining gates and priorities:

1. Finish the pilot and compare an enabled adapter with the **same unadapted
   base and quantization**. Separately compare against the deployed FP8 model;
   precision changes must not be credited to training. Test application queries,
   multi-turn scope changes, unsupported requests, numerical grounding and
   latency. Apply the routing adapter only to routing unless other stages also
   pass regression evaluation. No automatic deployment based on training loss.
2. Expand teacher-generated language on new synthetic task cards with blind,
   calibrated semantic review, exact attribute/unit/weight matching, independent
   oracle checks and held-out families. Preserve rejected examples and reasons.
   The 192-row template pilot is a starting curriculum, not broad distillation.
3. Complete presentation polish. The inspected empty-result card still exposes
   labels such as `complete=true`, and its exact filter explanation is initially
   collapsed. Protein grouping still has a generic caveat mentioning departments
   and fraud rings. These are recorded as assistant-evaluation feedback, not
   fabricated user feedback or numerical failures.
4. Measure latency under the deployed reasoning profile, then test reduced
   reasoning, context caching and smaller stage-specific prompts against the same
   questions. Do not compare different prompts/profiles as a controlled speed or
   accuracy improvement. Current numerical work is tiny relative to model time.
5. Test larger real graphs, dense overlapping groups, table truncation,
   concurrent sessions and GPU contention. Training shares the native-compute
   GPU, although inference remains on its separate GPU. Small 12-node source
   slices do not establish scale or general application accuracy.
6. Run a novice domain-user task study and a later untouched-source evaluation.
   OpenFlights remains outside development model calls and training; inspected
   workplace/STRING cases are development regressions, not an untouched test.

## Implementation checkpoint — 2026-10-03 UTC

The first domain-first implementation is now in the working tree. It adds:

- Typed non-executable refusals/clarifications; temporal-pattern, direction,
  weight-use and unit checks before execution; exact tool-specific generation
  schemas and server-owned backend selection.
- Rich graph context, bounded read-only record inspection, preserved original
  attributes, typed customer/product partition inference, CSV column mapping,
  and attributed, recorded input projections for filters.
- Structured follow-up routing and up to four independent analysis steps, with
  active filter inheritance and combined results.
- Deterministic named answer facts, original-record joins, separate unverified
  model implications, tested answer-view recipes, interactive answer networks,
  real event timestamps, and self-contained HTML reports from the CLI.
- Full local traces, user/evaluation feedback, malformed-output recovery bounded
  to one repair attempt, regression tests, and real-model/native-GPU replays.

These are application safeguards, **not proof that the model always understands
the question**. Semantic requirements still originate in model extraction. The
original priorities and acceptance criteria below remain the design record;
they are not all closed. In particular, result reuse/derivation is not a general
query engine, supporting steps cannot depend on each other's output, domain
clarifications and proposed next questions can still be too technical, and large
graphs and concurrent use have not been validated by the small fixtures.

See the [follow-up evaluation](evaluation/APPLICATION_USABILITY_REPORT.md) and
[CLI/data/report guide](CLI.md) for actual evidence and usage. The existing live
API was not restarted as part of those initial isolated tests. It has now been
restarted for the next-phase checkpoint below, retaining existing sessions and
the running model process.

## Automated-data checkpoint — 2026-10-03 UTC

The local `graphmine-agent learning` workflow now generates seeded application
graphs/questions, audits native outputs with independent bounded reference
solvers, measures the live agent on held-out families, and exports gated
intent-routing candidates. See [the commands and boundaries](CLI.md#synthetic-data-and-learning-candidates).

The first corpus contains 24 graphs and 114 questions across workplace, protein,
account, infrastructure, retail and security applications. It keeps all questions
for a graph together, separates topology generator families, and rejects
isomorphic topology leakage. It produced 54 training and 22 validation
RouteDecision candidates; 38 test questions are excluded from the export.
Candidate data remains local and has not been used to update weights.

The [recorded live baseline](evaluation/reports/synthetic-learning-2026-10-03.json)
passed 35/38 held-out single-turn contracts: all 28 executed analyses matched
the references, and all ten non-executable questions created no job. Three
weighted-route refusals used `needs_information` instead of `unsupported` while
their text correctly stated the missing capability. These are status-contract
mismatches, not wrong weighted computations. Linked feedback was saved, and the
model/prompts were not tuned on those held-out results. Median turn latency was
20.75 seconds with planning reasoning set to `none`; the deployed API retains
its own existing profile. The report records the live/native source boundaries.

Crucially, data generation found infrastructure defects before model training:

- CUDA-MS returned a group of three with `optimal: true` although a group of
  four exists. Three direct reproductions confirmed this. The library had used
  a local relaxation mask as a certified global upper bound. That certification
  was removed and covered by a native regression test.
- Maximum-Clique-on-GPU aborted on an eight-vertex cycle-with-chord fixture.
  The abort was reproduced; its root cause is not yet repaired.
- Both backends are excluded from agent selection, independently of benchmark
  rankings. GPUMaximumClique passes the affected examples and the corpus's
  maximum-clique checks. With that selection, all 84 executable reference checks
  and 30 separately identified non-execution contract checks pass. The original
  failed audits are retained, not rewritten.

The initial failed audit export correctly quarantined its bad example. The
subsequent independently passing audit allows 76 template-derived candidate
rows. Five local-model paraphrase calls produced 13 additional wording proposals;
all 13 remain quarantined. Some proposals introduce terms such as “maximal” or
“largest possible,” illustrating why syntax validation and self-consistency
cannot certify semantic equivalence.

This phase is an evaluation/data foundation, not a claim of improved model
weights or comprehensive novice usability. It currently covers seven native
operations, a small set of refusal/clarification cases, and isolated single-turn
questions. Community checking verifies returned-partition invariants, not global
optimality. Native audits and live language understanding are reported separately.

Next gates, in order:

1. Repair and independently re-audit the quarantined native adapters before
   restoring them. Keep correctness exclusions separate from latency policy.
   Normalize the refusal status when unsupported computation and missing input
   coexist, without inviting an upload that cannot enable the requested task.
2. Expand semantic coverage: plain business goals, variable wording, missing
   units/attributes, weighted/directed requirements, contradictory constraints,
   prompt injection in records, follow-up corrections and dependent tasks.
   Add new untouched test families for the next model comparison; do not tune
   on failures from the current inspected test set and call it unseen again.
3. Add independent semantic adjudication and execution checks for proposed
   paraphrases. Generate more wording automatically, but reject shifts between
   “every maximal group,” “one largest group,” and “every tied largest group.”
   Review domain vocabulary, assumptions, and confidence calibration in the
   template-derived targets too.
4. Choose a stronger teacher and a fixed generation budget/data policy. Teacher
   output remains a candidate; graph oracles and application constraints remain
   the correctness authority. Expand from intent targets to valid tool arguments
   only after these gates work. Keep numeric facts and ID joins deterministic.
5. Compare unchanged Qwen, improved prompting/retrieval, a stronger planner, and
   a small adapter fine-tune under the same task, error, refusal and latency
   measures. Training serving changes require their own rollback and held-out
   promotion gate. Repeated trials and domain-user review remain necessary.

This eval-first ordering also follows the
[official OpenAI supervised fine-tuning guidance](https://developers.openai.com/api/docs/guides/supervised-fine-tuning),
which discusses establishing evaluations before fine-tuning and using qualifying
larger-model outputs for distillation. It does not establish Codex teacher API
access or make the local Qwen checkpoint an OpenAI fine-tuning target.

## Semantic-review checkpoint — 2026-10-03 UTC

The next phase now has executable teacher-calibration, wording-generation,
blinded semantic-review, isolated replay, and reviewed-export commands. See
[the workflow and budget controls](CLI.md#teacher-calibration-and-semantic-review).
This implements the tooling for gates 3–4 above; selecting a qualified stronger
model and generating approved data are still open.

The reviewer receives only a candidate question and graph vocabulary/schema.
It must extract a typed meaning with question-grounded evidence. A deterministic
comparison checks quantifiers, thresholds, filter values/types, weighting,
direction, event roles/order, and time units. Additional requested constraints
must be surfaced, not silently dropped. A conservative wording screen flags
novice-unfriendly jargon and possible maximal-versus-largest substitutions.

Export requires a calibrated reviewer distinct from both generator and student,
a passing live replay, and independently checked native outputs. It revalidates
the saved request/raw response, question-bound replay, exact source hashes and
semantic contract; changing a pass flag cannot bypass the checks. Only verified
synthetic training families enter this route-candidate export. Neither this
reviewer nor the production model is treated as the source of numeric truth.

Observed results, not a general model-accuracy claim:

- The first local reader profile passed 4/14 development controls. Explicit goal
  definitions and smaller schema-focused context raised this to 9/14. Both
  reports are retained. These train/validation controls were used for prompt
  development; they are not a fresh held-out comparison.
- Remaining failures include treating a relative time window as an absolute
  timestamp filter, adding a pairwise-group minimum to a customer/product
  bundle, conflating missing data with ambiguity in the requested mathematics,
  and missing/non-verbatim evidence spans. Not every rejected case is a wrong
  operation: evidence-format failures also fail this strict gate.
- Of 13 previously generated paraphrases, 2 passed meaning/wording screening;
  both passed real agent/native replays. Six had jargon or risky “largest”
  wording flags (some overlapped other failures). Both promising replays and
  all rejected proposals remain available in local history/evidence.
- All 13 remain quarantined, and the reviewed exporter produced zero training
  rows. The local reviewer passed neither the calibration nor the distinct-model
  requirement. This is a successful rejection gate, not completed distillation.
- The Python suite passes 137 tests, including 33 new semantic-review/provider/
  export tests. Production planner behavior and deployed weights were not
  changed in this phase. No paid teacher calls or training jobs were started.

Evidence is under `.graphmine-learning/local-calibration-v1/`,
`local-calibration-v2/`, `semantic-review-v1/`, `semantic-replay-v1/`, and
`reviewed-candidates-v1/`; the compact
[evaluation record](evaluation/reports/synthetic-learning-2026-10-03.json)
records hashes and failures. The reviewed file contains routing targets only;
it does not establish quality of generated explanations or visualization design.

Provisional teacher choice: pilot GPT-6.1 Sol first, with GPT-6 Astra evaluated
as a possible stronger reviewer. This follows the official
[model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection)
and [model comparison](https://developers.openai.com/api/docs/models/compare),
not measured GraphMine results. The integration uses the documented
[Responses structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs).
It requires explicit external opt-in, a securely configured API key and finite
per-invocation reservations. The full two-model dry run reserves about $5.66 at
2,048 output tokens; Sol alone reserves about $0.94. A $5 full comparison is
refused before sending requests. These are conservative estimates, not a
provider-enforced billing cap. API access and paid-call approval remain pending.

Next: run the approved small external pilot, choose a reviewer only if it passes,
then review/generate a modest batch and inspect disagreement patterns. Expand
to fresh application wording and multi-turn tests before any adapter experiment.
Distinct models can still share blind spots; small controls, automatic evidence
spans and exact result checks do not replace domain-user evaluation. Continue
keeping template-derived targets separate from reviewed paraphrases, and do not
train on failed interpretations or on the already-inspected test set.

## Conversation-reliability checkpoint — 2026-10-03 UTC

The [conversation evaluation record](evaluation/reports/conversation-reliability-2026-10-03.json)
now covers six automatically derived workflows and 21 turns, using a new seed
but existing training/validation graph families. The unchanged local Qwen
baseline passed 19/21 turn contracts; the final replay passes 21/21, with all
six workflows complete. These are development regressions used to fix bugs,
not untouched held-out accuracy or evidence that the model learned new skills.

The implemented changes address concrete failures:

- Unsupported calculations take precedence over missing data. A weighted-route
  request is refused without implying that uploading costs would make an
  unavailable calculation possible. No unweighted substitute is executed.
- An uncertain follow-up classifier delegates the original question to the full
  planner instead of inventing missing inputs. Genuine ambiguous goals still
  receive clarification questions.
- Follow-up context includes actual prior parameters/output requests and the
  latest graph-scoped unresolved request. A refusal is not a completed result
  and does not silently replace the active analysis's constraints.
- The action classifier now has the same compact-JSON/no-padding instruction
  as the other structured prompts. One event-window correction fell from
  68.77 seconds with a token-limit/repair cycle to 31.21 seconds without that
  retry. The final replay's median was 25.08 seconds and maximum 38.37 seconds;
  this small sequential run is not a general latency benchmark.

The workflow runner checks corrections and cleared filters, one largest group
versus every unextendable group, clarification replies, independent customer
and product minimums, time windows/units, refusal and recovery. Native outputs,
named original attributes and answer-view contracts are independently checked.
The recorded device workflow repeats its initial three-partner threshold before
adding a year filter; it does not demonstrate changing that threshold.

The first updated run was initially scored 19/21 because the grader incorrectly
required a new job for two valid reused answers. Regrading now requires a saved
completed result from the same session and original graph bytes, with matching
parameters, scope and independently checked output. Under the same corrected
grader the baseline remains 19/21 and the updated run is 21/21. Original reports
and automatic feedback are preserved, with regrading lineage recorded separately.
The final fresh replay also passes 21/21 using this grader from the start.

Verification: 167 Python tests and two browser tests pass; the browser suite uses
model/native test doubles, while the three workflow runs use the real local
model and native analyses. The API was restarted after an online SQLite backup;
its health is ready, database content is unchanged, and the model process stayed
running. Replay planning used reasoning effort `none`; the live API retains its
existing `medium` planning setting, so replay timings are not deployment timings.

Following the [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
these scoped checks and failure histories come before training. No external
teacher calls or weight updates were made. Previously reviewed candidates need
new replays against the changed production sources before export can qualify.

Remaining priorities: executable, scope-correct follow-up suggestions in domain
language; human assessment of answer/visualization usefulness; fresh untouched
workflow families and repeated trials; and an explicitly approved stronger
teacher pilot. Some observed suggestions still use graph jargon or a stale year
despite a correct current answer. The two excluded native adapters, dependent
analysis steps, large-graph behavior and concurrent-use validation remain open.

## Codex subscription teacher pilot — 2026-10-03 UTC

The [pilot record](evaluation/reports/codex-teacher-pilot-2026-10-03.json)
confirms that the existing ChatGPT-authenticated Codex CLI can run the teacher
and reviewer without the paid OpenAI API adapter. Following the documented
[non-interactive interface](https://learn.chatgpt.com/docs/non-interactive-mode),
the learning commands now accept `--provider codex --allow-codex`. The installed
CLI was 0.160.0. No login credentials were copied into the project or call logs.

- Reviewer `gpt-6-astra` passed all 14 semantic calibration controls.
- Teacher `gpt-6.1-sol` made five generation calls, producing 10 application-language
  questions from five training graph families in four domains and three operations.
- Astra passed all 10 blinded meaning/wording screens. The unchanged local
  `Qwen/Qwen3.8-27B-FP8` passed all 10 live replays, including independent native
  output and answer-view/attribute checks. A fresh five-case native audit also
  passed 5/5. Student replay used planning reasoning effort `none`; the live API
  retains its existing `medium` setting.
- Export rechecked calibration, saved response evidence, current source hashes,
  native audit and student replays. It produced 10 `RouteDecision` candidate rows
  and zero quarantines in `.graphmine-learning/codex-reviewed-candidates-v1/`.
  Row schemas, training-only splits and file/row hashes were checked separately.
  Labels remain source-contract-derived, not copied from teacher reasoning.

The 29 successful Codex inference invocations reported 332,232 input tokens
(35,328 cached, already included in input) and 4,466 output tokens. These are
reported usage, not a dollar bill or a measurement of remaining plan allowance;
account limits and credit settings still apply. One initial CLI launch failed
locally because a reserved built-in provider cannot be overridden. Its evidence
is retained in `codex-astra-calibration-v1`; no model usage was reported, and its
failed controls are not a model-quality score. The corrected run uses the
built-in provider unchanged. There was no API-key fallback or model substitution.

Each call uses forced ChatGPT login, a clean allowlisted environment, a fresh
temporary directory, ignored user config, read-only/ephemeral execution and
disabled tools. Raw redacted events, requests, schemas and usage stay in private
local history. Call counts, a 120-second timeout and 1 MiB per-stream capture
bound execution. The CLI may retry internally within that timeout; the application
does not retry. The output-token limit is a post-call acceptance check, not a
generation or billing cap. The API and model processes stayed running and healthy.

Verification: 186 Python tests and two browser tests passed. The browser suite
uses test doubles; the pilot replays use the real local model and native analyses.
No weight training, training upload, model deployment change or API restart was
performed. The new provider changes review-source fingerprints, so earlier
calibration/review artifacts cannot qualify new exports without fresh runs.

This is a successful pipeline pilot, not evidence of improved Qwen weights,
held-out accuracy, novice usability or attractive visualizations. The questions
are close paraphrases of precise synthetic templates. Distinct model identifiers
reduce same-model review but do not prove independent model lineage; the CLI
stream records the requested model, not a provider-attested served-model identity.
Next, generate harder application-only requests and negative/ambiguous cases,
add untouched graph/workflow families, repeat the checks and assess a sample of
answers and visualizations. Only then compare a separately approved training
experiment against the unchanged baseline with a rollback path.

## Public-data evaluation checkpoint — 2026-10-03 UTC

The learning CLI now has a separate real-world evaluation workflow. See
[the source catalog and commands](CLI.md#public-real-world-evaluation-datasets).
It preserves downloaded bytes, source/version/license metadata, transformations,
stable original IDs and application attributes. Real data cannot enter the
synthetic training exporter by changing a flag.

Three public sources are prepared: anonymous workplace contacts from SocioPatterns,
STRING v12.0 E. coli functional associations, and historical OpenFlights routes.
The selected graphs each have 12 vertices, enabling independent exact checks.
Workplace contacts are deliberately aggregated into a static undirected graph;
protein confidence remains descriptive rather than silently becoming a supported
weight; airport links explicitly require a listed nonstop route in both directions.
Sampling is activity-/hub-biased or purposive, not representative. Full raw files
are retained where downloaded; the STRING source is itself a bounded API query.

Whole-source separation reserves nine OpenFlights scenarios from all development
teacher, reviewer and student calls. Twenty-one workplace/protein development
scenarios contain 27 turns across six operations, ambiguity, unsupported weights,
empty answers, corrections, attribute filters and a marked adversarial record note.
Source separation prevents this workflow's train/evaluation mixing; it does not
establish unfamiliarity to pretrained models, unseen task types or broad accuracy.

Data preparation itself found issues worth keeping separate from student errors:

- The first native audit omitted optional membership outputs for fixed-size groups
  and surviving entities. The task builder was corrected; the fresh audit passed
  17/17 native checks. This was a harness defect, not a failed graph calculation.
- The first real-data reviewer calibration passed 7/8 controls. A boolean about
  using weights did not specify which attribute supplied the lengths. The real-data
  meaning schema now records both `weight_attribute` and `weight_usage`, and the
  revised reviewer passed 8/8. The original failure report is retained.
- The community source cards ask for a strict within-group connection guarantee
  that the heuristic partition computation does not promise. Both wording proposals
  are quarantined rather than assigning a misleading correctness label. The native
  community checker verifies coverage and modularity only, not this stronger claim.

The rerun selected 17 non-duplicate development scenarios, retaining both multi-turn
workflows and the injection case. Its 42-call ceiling plus the initial eight
calibration calls stays within the announced 50 Codex-call bound. Raw model events,
blinded inputs, screening failures and subsequent student feedback remain private
local artifacts. No paid-API fallback, fine-tuning or deployed-model change is part
of this evaluation. Following the [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
repeated task-specific checks and calibrated graders precede any training decision;
automatic checks do not replace assessment of domain usefulness.

Completed-run evidence is saved in
[the real-world evaluation report](evaluation/reports/real-world-learning-2026-10-03.json).
The final corpus is `.graphmine-learning/real-world-corpus-v4`; the accepted
questions are in `real-world-questions-v2/questions.json` under the same parent.
Raw student evidence is in `real-world-student-v1.json` and
`real-world-student-runtime-v1/history/`. Earlier preparation and calibration
failures remain available; they were not counted as student failures.

| Check | Observed result | Interpretation |
| --- | --- | --- |
| Revised reviewer calibration | 8/8 | Small calibrated control set, not proof of grader accuracy. |
| Generated scenarios accepted | 15/17 | Two community source cards quarantined. |
| Independent native checks | 17/17 | Includes community coverage/modularity, not its quarantined stronger promise. |
| Student turn checks | 38/42 | Two fresh-session replays of 21 turns across five executable operations. |
| Complete scenario replays | 26/30 | Only 12/15 scenarios passed in both repetitions. |
| Software regression tests | 199 Python + 2 browser | Browser tests use fixtures; three additional real saved answers were inspected offline. |

Both repetitions passed 19/21 turns, but the failures differed. Only 18/21 turn
identities passed both times. Three failures returned `needs_information` for
valid empty workplace requests, despite correctly describing zero matches in
prose. The fourth mistook the supported protein filter `score == 0.999` for an
unsupported weighted computation. The same protein filter passed in repetition
one; the department restriction failed in repetition one and passed in two.
Resets and the other checked computations completed. All 28 native jobs finished;
30 turns had validated result evidence, including two prior-result reuses.

Crucially, **passing these checks is not a good-answer score**. Both zero-score
protein answers included the false assertion that eight links had score zero,
although the actual score range is 0.705–0.999. This claim appeared in an
unchecked planner assumption copied into the displayed limitations. Other
inspected passing replies exposed algorithm jargon, generic "entities", clipped
JSON-like membership tables and unhelpful visualization defaults. Original
attributes are retained: department coloring works when selected, and the
six-protein largest-group network correctly shows just the returned answer.
Six qualitative feedback records supplement four automatic failure records.
All ten are linked to their local turns/results as `assistant_evaluation`, not
mislabelled as user or human review. Three HTML reports and five screenshots are
indexed in the report; no external resources were fetched when rendering them.

Median end-to-end turn latency was 27.3 seconds; nearest-rank p95 was 45.3 seconds,
even on these small graphs. This includes model/agent work, not just kernel time.
The isolated student used planning effort `none`; the untouched deployed service
uses `medium`, so this is not a deployed-configuration accuracy or latency claim.
The run used exactly 50 ChatGPT-authenticated Codex calls across both calibration
attempts and generation/review (587,503 input tokens including 77,952 cached;
8,881 output tokens). These are CLI usage receipts, not an API bill or a promise
of unlimited subscription usage. The live API remains ready, with unchanged
processes/model and no training job launched.

## Next improvement and automated-data plan

1. **P0: validate every displayed factual claim, including assumptions.** The
   protein zero-score query produced a correct empty computation but also the
   claim that eight links had `score = 0`. The source has none: its minimum score
   is 0.705. The planner's context does contain eight zeros under `ascore`, a
   different evidence channel. Cross-column confusion is a plausible cause,
   not a demonstrated account of the model's internal reasoning. Currently
   `answers.py` copies free-text planner assumptions into displayed limitations.
   Replace that path with attribute-qualified evidence references and validated
   counts/ranges. Test misleadingly similar column names and incorrect claims
   inside limitations as well as the headline. Acceptance: the false claim is
   rejected even when the computed answer is correct; no unsupported datum is
   legitimized by an "Assumption" prefix.
2. **P0: finish valid empty requests without an unnecessary clarification.**
   A filter selecting no contacts, or only one participant when groups of three
   are requested, is not missing information. Return a completed empty answer
   with the active filter, source hash and a plain-language reason. A validated
   deterministic proof of emptiness can avoid launching a kernel; teach the
   evaluator to accept that evidence-bearing result, not arbitrary model prose.
   Keep genuine ambiguity separate. Acceptance: both empty workplace requests
   complete in repeated trials, retain the intended scope, and support a later
   reset. The current grader requires a completed result, so its failures must
   not be reported as incorrect arithmetic when the prose correctly says zero.
3. **P0: distinguish filtering by an attribute from weighted computation.**
   The protein follow-up "use associations with score exactly 0.999" completed
   in repetition one but was refused as unsupported weighted analysis in
   repetition two. Equality filtering is supported and does not make the graph
   calculation weighted. Make filter predicates and numerical weight use separate
   validated decisions, with contrastive regression cases sharing the same column.
   Extend the existing weight-use boolean with explicit attribute/use semantics;
   describe supported pre-analysis filters separately from kernel capabilities.
   The failing router already extracted the correct equality predicate but also
   set `requires_edge_weights=true` and falsely declared filtering unavailable.
   Acceptance: confidence filtering executes in every repeat; actually adding
   scores as route lengths still receives the supported, explicit refusal.
4. **P1: make the answer and its default view application-specific.** Use
   "participants" and "proteins", not "entities"; show the requested names and
   departments/STRING IDs as readable columns, not JSON blobs. Put the short
   answer and useful view before repeated question text and implementation notes.
   Use department coloring by default when relevant; retain the working original
   attribute joins and answer-only networks. For many overlapping trios, provide
   a readable group-membership table and optional single-group inspection rather
   than a dense all-group picture. Hide operation names, backend warnings and
   raw paths behind details; make suggested follow-ups typed and executable.
   Acceptance: browser checks verify labels, membership, defaults and readable
   empty states; domain users can identify the answer without graph-mining terms.
5. **P1: broaden and repair the evaluation before choosing a model.** Repair
   community task cards so they request the heuristic's actual capability, not
   a strict per-member internal-versus-external guarantee. Recalibrate the
   reviewer before admitting replacements. Generate short, messy domain goals
   and multi-turn clarification replies, not only verbose mathematical contracts
   rewritten without jargon. Include answer-grounding and presentation grades
   separately from task completion and arithmetic. The workplace pruning case
   retains all 12 nodes; the protein case retains eight. Add explicit cascade
   cases and verify that an incorrect one-pass implementation fails, rather than
   relying on these results alone. Keep the airport source
   unopened by model calls until the model/prompt configuration is frozen; add
   more whole-source and graph-family holdouts for an actual generalization test.
   Compare the benchmark's `none` planning effort with the deployed `medium`
   profile under a separate bounded run; neither profile's result stands for the
   other. Require repeated runs and a small domain-user assessment.
6. **P2: measure scale and workflow limits.** Add paginated/lazy answer
   materialization, resource budgets, cancellable whole-analysis workflows, and
   dependency-aware execution only when a concrete task needs it. Measure memory,
   time to first useful answer and p50/p95 end-to-end latency on larger graphs
   and concurrent sessions. Do not infer scalability from native GPU speed or
   tiny exact-reference slices.
7. **Generate training candidates without hand-authoring each example.** Use
   seeded synthetic graph generators with meaningful attributes, independent
   small-graph oracles, and a stronger teacher to produce diverse application
   questions and candidate intent/plan/answer records. Execute every candidate;
   retain only traces passing semantic, numeric, provenance and rendering gates.
   Store the teacher/version, generator seed, input hash, checker results and
   review status. Quarantine disagreements instead of using a teacher's opinion
   as the correctness label. Existing failure histories supply failure categories,
   not automatically trustworthy training targets.
8. **Compare model adaptation after the application fixes.** Split by graph
   family and workflow, not just question wording. Compare prompting/retrieval,
   a stronger planner, and a small task-specific fine-tune using the same held-out
   suite and latency budget. Start with intent extraction and tool arguments;
   keep ID joins, semantic gates and computed facts outside the model. Spot-check
   a sample of generated data: no manual authoring does not mean no validation.

The bounded Codex/ChatGPT teacher pilot and public-data workflow above are
implemented; no paid-API inference or fine-tuning job has been launched. Larger
generation runs still need an explicit scope and allowance. The training method,
data-use terms and deployment decision remain separate choices. The earlier 10
exported routing candidates are a pipeline proof; real-data evaluation cases stay
out of training exports and do not justify replacing Qwen on their own.

## Original roadmap and acceptance criteria

## 1. Block semantically wrong execution — P0

**Evidence:** `security_unsupported_chain` recognized an unsupported four-host
pattern in prose, yet executed a supported three-host pattern.

Change planning to return a discriminated outcome: `ready`, `needs_information`,
or `unsupported`. Only `ready` may carry an executable plan. Preserve the user's
requested structure, direction, weight use, time units/window, entity roles, and
requested outputs in typed fields. Compare those fields with the operation's
validated profile before creating a job. A runnable parameter combination must
not be mistaken for proof that the operation answers the user's question.

Update `models.py`, `agent_service.py`, `planning.py`, and the executable operation
contracts together. An operation-specific refusal must be expressible after
routing, when the detailed backend capabilities become available. Keep rationale
as explanation; it must not be the only place a refusal is represented.

Acceptance:

- The four-host chain query produces a plain-language unsupported reply and
  **zero jobs**; it never presents the triangle count as an answer.
- The supported three-host sequence still returns its one exact instance.
- Add negative semantic cases for directed/undirected input, ignored weights,
  unsupported patterns, missing time units, and incompatible optional outputs.
- Every accepted job can state the application question it is actually answering.

## 2. Make follow-ups resolve intent and complete work — P1

**Evidence:** asking to rank coworkers by shortest-route mediation after finding
groups did not run another computation. The model instead required the user to
name `betweenness-centrality`. Conversely, the largest-group answer was correctly
derived from a complete prior result and did not need another GPU job.

Replace `_execution_followup` keyword gating with structured turn intent:
explain an existing result, derive an answer from sufficient prior evidence,
request a new analysis, modify an analysis, or answer a clarification. Carry the
active graph, domain meaning, selected entities, earlier constraints, and pending
question explicitly. Treat “show,” “which,” “rank,” and “now…” as possible action
requests without requiring an algorithm name or the word `run`.

When reusing results, record why the prior output is sufficient, including its
completeness/limits. When a new computation is required and supported, proceed
through the validator and worker. Clarifications should merge with the pending
intent rather than restarting from isolated text.

Acceptance:

- The supplemental coworker question runs the ranking and returns Divya = 18,
  Eli = 16, and zero for the other five people.
- “Explain why this account matters” reuses its result without another job.
- The largest-group derivation remains allowed, but its answer and visualization
  must explicitly represent the derived four-person group.
- Add multi-turn cases involving a changed measure, changed threshold, uploaded
  supporting file, changed graph, and a completed versus truncated prior result.

## 3. Ground and simplify the answer — P1

**Evidence:** correct computations were accompanied by false connectivity claims,
unsupported absence claims, misplaced biological claims, an incorrect unused-edge
count, and internal placeholders. `_sanitize_evidence` validates values/paths,
not the logical relationship between a claim and its evidence.

Build common factual answer components directly from structured outputs:
named groups, ranks, counts, completeness, warnings, and relevant input metadata.
Give the analyst those verified facts and a small set of allowed claims. Claims
about original edges, components, timestamps, labels, or group overlap must use
the corresponding input or a computed fact, not a proxy such as graph density.
Provide bounded read-only access to the relevant graph records when needed.

Separate computed facts, justified derivations, hypotheses, and unknowns in the
result contract. Keep background domain knowledge visibly separate from dataset
evidence. Default to a short answer, the requested named items, and the most
important limitation. Keep backend IDs, internal paths, and formal notation in
an expandable technical view or `/result`.

Acceptance:

- The collaboration answer acknowledges the Divya–Eli connection.
- The security answer identifies six unused events, not eight, when explaining
  participation in its one three-edge occurrence.
- No claim of fraud, a confirmed protein complex, or statistical significance
  is inferred solely from graph structure or a raw score.
- Unsupported suggested parameters and placeholder text are rejected before
  presentation. Evidence tests include correct values attached to false claims.

## 4. Collect domain meaning and resolve routine inputs — P1

**Evidence:** customer/product types were present in the uploaded graph, but the
model asked only for `left_partition`. The fraud clarification asked the user to
choose a formal graph problem.

Add a persistent graph context containing entity kinds and display names, what
connections mean, direction, weight meaning/unit, timestamp unit, and relevant
attributes. Preserve that context through planning, execution, and interpretation.
Use bounded summaries and selected records for large graphs rather than placing
the entire graph in every prompt.

Infer the two sides of a customer/product graph when types are unambiguous and
the connections validate that assignment. Otherwise ask “Which records are
customers, and which are products?” and give a concrete example. Offer a simple
column-mapping flow for ordinary CSV files. Clarify investigation goals using
domain choices such as coordinated groups, bridge accounts, or a time sequence.

Acceptance:

- The retail example runs from its typed graph without a hand-authored partition
  file; ambiguous or inconsistent types produce a useful question.
- A novice can answer clarifications without learning `left_partition`, `k`,
  `induced`, an operation ID, or a backend name.
- Entity names, directedness, weights, timestamps, and units survive a round trip
  and are reflected in the answer's limitations when an operation ignores them.

## 5. Make visualization promises match displayed data — P1

**Evidence:** all requested views were discarded in 8/10 baseline interpretations;
valid remaining specifications still promised filters the browser ignores.

Use one documented reference convention for raw result data. Normalize safe
equivalents such as `result.output...` deliberately; reject summary-wrapper paths
with a recorded reason. Validate field encodings and supported interactions, not
just whether a root path exists. Share a small capability contract between the
analyst and renderer so it can promise only implemented behavior.

Materialize application-facing tables for groups, customer/product memberships,
rankings, and matched events joined to original timestamps. Implement selection
across every returned group, actual table filters, and a time axis with declared
units. Derived results need derived view data; a title cannot turn a trio array
into a maximum-group result. Record proposed, rejected, accepted, and fallback
view choices explicitly. Provide a readable table when a richer view is unavailable.

Acceptance:

- Every retained visualization resolves to the intended data and produces a
  nonempty view when the corresponding result is nonempty.
- The selected protein table contains exactly four rows.
- A user can inspect both retail bundles and all five collaboration trios.
- The largest-group view selects four people, and temporal views show the actual
  event times. Browser tests inspect nodes/rows/labels, not only card presence.

## 6. Reduce latency and explain progress — P2

**Evidence:** complete turns took 103–142 seconds on the tiny baseline graphs,
while the six available native execution-time statistics were 185–211 ms.

Measure route, plan, queue, native execution, analysis, and rendering separately.
Show useful stage progress in both CLI and browser. Present actual user-visible
elapsed time separately from the native algorithm statistic. Reduce repetitive
analyst output and prompt payloads, cache immutable operation/domain context, and
evaluate smaller reasoning/token budgets against the same correctness and
grounding tests. Reuse exact results only when input hashes and semantics match.

The explicit `/run` replay also exhausted all 3,072 completion tokens as reasoning
without producing an analyst answer. Detect this finish condition explicitly,
reserve enough budget for the structured answer, and evaluate a bounded retry
with a lower reasoning budget. A successful algorithm result must remain visible
when explanation fails. Accurate fallback labeling and a computed-output preview
have been added; reliable model output within the latency budget remains open.

Initial measurement targets for this host: first useful progress within 1 second,
a useful clarification within 10 seconds, and median complete small-graph answers
below 30 seconds. These are proposed acceptance targets to validate under load,
not current guarantees. Run repeat trials before attributing improvements to
GPU selection; the baseline points primarily to model/orchestration latency.

## 7. Turn feedback into a trustworthy improvement loop — P2

Keep the new histories as evidence. Add a review state and separate labels for
algorithm correctness, intent match, explanation grounding, clarity, input
friction, visualization accuracy, and latency. Preserve reviewer identity/source
and corrections to earlier automatic feedback. The overly strict largest-group
check demonstrates why raw automatic feedback is not training ground truth.

Expand beyond this small corpus with paraphrases, genuinely ambiguous questions,
unsupported requests, errors, empty/disconnected/directed graphs, weights, time
units, truncation, and multi-turn sessions. Include the remaining application
profiles before making a cross-domain quality claim. Keep numerical oracles,
semantic acceptance, and human usability judgments as separate measures.

Run a small task study with actual domain users who do not know graph algorithms:
can they upload their data, ask a useful question, understand the result, change
the question, and submit feedback without help? Record task completion and where
they get stuck. Set broader success thresholds from that study and repeat it
after the first five stages.

Only then consider fine-tuning using reviewed, explicitly labeled examples with
held-out workflows. Start by repairing the deterministic execution and rendering
contracts; a model update cannot enforce contracts the application does not have.

## Delivery order

Ship semantic execution gating first. Then fix follow-up intent and grounded
answers together, followed by domain intake and visualization contracts. Tune
latency after the correctness gates hold. Use the same saved application sessions,
new held-out paraphrases, and novice task study to assess each change. Preserve
each run and its feedback so improvements can be compared against this baseline.
