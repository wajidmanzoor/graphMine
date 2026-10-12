# Planner recovery — 2026-10-11

All four failures in the original 16/20 acceptance run are repaired, and the
final replay passes 20/20. The affected tasks were:
minimum vertex cover, weighted shortest paths, neighbor lookup, and a dependent
subgraph/triangle workflow. The original suite and scores are preserved in
`validation/native_final`.

## Changes

- Family and operation decisions use mutually exclusive status branches.
  Selected decisions require a nonempty selection; reroutes require destination
  families; clarification and unsupported decisions cannot select operations.
- Generated references explicitly choose their source: an uploaded `input` or
  an earlier `step`. Step references use zero-based indices. Positional JSON
  schemas prevent self-references, forward references and missing steps during
  decoding. The server assigns IDs and converts these references to the existing
  public workflow format.
- Planning retains the selection stage's explanation as fallible context and
  explicitly preserves the requested input scope. A calculation on a derived
  graph must consume its graph port. An independent calculation on the original
  graph must keep its uploaded input.
- Actual-input validation, typed ports, vertex namespaces, completeness checks,
  approval requirements and the bounded repair path still apply. No reference
  is guessed or silently rewritten to another data source.

## Verification

| Check | Result |
| --- | --- |
| Planner contracts, transport and native execution | 58 passed (`planning-source-choice.xml`) |
| Final application, workflow and MCP suite | 81 passed, 2 physical-GPU checks skipped (`application-final-v2.xml`) |
| Original twenty cases with the final planner | 20/20 passed (`original-twenty-final.json`) |
| Thirteen fresh cases with the final planner | 12/13 strict passes; all 13 returned correct results and dependencies; one equivalent-default grading mismatch (`fresh-thirteen.json`) |
| Independent answers for the thirteen fresh cases | 13 passed (`fresh-oracles-v3.json`) |

The real-model runs use the pinned Qwen/Qwen3.8-27B-FP8 revision
`017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`, medium reasoning, a 1,536-token
thinking budget within 3,072 completion tokens, temperature 0 and seed 0.
They plan and execute through the actual application service and native worker
in temporary workspaces. No expected answers enter the planning request, and
reviewed-example retrieval is excluded by the evaluation marker. Both final
model runs and the final application suite confirm unchanged source files.

The fresh suite was frozen before its first model call. It includes directed
and undirected weighted paths, unreachable vertices, fractional and zero costs,
incoming and outgoing neighbor lookups, distinct vertex-cover graph shapes,
three derived graphs, and a control requiring an independent calculation on
the original graph. Small exhaustive vertex subsets, path relaxation, adjacency
sets and triangle enumeration supply independent answers. The native core
cross-checks those answers before model evaluation.

The strict fresh-case grader flags `fresh_neighbors_2` because it requires an
explicit effective direction of `both`, whereas the model uses the documented
default `out`. The graph is undirected and the returned neighbors are exactly
correct. The separate [direction audit](neighbor-direction-audit.json) verifies
that default, `out`, `in` and `both` produce the same complete set matching the
independent adjacency oracle. This is an overstrict parameter requirement, not
an incorrect neighbor result. The original strict grade remains preserved.

## Diagnostic history

`baseline-four.json` replays the unchanged application from commit `0141939a`:
1/4 passed. This differs from the saved acceptance run, in which all four
failed, so a single seeded model run is not treated as a determinism guarantee.

The first repair reached 2/4 (`repaired-four.json`). The positional grammar
reached 3/4 (`repaired-four-v2.json`), but the dependent case still used the
original graph. Its numeric answer happened to match; the explicit dependency
check correctly rejected it. Additional scope instructions alone did not fix
that (`dependent-scope.json`). Explicitly tagged source choices then passed the
dependent case (`dependent-source-choice.json`).

`planning-first.xml` retains an initial test-fixture error: its intentionally
invalid reference used a port outside the selected operation's schema, so it
failed before reaching the intended repair check. The corrected routing/repair
checks passed 19/19 in `decision-and-repair.xml`.

`application.xml` is a superseded run: changing sources during the run correctly
failed its provenance assertion, and three MCP checks exceeded their polling
window while using the larger GPU-linked runtime. It is not final acceptance
evidence. The final application run uses the independently verified CPU build;
real-model execution uses the same GPU-linked build on CPU as the baseline.
The subsequent `application-final-v2.xml` run also isolates the negative test
cases so duplicate arguments and unknown ports exercise their intended checks.
Two earlier twelve-case freezes were never exposed to the model; v3 adds the
independent-scope control. Interrupted partial outputs are not scored as passes.

## Reproduction and limits

Configure the pinned model, verified native runtime and worker environment as
in `docs/ANALYTICS_WORKSPACE.md`, then run:

```bash
.venv/bin/python tools/evaluate_planner_recovery.py \
  --suite validation/native_final/heldout-suite.json \
  --output /tmp/graphmine-original-regression.json \
  --scope 'Regression replay of previously exposed cases'

.venv/bin/python tools/evaluate_planner_recovery.py \
  --suite validation/planner_recovery_20261011/fresh-suite-v3.json \
  --output /tmp/graphmine-targeted-regression.json \
  --scope 'Repeat of the targeted generalization suite; now regression data'
```

Reports record exact source hashes, model settings, suite hashes, generated
decisions, actual native results and whether source files stayed unchanged.
The original twenty questions are regression data. The thirteen new questions
are assistant-authored variations of the known failure categories, not a public
benchmark or human evaluation. These checks do not establish general unattended
planning reliability or a fine-tuning gain.
