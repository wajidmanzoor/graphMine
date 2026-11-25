# Six-hour execution and unlimited input bytes

Development now configures backend attempts, workflows and account calculations
for 21,600 seconds (six hours). A shorter explicit step deadline still applies.
Benchmark timings no longer shorten backend attempts. Upload, account-upload and
combined workflow input-byte caps are disabled. The native JSON parser, C API,
CLI, workflow worker and cuDF file reader have no fixed 64 MiB byte ceiling.
Memory admission, account storage quotas and configured source row budgets remain.

The private development configuration points to the verified development build.
Production/testing configuration is unchanged. Development web services were
already stopped; these settings apply when they next start. Actual supervised
workers ran successfully using this configuration in the checks below.

## Verification

| Check | Result |
| --- | --- |
| Agent regression coverage | 1958 passed, 55 optional checks skipped |
| Native CTest | 61 passed; 15 optional backend tests disabled |
| Independent native CPU oracle requests | 129,076 passed |
| Native Python contract tests | 178 passed |
| Enabled GPU backend oracles | 2 passed |
| Requests above 64 MiB through C API and CLI | 2 passed |
| Previously failing isolated GPU case | 20 consecutive passes |
| Frontend | 31 tests, typecheck, API contracts and JS syntax passed |
| Real development NN execution | Count and limited enumeration passed; six-hour deadline logged |

Agent coverage was completed in disjoint batches of 423, 1,041 and 494 passing
tests. Diagnostic test runs retain GPU-lease contention and missing test-fixture
environment variables; every affected case passed after correcting the setup.
`tests.json` identifies the reports. Benchmarks and scheduler tests run serially.

The existing development build cache initially used CUDA target 70, while the
previous verified build used 89-real. Isolated ToT calls on the former target
intermittently failed with `radix_sort` / `cudaErrorInvalidValue`. The corrected
build restores 89-real for ToT and WeTriC. All diagnostic measurements remain in
the development run store; `diagnostic-build.json` records them. `build.json`
records the final build options and binary fingerprint.

## Shared-policy refresh

Model `20261125t070655.721137z-7f48923fc36a` uses schema 2 with no parameter features.
There are 112 raw features and 9 varying features;
the dropped features are listed in `shared-policy.json`. Its native implementation
hash is `58fceaaa38721068dc12b91b1f349390db63ac379442c4e5cb0befca24af885b`.

The refreshed paired dataset has 192 completed measurements on 16 synthetic
graphs, count/enumeration settings, and three eligible backends. The shared host
was measured without added CPU load and with two added CPU workers. Entire graphs
were held out: 3 graphs form the test partition.

| Held-out NN policy metric | Value |
| --- | ---: |
| Mean selected/oracle runtime ratio | 1.007157 |
| Median | 1.000000 |
| p90 | 1.000000 |
| p99 | 1.000000 |
| Failure rate | 0.000000 |
| Timeout rate | 0.000000 |

This refresh covers triangle counting/listing with K=3. Development retains the
requested live `bandit` setting. `live-count.json` and `live-enumerate.json` show
the selected backend, exact probability, unchanged parameter-independent NN
context and actual attempt deadline. Verification rows are evaluation-only.
