# Agent catalog expansion verification

The packaged agent now catalogs 37 problems, exposes 18 operations across 17
families, and lists the other 20 families with their availability limits. The
compiled version-1.0.0 CLI reports 31 backend choices. Existing agent correctness
exclusions remain active.

| Verification | Result | Evidence |
|---|---|---|
| Agent regression suite | 337/337 passed | [Log](agent-tests.log) |
| Public native API correctness/rejection replay | 99/99 passed | [Detailed cases](../gpu_correctness_expansion/results/library_expansion.json) |
| Packaged native CTest, CUDA enabled | 22/22 passed | [Log](native-ctest.log) |
| CUDA-disabled build and active smoke tests | 5/5 passed | [Log](cpu-only-tests.log) |
| Root facade after worker-group synchronization | 1/1 passed | [Log](root-facade-test.log) |
| Catalog regeneration and original 13 operation contracts | Consistent; originals preserved | [Machine-readable report](results.json) |
| Vendored sources and license paths | Pinned hashes match; paths exist | [Provenance](../../library/src/backends/expansion/upstream/PROVENANCE.json) |

The agent suite includes 42 expansion checks. Five execute the real native
profiles through planning, API submission and result handling; a separate test
verifies that cancellation terminates the native worker process. Other checks
cover typed terminal IDs, missing data, capacities/costs, graph/profile limits,
unknown parameters, routing-contract selection and grounded answers.

The local base-model endpoint was unavailable. No live LLM routing accuracy is
claimed. A separate 66-case evaluation-only holdout covers every new problem and
the supported/unsupported profile boundary. The legacy routing prompt fingerprint
is preserved. No model training, adapter-weight changes or deployment was performed.

Historical artifact screens are preserved separately; their partial passes and
failures were not reclassified by these integration tests. Generated code-reference
pages remain the original release snapshot; current profiles and API usage are
covered in the updated guides and the source-reference generator supports the
new vendored paths.

See [the integration guide](../../docs/ALGORITHM_EXPANSION.md) for reproduction,
all 17 new-family dispositions, exact profile limits and training implications.
