# Application-language evaluation — 2026-10-02

This opening report preserves the original baseline. The implementation replay
and remaining issues are documented in the final section below.

The tested algorithms usually returned the expected small-graph results. The
larger problems are between the user's question and the runnable plan, and
between the computed result and the explanation/visualization. A successful
job is not enough to call the application usable by a domain expert.

## What was actually exercised

The baseline used the running **Qwen/Qwen3.8-27B-FP8** endpoint and the real
GraphMine native binary on the configured compute GPU. It ran through the same
API, planner, validator, worker, analyst, and terminal client used by the CLI.
The existing browser server was not restarted or used as the test database.
No keyword fallback or fake binary was used for these application runs.

There are **seven synthetic graphs across seven domains**, eleven workflows,
and thirteen baseline questions. A separate follow-up probe resumes the actual
collaboration session and asks for a different measure. An explicit `/run`
replay checks the CLI workaround. These small graphs test correctness and
usability; they do not establish scale, production readiness, or broad model
accuracy. This was assistant review, not a study with recruited end users.

In total, **15 live user turns** were exercised and **15 feedback records** were
saved. The two supplementary probes and their IDs are included in the same
machine-readable report as the baseline.

The fixtures contain 4–11 entities. Expected answers were written before the
runs and checked with independent, exhaustive Python oracles for groups,
pruning, shortest-path mediation, directed delivery costs, and temporal patterns.
The two-circle community result is an expected result for this synthetic graph,
not a claim of global optimality for community detection.

Evidence:

- [Application questions and expected behavior](applications/cases.json),
  [graphs](applications/graphs), and the
  [independent fixture checks](../tests/test_application_fixtures.py).
- [Machine-readable baseline and reviewer feedback](reports/application-usability-2026-10-02.json).
- [Authored review observations](applications/baseline_review.json) and
  [additional follow-up expectation](applications/followup_probe.json).
- Full local history under
  [the isolated evaluation runtime](../../.graphmine-usability/application-baseline/runtime/history),
  including original graphs, prompts, provider responses, plans, commands,
  outputs, interpretation revisions, visualization specifications, and feedback.
  Each case in the machine-readable report gives its exact session/history path.

## Observed behavior

| Application request | Actual behavior | Usability assessment |
| --- | --- | --- |
| Fraud: list mutually connected account groups of at least three | Returned the two expected groups | Correct groups; invented claims about other connections and emitted an internal placeholder |
| Biology: largest pairwise interacting protein group | Returned TP53, MDM2, ATM, CHEK2; size 4, optimal | Correct answer; mixed dataset evidence with unsourced biological background |
| Biology: repeatedly remove proteins with fewer than three partners | Returned the same four expected survivors | Correct computation; promised a filtered table the browser does not implement |
| Infrastructure: rank devices by shortest-route mediation | Ranked gateway-01 first, then east-router/west-router | Useful answer; correctly distinguished structural importance from measured traffic |
| Retail: customers sharing at least two purchased products | Responded only “The plan needs additional input: left_partition” | A domain user cannot act on this without learning implementation terminology |
| Retail: same question after uploading the customer list | Returned Alice/Bob × Coffee/Tea and Bob/Carol × Coffee/Cocoa | Correct bundles; all model-selected views were discarded and replaced by defaults |
| Collaboration: count and list fully collaborating trios | Counted all five expected trios | Incorrectly claimed the two groups were disconnected; Divya–Eli is an explicit bridge |
| Collaboration follow-up: show the largest group | Correctly inferred Ava/Ben/Chen/Divya from the existing complete trio result | Reuse is valid here; the promised view still references the old trios and unsupported filters |
| Collaboration: divide coworkers into circles | Returned the expected four-person and three-person circles | Useful partition; overstated “meaningful” modularity and suggested unavailable controls |
| Transport: fastest directed, weighted delivery route | Declined because the operation is unavailable | Appropriate refusal; no nearby algorithm was substituted |
| Security: ordered A→B, B→C, A→C within 60 seconds | Returned one correct instance, mail/app/db, events 1/2/3 | Correct match; explanation miscounted unused edges and confused native runtime with user latency |
| Security: ordered A→B→C→D through four hosts | Planner described it as unsupported, but a triangle job still ran and returned 1 | Critical semantic gating failure; the graph actually has two requested chains |
| Fraud: “Which accounts should I investigate first?” | Asked for a formal graph problem/criteria | Safely avoided guessing, but clarification still requires algorithm vocabulary |
| Follow-up: rank coworkers by shortest-route mediation | Said a different computation was needed, then told the user to request `betweenness-centrality` | Did not carry out an already clear application request; the keyword-based follow-up gate prevented execution |

