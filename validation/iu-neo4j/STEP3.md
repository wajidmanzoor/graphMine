# Step 3: backend selection and retained local services

Completed on `feat/iu-neo4j-backends-20261126` after the user confirmed
"park local neo4j yes". All eight retained local units are inactive and disabled,
with zero RSS. The application changes have not yet been deployed to testing or
production; their running application services still use the previous code.

## Implemented behavior

- `agent/graphmine_agent/neo4j_backend.py` defines exactly `local` and
  `iu-remote`. Local registry endpoints must be explicit loopback Bolt addresses;
  IU is exactly `bolt://10.2.147.169:7689`, with `auth=None`.
- The active selection defaults to IU and is stored in
  `settings.data_root/neo4j_backend.json`, mode 0600. A file lock, temporary file,
  fsync and atomic replacement protect concurrent initialization and updates.
  Invalid selection files fail closed rather than resetting the selection.
- Application drivers, connector imports, monitoring, local loaders and the
  retained Browser implementation resolve their connections through
  `get_active_neo4j()`. Endpoint metadata reads are centralized in that module.
  Explicit local maintenance does not alter the application's selection.
- Old local mappings cannot silently become writes to IU. The old local HTTP
  connector remains supported; the IU connector uses direct Bolt and a managed
  read transaction. Discovery and health checks do not start services.
- `scripts/neo4j_local.sh status|park|activate` uses user systemd without sudo.
  Parking stops then disables every discovered local Neo4j unit, measures `ps`
  RSS before and after, and reports failures instead of claiming zero RAM.
- The unsuffixed `graphmine-neo4j.service` and Browser proxy are included. The
  already disabled OnTime partial store is preserved and stays excluded from
  activation. All installed units, stores, datasets and local loading code stay
  in place.
- Activation enables and starts the retained units, then waits for their Bolt
  listeners for up to 120 seconds. It does not treat Browser as a Bolt server.
  Failed activation attempts roll back the service state changes they introduced.
- The tracked Browser launcher is
  `deploy/database-workspace/neo4j-browser-proxy.py`. It is now installed at the
  existing private service path. The previous launcher remains alongside it as
  `neo4j-browser-proxy.pre-iu-backend.py`; the service stays stopped.
- Linked unit definitions are preserved as identical regular unit files before
  disabling. This prevents systemd from removing their registration and making
  subsequent activation unable to find them. Original external definitions are
  retained. The Browser unit exposed this case during the first real park and
  was restored as an identical disabled regular unit before final verification.

## Verification

Final results in `step3-tests.xml`: **301 passed, 1 deselected**, in 92.09 seconds.
After the linked-unit fix, all **23 resolver/lifecycle tests passed** in
`step3-linked-units-tests.xml`, including a new test that reproduces systemd's
removal of linked registrations and verifies later activation still works.
Coverage includes concurrent
selection writes, exact backend identity, credential redaction, symlink refusal,
inactive source rejection, driver credentials, direct Bolt connector reads,
Browser isolation, URI-read scanning, local service failures, repeated parking,
activation rollback, pool reuse, queries, schema inspection, synchronization,
database jobs, managed connections, monitoring and dataset deployment helpers.
Service lifecycle tests use mocks; they never park or activate the real services.

The broader admin CPU self-test was also investigated separately. Without the
deployment's analytics Python path it reports `backend_unavailable`; with that
path it reports missing or stale native CPU correctness evidence for `k-core`.
This also occurs with pre-Step-3 application code. That independent native
evidence issue is not bypassed or repaired here, and this single test is excluded
from the scoped final run. Its diagnostic reports remain under `/tmp`.

Reproduce the scoped run from the checkout root:

```sh
PYTHONPATH=agent .venv/bin/python -m pytest \
  agent/tests/test_neo4j_backend.py agent/tests/test_neo4j_local.py \
  agent/tests/test_database_connections.py agent/tests/test_database_pools.py \
  agent/tests/test_benchmark_mappings.py agent/tests/test_connectors.py \
  agent/tests/test_managed_connectors.py agent/tests/test_database_workspace.py \
  agent/tests/test_database_independent_sources.py \
  agent/tests/test_database_query_editor.py agent/tests/test_database_query_projection.py \
  agent/tests/test_database_schema.py agent/tests/test_database_sync.py \
  agent/tests/test_database_jobs.py agent/tests/test_database_mcp.py \
  agent/tests/test_database_datasets.py agent/tests/test_benchmark_datasets.py \
  agent/tests/test_admin_monitor.py deploy/neo4j-datasets/tests \
  -k 'not test_selftest_real_signin_calculation_and_result_with_question_provider_double' \
  -q --tb=short --junitxml=validation/iu-neo4j/step3-tests.xml
```

Additional checks: changed Python files parse, `bash -n scripts/neo4j_local.sh`,
`git diff --check`, and a read-only run of `scripts/neo4j_local.sh status`.
Changed files were scanned against the two supplied tunnel secret values with
no matches; credential-redaction tests use generated values.
`step3-prepark-status.json` records that read-only snapshot and `free -h`.
It is the earlier review snapshot; fresh parking measurements are below.
No remote SSH command or database write has been performed.

## Confirmed parking and memory

The user's Step 3 instruction says: "At the end of this step, after confirming
with me, run `scripts/neo4j_local.sh park`." The user supplied that separate
confirmation before the operation. Production had no database job records at
the pre-check.

Parking interrupts local Neo4j access used by the currently deployed
applications. Remote source integration and the later switching/visibility
steps are still pending; this code is not a completed testing/production rollout.

`step3-park-before.json`, `step3-park-output.txt` and `step3-park-after.json`
record fresh before/after measurements and the required systemctl commands.
The unsuffixed service is separately checked because the requested wildcard
does not include it. Final status covers eight units: all inactive, all disabled,
zero RSS. The intermediate result before restoring Browser's registration is
preserved in `step3-park-initial-after.json`. A repeated park succeeded with zero
additional RSS freed (`step3-park-idempotent.txt`).

| Measurement | Before | After |
| --- | --- | --- |
| Local service RSS measured inside park | 18,501,095,424 bytes (17.23 GiB) | 0 |
| `free -h`: total | 251 GiB | 251 GiB |
| `free -h`: used | 93 GiB | 76 GiB |
| `free -h`: free | 94 GiB | 112 GiB |
| `free -h`: available | 157 GiB | 174 GiB |
| `free -h`: swap used | 14 MiB | 14 MiB |

The production data root's private selection file is initialized to `iu-remote`.
This is persisted configuration for the new implementation, not a claim that
the previous running application version has already switched to IU.
