# Step 9: verification and operator check

scripts/check_iu_neo4j.py checks network reachability through wg-iu, Bolt on
7689 and RETURN 1 in a managed read transaction. Its default path sends no SSH
command; --wake explicitly opts into the existing AUTOWAKE policy. Failures
never expose driver exceptions, remote output or secrets. The URI-read scanning
test now includes scripts as well as application and deployment modules.

The focused suite passed 93 tests (step9-tests.xml); the expanded scanner also
passed independently. The local release gate discovers every new Neo4j suite;
its five contract checks pass (step9-gate.xml). The focused coverage includes exact fake SSH commands, pinned host keys,
password stdin and log redaction, process/file locks, timeouts and back-off,
idle ownership/activity, VPN failures, auth=None and exact network allowlisting,
local park/activate, both switch directions, rollback, force cancellation,
administrator authorization/audits and backend visibility. Step 7's broader
439-pass regression and 35 frontend checks remain recorded separately.

Live verification (step9-live.json) succeeded without wake or SSH:
wg-iu reachable, direct Bolt 7689 connected, authentication none, RETURN 1 = 1.
All eight local units remain inactive and disabled with zero RSS
(step9-local.json). Step 3 measured 18,501,095,424 bytes of RSS freed;
free -h changed from 93 GiB used / 94 GiB free / 157 GiB available to
76 GiB used / 112 GiB free / 174 GiB available immediately after parking.

A metadata migration rehearsal on a private copy of production passed integrity
checks, tagged all 52 legacy queries local, and retained identical bytes for 126
result artifacts. It classified 28 workflows as local and 19 as upload-derived;
36 Neo4j files hid under IU while all 22 ordinary files remained visible. All
58 files were visible again under local. No original data was changed.

Existing write path: database_sync.reconcile_records opens an explicit write
session for SQL-to-Neo4j reconciliation (merge/update/delete of its managed
records). Both the sync API and the sync CLI reach that same path. The IU source
example has no SQL mappings, so sync is unavailable. Provisioning and benchmark
loaders remain pinned to local. This work performed no database write on IU and
ran no remote SSH command.

Release is still pending: an unrelated zlib update invalidated native runtime
dependency evidence. Fresh native oracle/contract checks and a new evidence
manifest are being prepared before testing and production promotion. The
correctness gate remains enforced.
