# Runnable problems and the shared backend policy

The executable hierarchy is **Family → Runnable Problem → Backend**. Every
previous runnable identifier keeps its spelling. `catalog/problems.json` maps
each runnable problem directly to one family; native cards own its parameter,
input, output and backend contract. `catalog/topics.json` contains documentation
text only. Topics can explain distinctions such as degree, betweenness and
PageRank without becoming an executable choice.

The planner makes a family call followed by a route call. The route sees all
eligible problems in that family and documentation hints. It ranks up to three
calculations; multiple problems within a calculation are required workflow
steps. Every calculation must include a problem from the selected family.
Cross-family dependencies need explicit question evidence. An unsupported route
can reject one family and retry once. Normal-mode cards use this ranking without
another sampling call, and execution waits for the user's calculation choice.

Native protocol v2 and all new workflow steps write `problem`. Workflow readers
and the native request boundary accept the old `operation` key and reject
conflicting dual keys. Canonical validation and workflow hashes use the new key.
Existing runnable IDs, mathematical definitions and backend contracts remain
unchanged. The native protocol version rejects accidentally loading an old
library with a new binding.

The development redesign removes the old linear backend selectors and policies.
Development backend data is isolated from the shared production stores. The new
shared neural policy will have one 64-unit ReLU layer, one 32-unit ReLU layer,
and one backend-score output layer. Unavailable models use native feasible
backend ordering. Memory admission remains deterministic, with no auxiliary
learned memory model. The remainder of the policy implementation, training,
logging and evaluation controls is documented with Phase 2.

Validation reports distinguish deterministic contract tests from live routing
accuracy. The initial live routing attempt could not reach the model service;
its failures are infrastructure failures and do not establish a calculation
accuracy baseline. GPU admission requires new matching correctness evidence.

Phase 1 verification (CPU build, 2026-11-24): 53 native CTest cases passed;
all 82 runnable contracts have regenerated CPU correctness evidence (10 oracle
reports). The native binding suite passed 52 tests and skipped 96 tests requiring
optional GPU builds. Catalog/taxonomy checks passed 85 tests; option/taxonomy
checks passed 67. Routing/lane/parameter integration passed 111 tests (including
the two dependent-workflow tests rerun after updating model-call assertions),
with two GPU-only skips. Three migration tests verify legacy reads, canonical
hashing, conflicting-key rejection, and the native request alias. Frontend API
contracts regenerate and TypeScript checks pass. These are deterministic tests,
not measured LLM accuracy. Live routing baseline: 42 cases could not reach the
configured model service; correct-calculation and clarification rates are unknown.
