# Release validation and deployment

Browser regression checks found that waiting for backend discovery delayed the
entire data-workspace form. Backend-scoped drafts now initialize after the
loading controls have mounted; source actions remain disabled until discovery
finishes. Refreshing to another backend resets previews and loads only its
drafts. The corrected real Firefox suite passed all 19 draft/source/home/history
checks (release-browser.xml).

Admin storage inventory, direct downloads, cleanup previews and calculation
details now apply backend visibility too. Hidden work continues to protect
ordinary uploads from cleanup, without exposing its identifiers. Switching
back restores access without changing file or result bytes. The admin and
visibility regression suite passed 55 tests (release-admin-visibility.xml).

After a host zlib update, fresh native validation passed 170,599 oracle requests
across 23 completed reports and all 175 CPU contract tests. The native
implementation and compiled library are unchanged. Five historical GPU reports
remain attached to this binary because shared GPU memory prevented the remaining
reruns. The user explicitly authorized documenting those checks for later and
proceeding to production; see [DEFERRED_GPU_CHECKS.md](DEFERRED_GPU_CHECKS.md).
The evidence validator and existing cuMBE correctness quarantine remain intact.
The resulting catalog retains 82 CPU profiles and the existing GPU backend
coverage; this is not a claim that all GPU backends were freshly revalidated
against the updated dependency.

Application preflight passed 734 tests. The refreshed CPU workflow check passed
31 tests with one physical-GPU test skipped. Deployment uses the existing
testing/promote controller, with physical-GPU validation explicitly deferred;
application, CPU, frontend and migration gates remain enabled. The controller
records exact candidate verification and promotion outside the release checkout
in graphmine-data/environments/state/iu-neo4j-20261126 and last-promotion.json.
