# Standard graph views: Step 3 progress

Step 3 is in progress in `devlopment`. Production is unchanged. This file will
record the CPU-family migrations and their independent commit gates.

## Prerequisite extensions

The user approved two additions needed to preserve existing CPU behavior:

- COO record mode, retaining original edge orientation, identity and order.
- Exact-rational weights, preserving parallel sums that cannot fit f64 or int64.

Both are implemented in the shared factory. Existing defaults remain unchanged.
New tests cover record order, undirected parallel records, loops, incompatible
specs, rational min/max/sum, binary64 fractions, sums beyond binary64 range,
negative loop validation, parser precision restrictions and byte determinism.

The first checkpoint is `validation/graph_views/step3/00-view-extensions/`.
It passes 52 runtime CTests, 238 Python tests, the existing 129,073-request C++
oracle replay and all 82 CPU capability admissions. Existing normalizer byte
goldens are replayed against the Step 2 corpus. No CPU family is declared migrated
by this prerequisite commit.

The checkpoint runner initially resolved a virtualenv interpreter symlink to
system Python. That caused the first agent capability check to fail. It now
retains the virtualenv path, and all three agent checks pass. The initial output
is preserved losslessly under the checkpoint's `diagnostics/` directory.

`tools/validate_graph_view_checkpoint.py` runs the existing gates and refreshes
execution evidence for each family commit. Algorithm-specific input goldens are
retained alongside those reports.

## Traversal

Breadth-first search now reads V1 CSR directly. Its immutable declaration lives
beside the CPU adapter and specifies preserved direction, dropped loops, first
parallel-edge collapse, omitted weights and sorted neighbors. Source selection,
predecessor tie-breaking, depth limits and independent/nearest-source modes are
unchanged. The existing cuGraph path remains for Step 4.

`view_profiles.*` exposes the same declarations used by adapters for later
registry generation. The shared acquisition helper records the actual profile,
resolved spec and normalization in provenance, preserving candidate admission
on fresh and cached views. It performs no normalization itself.

Checkpoint `01-traversal` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Its byte golden compares the actual declared view with the frozen
old adjacency builder on every Step 2 corpus graph, including warm-cache costs.
The declaration test also checks the spec reported by real BFS requests.
