# Sweep checkpoint — 2026-10-10

User scope: extend supported parameters, reject impossible plans, test all 38
executable choices using both GPUs, list research gaps. Also test newer outer
problems and newly collected implementations. No subagents, commit or publishing.
Preserve extensive pre-existing dirty work.

COMPLETED:
- Final binary SHA 9fbacd0bfc0a958ebb8326aa537a55363ff862029ec90aeab84cc90ff951f338.
- All 38 registered choices plus automatic clique selection were tested.
- results/acceptance: 15,204/15,204 distinct cases pass, using the complete
  final-binary run and explicit reruns below. This was not a clean single attempt.
- results/final: 15,145 pass / 59 MBE-GPU allocation failures at eight jobs/GPU.
  Four MBE processes exhausted fixed scratch memory on GPU 1. Original failures
  remain intact. No binary or algorithm change was made for this resource issue.
- results/mbe-resource-rerun: all 512 MBE cases pass with one worker on GPU 0.
- Final review found a harness command bug: string ID "0" became integer 0.
  The agent already preserved types. The corrected generator JSON-encodes IDs;
  all 368 PageRank/max-flow cases pass in results/vertex-id-rerun. Dangling-seed
  PPR is checked exactly; worst measured PPR absolute error is 6.3281344e-05.
- reconcile_resource_rerun.py verifies unchanged binary, workers, instructions,
  fixtures, complete rerun case sets and the recorded generator versions. It
  refuses to replace numerical errors with the resource rerun.
- CTest 24/24, agent 229/229, boundaries 51/51, CUDA memcheck 41/41 passed.
- Both offline collection validators passed after final annotations.
- coverage_matrix.py and report_results.py regenerated; report hashes, unique
  case counts, every registered choice, paths, and git diff --check verified.
- No required work remains within the agreed scope. Research failures and gaps
  are explicit; no claim that all 219 collected records passed runtime tests.

VERIFIED:
- CTest 24/24 after main repairs; updated KCGPU deep regression rebuilt/passed
  after its final table/storage repair.
- Agent suite 229 passed, evidence/graphmine-agent-final.log.
- Boundaries 51/51, including KCGPU K405/K514/K1001 triangles, degree/count
  rejection, CDS K20 k10, gMatch 16-vertex DFS.
- Sanitizer-final 41/41. K514 memcheck zero errors; GAMMA racecheck zero hazards.
- Logs copied into evidence/. Inner collection 70 contracts/219 records passes.
- Outer 37 contract/schema references pass; 91 records, 37 newer in folders21..37.
- Outer runtime 322/393 across15 modes. Historical ECL-Maxflow83/141,
  GAMMA-butterfly1/12 and KPAR0/2 fail. Others have explicit partial scopes,
  including signed solver smoke checks only. GPU4GST current outer source was
  rebuilt (it already had earlier repairs):2/2 path cases. Other22 newer
  records remain runtime gaps. Evidence in ../validation/parameter_expansion_outer.
- Research runtime19 records:3590/3743 pass; failures torch-cluster51 (ties),
  CuPy LOBPCG2 (recorded wheel/runtime combination), Ripser++100 missing
  essential H0 bars (finite bars pass). MVC both modes576/576 size checks,
  no witness. Model parity/gradients do not certify trained accuracy.
- HyperGCN singleton rejection is expected, separately named in results.
-55 artifact status files link scoped runtime_validation.json; their dated
  collection fields remain intact. Matrix:52 scoped passes,3 research failures,
  164 without runtime validation. No new research agent adapters were added.

REPAIRS: see README.md. GAMMA position comparison/warp barriers, temporal strict
timestamp ordering, KCGPU unused SM diagnostic removal, full1001-square Pascal
table, pivot array1001 and terminal depth slot. CMake patches generated copies.
Other extensions:KCGPU k10, GAMMA k7, CDS clique_order/bounded overflow retry,
PGGC resolution/objective refresh and no-contraction termination, max-clique singleton ties, gMatch shared memory,
planner/schema native ranges and restrictions, weighted BC rejection.

HISTORICAL RESULTS:
- results/full:first complete sweep15168/15204,36 failures in GAMMA/temporal.
- before-pggc-stagnation-fix:15203/15204, one Leiden timeout. All other checks
  passed. One stalled refinement reproduced in9/40 old-binary replays; repaired
  candidate60/60 passes, fixture and hashes in results/leiden-timeout-replay.
- boundaries-before-pggc-stagnation-fix51/51 and
  sanitizer-before-pggc-stagnation-fix41/41 retain the preceding binary results.
- before-kcgpu-memory-fix and before-kcgpu-pascal-fix:interrupted follow-ups.
- sanitizer:40/44, three host-only fixture selection issues and real invalid atomic.
- sanitizer-fixed precedes Pascal fix; use sanitizer-final for final evidence.
- kcgpu-pascal-boundary/before.json:K405 undercount before repair.

FINAL REPORTS:
RESULTS.md, README.md, research_gaps.md/json, parameter_profiles.json,
verification_summary.json, ../research_runtime/README.md, and the outer
workspace's validation/parameter_expansion_outer/README.md and inventory.json.
The matrix uses explicit repaired-profile paper mapping, avoiding double-counting
the two MBE records sharing a repo and handling KPAR's archive hash.

Most exec_command calls need require_escalated because bwrap loopback fails.
No auto-review rejection. No further permission is needed.
