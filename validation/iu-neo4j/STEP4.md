# Step 4: configured IU connection

Configured sources accept an explicit boolean `auth_disabled`. Only the exact
IU direct Bolt endpoint can use it; its driver receives `auth=None`. Configured
sources carry a private trust marker assigned by the server's file loader.
User-created connections cannot set this option through their request model,
and their private saved documents still require nonempty Neo4j credentials.

The existing private-network policy grants access to the exact host/port in the
administrator's source file, subject to that source's user list. The change adds
no subnet or general private-address exemption. Tests verify rejection of IU
port 7687, HTTP port 7474, neighboring private hosts and unconfigured loopback.

The registry permits explicit loopback Bolt endpoints and the exact IU endpoint
with `auth_disabled=true`. An IU registry entry never becomes part of the local
backend or a local maintenance target. Local credentials and loading behavior
remain supported.

IU connection checks, Cypher queries, schema discovery and connector imports use
managed read transactions. Query collectors and schema samples reset between
driver retries so an unsuccessful attempt cannot duplicate rows or expose
partial choices. Existing explicit SQL-to-graph synchronization remains a write
path; administrative local loaders remain pinned to the local backend. No write
feature was exercised against IU.

## Live verification

`step4-connection.json` records a successful driver connectivity check and
`RETURN 1 AS connected` through GraphMine's connection and query functions:

- Route: `10.2.147.169 dev wg-iu src 10.66.0.8`.
- Endpoint: `bolt://10.2.147.169:7689`, direct scheme, `auth=None`.
- Result: one row, `connected=1`, using `session.execute_read`.
- No SSH command, remote configuration change or database write.

The check used a separate owner-only configured-sources file and temporary data
root. `deploy/database-workspace/iu-source.json.example` supplies the source
entry for rollout. Its entry must be merged into the environment's private
source file (mode 0600) when deploying the new code. Existing production source
files have not yet been changed because the previous running application does
not understand the new field.

## Tests

Final scoped results in `step4-tests.xml`: **323 passed, 1 deselected**, in 91.73
seconds. The command is the Step 3 scoped
run plus `agent/tests/test_iu_neo4j_connections.py`. This includes explicit
authentication policy, user-connection credential enforcement, exact-address
and source-user allowlisting, remote registry validation, managed reads and
retry isolation, alongside database query/sync/pool/lifecycle regressions.
The independently reproduced pre-existing native CPU self-test issue described
in Step 3 remains excluded; its evidence gate was not weakened.
