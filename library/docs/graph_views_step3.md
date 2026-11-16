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