The baseline's mechanical contract checks passed **11/13** questions. That is
not a usability score. One failure required a fresh maximum-clique job even
though the answer could be correctly derived from the complete prior result;
the manual review explicitly corrects that overly strict expectation. The other
failure is the real unsupported-pattern execution bug. Several mechanically
passing answers still have explanation or interface defects.

The follow-up probe avoids that ambiguity: the previous triangle result does
not identify which endpoints connect the groups or provide shortest-path
scores. The system recognized the missing computation but did not launch it.
The independently expected ranking is Divya = 18, Eli = 16, everyone else = 0,
using the native ordered-pair convention.

The explicit `/run` replay did compute that exact ranking. Its analyst call then
exhausted all 3,072 completion tokens on reasoning and returned no answer
(`finish_reason=length`). The original fallback claimed inference was disabled
even though the model was running. The CLI now labels interpretation fallbacks,
removes that misleading claim, and shows a bounded computed output/ranking if
the interpretation fails. An injected-failure regression test verifies this
handling; the archived live response is preserved as it actually appeared.

## Findings that matter most

**1. A refusal in prose does not prevent execution.** In the four-host security
query, the plan's rationale says that the topology is unsupported and that no
plan is produced for execution. However, the same object contains the Everest
backend, a 60-second window, requested instances, and an empty `missing_inputs`
list. The validator accepts those fields and the worker executes. The analyst
then warns that the result is for a different question. The correct fix is a
typed non-executable outcome and semantic validation before queueing, not a
more forceful instruction to the analyst.

**2. The follow-up gate requires particular verbs.** Both initial routing and
the analyst's request for another execution depend on a small regular
expression containing words such as `run` and `compute`. “Which coworkers…?
Rank…” is a clear request to perform an analysis, but is sent only to the
analyst. `/run` provides an explicit CLI control while that behavior is repaired.

**3. Evidence paths do not establish that claims are true.** The evidence
sanitizer checks that a path exists and replaces its value with the actual data;
it does not establish that the adjacent claim follows from that data. Examples
include inferring disconnectedness from disjoint group membership, inferring
path absence from graph density, and treating ignored attributes as absent.
The temporal explanation says eight of nine edges were unused despite returning
a three-edge instance; the correct number is six.

**4. Most model visualization choices were silently lost.** In **8 of the 10
baseline interpretations**, every proposed view was rejected. The model used
references such as `result.output.cliques` or `result_summary.output...`, while
the renderer/validator expects paths into the raw payload such as
`output.cliques`. Default views made the result appear to have a visualization,
masking the loss of the model's selection.

Separately, static review of `static/app.js` shows that specification filters
are not applied, and a network built from a list of groups initially selects
the first group. Therefore the promise to show a filtered four-protein panel or
a derived four-person group is not fulfilled by that adapter. These renderer
findings are based on source inspection and saved specifications; this report
does not claim a browser rendering or screenshot validation pass.

**5. Domain information stops at the upload boundary.** The retail graph labels
vertices as customers/products. Those types are saved in the original and
canonical graph, but the model receives aggregate graph statistics rather than
the typed entities. The resulting `left_partition` request exposes a technical
file requirement. Similarly, an ambiguous investigation question is met with
algorithm names instead of a choice between understandable investigation goals.

**6. User latency is dominated by model calls.** The nine baseline jobs that
executed took **103–142 seconds per complete user turn**, with a median of about
**117 seconds**. The six outputs exposing native `end_to_end_ms` reported only
about **185–211 ms**. For example, the supported security question took 113
seconds while the analyst described its roughly 203 ms native statistic as
interactive end-to-end runtime. Route, plan, and analyst call times are recorded
separately in the raw history. These are single-run observations on tiny graphs,
not a load-test result.

## Feedback and limitations

Automated contract failures and eleven additional reviewer observations were
saved through the same feedback persistence used by `/feedback`. They are
marked `assistant_evaluation`, carry turn/job/result references, and do not enter
the model's conversation. The supplementary probe also saves its failure as
feedback. The correction to the overly strict largest-group check is retained
alongside its original automatic feedback so it cannot silently become a bad
training label.

The baseline pass did not recruit domain users, test large graphs, measure concurrent
load, or add new native algorithms. The recorded shortcomings remain open
except for the CLI/history infrastructure fixes described in the
[CLI guide](../CLI.md). The next implementation sequence and acceptance criteria
are in the [improvement plan](../IMPROVEMENT_PLAN.md).

