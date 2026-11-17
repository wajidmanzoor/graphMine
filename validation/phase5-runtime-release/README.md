# Grounded analytics native runtime release

Built on 2026-11-17 from the Phase 0–5 native sources, retaining all 82 CPU
operations and all 59 GPU profiles across 36 operations. The optional biclique
partition contract is included. `report.json` records the exact source commit,
implementation and binary hashes; `admission.json` records the application gate.

Validation passed: 129,073 CPU oracle requests, 44,884 on each GPU, 53 C++ tests,
134 CPU completion tests, 34 CPU original-backend tests, 34 GPU 1 original-backend
tests, 33 GPU 0 original-backend tests, and 140 Python binding tests. Source and
binary inventories accompany the reports used by the execution gate. These are
finite checks, not a proof for every input.

The existing GPU 0 restriction for `mbe-gpu` is retained: its fixed 10.64 GiB
scratch cannot fit beside the loaded production model. The backend passed on
GPU 1 and is admitted only there. No model or database service was restarted.

Files prefixed `diagnostic-` retain launch-configuration failures. The final
runs use the analytics interpreter with NetworkX, the required build variables,
and a genuinely CPU-only runtime for the binding test that rejects GPU upload
on CPU-only builds. No native code was changed to resolve those launch errors.

`runtime-build-configuration.json` records dependencies and the build command.
Keep the earlier pinned Kokkos installation and research workers available;
the new runtime reuses them without modifying them.