## Domain-first implementation replay — 2026-10-03 UTC

The final replay passed **16/16 mechanical contract checks** across 12 workflows,
eight small synthetic graphs and seven domains, using the real local Qwen model
and native GraphMine execution. The source/contract/fixture hashes, actual
questions, responses, plans, timings and result checks are in
[the complete machine-readable run](reports/domain-first-2026-10-03.json).
The new [case set](applications/domain_first_cases.json) retains the original
baseline separately and adds attributed workplace exploration.

This is a development regression suite, **not a held-out accuracy benchmark**:
these cases were also used to diagnose and repair defects during implementation.
Passing them does not establish general application understanding or novice
usability. No external teacher or fine-tuning run was used.

| Capability checked | Final observed behavior |
| --- | --- |
| Four-host event chain / directed weighted delivery route | Typed unsupported replies and zero jobs; no substituted computation |
| Supported three-host sequence | Correct instance, original event IDs/timestamps, and exact unused-event count |
| Typed customer/product data | Both expected bundles without a manually supplied partition file; also works after an explicit file upload |
| Largest collaboration group follow-up | A fresh maximum-group result and views for that answer |
| Communities plus connectors in one question | Two validated computations; combined named groups, bridge connection and ranking |
| “Only collaborations from 2026” | Projection contains nine edges, original source remains unchanged, names/departments retained |
| Subsequent connector ranking | Retains the 2026 constraint; all seven zero scores are explicitly non-discriminating |
| Ambiguous investigation priority | Asks for application-level investigative intent before execution |

The 13 turns that ran computations took **19.2–39.6 seconds**, median **23.9
seconds**, including planning and interpretation. All 13 final interpretations
used the configured model, not a fallback. The three non-executing replies took
9.5–13.6 seconds. This profile uses no planner reasoning and deterministic
fact/view selection with reasoning disabled; the original baseline used a
different reasoning profile. These single-host small-graph observations are not
a load test or proof of any one change's causal speedup. Existing `.env` values
and running services were not overwritten; see the [CLI guide](../CLI.md) for
reproducing the tested profile.

Development replays were intentionally preserved, including failed attempts:

- First domain-first replay: 13/16 checks. It exposed an unknown-problem refusal
  normalization bug and missing attribute context in follow-up classification.
- Subsequent focused replays exposed whitespace-only model continuations,
  multi-part requests mislabeled as ambiguity, invented auxiliary input keys,
  and unavailable backend choices. Their failed turns and feedback remain under
  `.graphmine-domain-evaluation/live*`; compact reports are alongside those stores.
- The final implementation uses one bounded malformed-output repair attempt,
  operation-specific parameter/output/file schemas, server-owned backend
  selection, and semantic checks independent of a prose rationale.

### Browser and regression verification

**78 Python tests** and **2 full browser scenarios** passed, alongside lint,
JavaScript syntax checks and schema regeneration. Tests cover exact original-ID
joins (including integer versus string IDs), selected records beyond the first
500 uploaded vertices, attribute filtering, timestamp conversion exactly once,
explicit direction-projection consent, safe refusal, combined workflows, CSV
mapping, history/feedback and private offline exports.

The browser scenarios exercise upload, chat, computation, follow-up, selectable
groups, attribute color controls, click-through original records, finite graph
positions, and opening the exported report with no HTTP resources. One uses
650 uploaded vertices while the answer contains seven selected entities; this
checks selection correctness, not large-graph performance. Native execution and
LLM calls are test doubles in these browser scenarios; the separate replay above
uses the real model and native binary.

An additional Firefox inspection opened the real collaboration replay as an
offline report. It exposed excessive spacing around compound groups. After the
replay, the frontend-only layout was changed to compact group placement; browser
tests were rerun and the same real result was re-exported and inspected. All
seven names and ten source connections remain, labels are approximately 15px at
the tested viewport, and there are no remote resource requests. The original
replay source hashes and saved reports remain unchanged; its `app.js` hash
therefore predates this final rendering-only correction. Local screenshots and
the corrected report are under `.graphmine-domain-evaluation/browser/`.

### Remaining issues and saved feedback

Five assistant-review observations were saved through the same feedback storage,
linked to their exact turns/jobs/results. See
[the authored review](applications/domain_first_review.json); the report with
generated feedback IDs is `.graphmine-domain-evaluation/domain-first-reviewed.json`.
They remain separate from model conversation and are not automatically training
labels:

- Some follow-up suggestions still expose algorithm names or require annotations
  and dependent transformations not available in the current workflow.
- Generic tables show internal field names instead of polished customer/product
  columns. The retail model selected tables rather than the available two-sided
  network in this replay.
- The combined workplace explanation spends two facts on Divya's score while
  Eli's score is available in the ranking view but omitted from the short text.
- A zero-score ranking suggests inspecting a returned group without clearly
  linking to an earlier group result.
- Domain caveats and assumptions can still be awkward or unnecessarily technical.

The deterministic findings prevent the earlier false connectivity/unused-event
claims; they do not make model-proposed implications or suggestions verified.
Memory-bounded answer materialization, large graphs, repeated held-out trials,
concurrency and a study with domain users remain open. The next sequence,
including oracle-checked synthetic data and teacher-generated candidates rather
than manually authored training examples, is in the updated
[improvement plan](../IMPROVEMENT_PLAN.md).

## Next-phase synthetic learning baseline — 2026-10-03 UTC

The API was gracefully restarted, preserving its five sessions, five files,
five jobs and three results. Online SQLite backups were saved before each
restart, and the model server remained running. The final restart also loaded
the backend correctness exclusions described below.

The seeded corpus generates 24 attributed graphs and 114 domain-language
questions across six domains and seven operations. Training, validation and
test use distinct topology families with isomorphism checks, not random splits
of paraphrases of the same graph. Full artifacts are local under
`.graphmine-learning/`; the compact, hash-linked evidence is
[synthetic-learning-2026-10-03.json](reports/synthetic-learning-2026-10-03.json).

| Check | Observed result |
| --- | --- |
| Initial native reference audit | 113/114 checks; one false maximum-clique certification |
| Audit after that exclusion | 113/114 checks; another maximum-clique backend aborted |
| Final native reference audit | 84/84 executable checks plus 30/30 separately marked template/refusal checks |
| Held-out real-agent replay | 35/38 strict contracts; 28/28 computed answers checked; no jobs on all ten non-executable requests |
| Candidate export | 54 training + 22 validation RouteDecision rows; no test rows |
| Local paraphrase generation | Five calls, 13 proposals; all quarantined and ineligible for training |
| Regression verification | 104 Python tests, 2 browser scenarios, 18 enabled native tests passed; 3 unavailable native community backends disabled |

The first audit found CUDA-MS returning a three-protein group with `optimal: true`
and `upper_bound: 3`, although exhaustive enumeration and two alternative GPU
solvers found a four-protein group. Three direct repetitions reproduced this.
The library's use of a relaxation-mask size as a certified global bound was
removed, and a native regression now tests the counterexample. A subsequent
audit found Maximum-Clique-on-GPU aborting with exit -6 on an eight-device
cycle-with-chord graph; a direct replay reproduced that too. The abort's root
cause remains open. Both backends are excluded from agent selection, including
explicit selections and stale benchmark policies. The final corpus audit uses
GPUMaximumClique for maximum-clique requests and passes. Native failures also
have linked assistant-evaluation feedback; the original failed reports remain.

The live run used the unchanged local Qwen model and the documented lower-latency
planning profile. Its median turn took 20.75 seconds (range 8.75–26.00). Three
questions requesting monetary-cost shortest routes—workplace, accounts, and
devices—were safely stopped, but used `planning_status: needs_information`
instead of the expected `unsupported`. Their prose correctly states that the
native operation cannot use costs and that cost data is absent. The strict
status checks remain failed, with saved feedback; these are not unsafe
computations or evidence of incorrect numerical answers. The protein version
used the expected status. Clarifications for vague priorities and unsupported
four-host sequences behaved as expected in this one run.

Source boundary: the isolated live replay began after the first exclusion and
before the later cycle-crash exclusion. Its four maximum-clique requests used
Maximum-Clique-on-GPU and matched the reference answers. The final native sweep
independently rechecked all examples with the final GPUMaximumClique selection.
The compact report retains source hashes; the two measurements are not presented
as one identical runtime. The model and prompts were not changed in response to
the held-out status mismatches. The browser tests use doubles; the 38-question
replay uses the actual model and native binary.

Limits: these are small generated graphs and single-turn, template-derived
questions, not representative production accuracy or a domain-user study.
Community checks verify partition coverage and reported modularity, not global
optimality. Visualization checks in this corpus only require an answer view;
the separate browser scenarios cover interactions. Generated wording still
needs independent semantic review: some local-model proposals use “maximal” or
“largest possible,” which can undermine novice usability or change the request.
Neither these proposals nor failed traces are accepted automatically as training
labels. No external teacher calls, data uploads, or weight updates occurred.
