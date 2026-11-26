# Neo4j backends

GraphMine has exactly two database backends. `iu-remote` is the default:
`bolt://10.2.147.169:7689`, reached through WireGuard, with authentication disabled
(`auth=None`). `local` contains the retained loopback instances in
`deploy/neo4j-datasets/registry.json`. Local services are parked until activated;
their code, units, imports and stores remain on disk.

Each application data root has a mode-0600 `neo4j_backend.json`. GraphMine writes
it atomically. Use the administrator switch to change it: editing that file by
hand bypasses job admission, connection verification and pool draining.

## Switch in the workspace

Sign in as an administrator and open **Administration → Data & storage → Neo4j
backend**. The card shows the active backend, local unit states and RAM, remote
reachability and power ownership, record counts, and running database jobs.
Select the target and confirm the change in visible datasets and saved work.
Progress appears while the switch runs; its controls remain disabled.

The API is `GET /api/admin/neo4j` and
`POST /api/admin/neo4j/switch` with `{"target":"local","force":false}` (or
`"iu-remote"`). Both use the existing administrator authentication; other
accounts receive 403. Running database jobs produce 409. The explicit force
option requests cancellation and waits for work to finish safely. The switch
activates the target, verifies `RETURN 1`, changes selection, drains old pools,
and parks local services or releases remote activity. Failures restore the
previous selection and service state, and every attempt is audited.

Environments share the same local units. Stop another running environment that
still selects local before switching away from local. The switch reports this
conflict instead of interrupting that environment.

## What is visible

Neo4j connections, curated datasets, synced/query snapshots, saved query drafts,
imported files, workflows and results carry `backend_id`. Only the selected
backend's records appear in lists, search, recent work and source pickers.
Hidden records return 404 through direct URLs and are retained for switching
back. Uploaded files and results without Neo4j provenance remain available.
Browser drafts are scoped to the backend; old untagged drafts remain local.

Schema 13 migrates existing Neo4j records to `local`, including legacy saved
queries. It tags metadata without rewriting immutable graph/result bytes. A
complete history archive, manifest or model-note bundle is unavailable while
it contains inactive Neo4j evidence; switching back restores it. Access to
individual ordinary uploads is unaffected.

Back up the store before migration. Restoring pre-schema-13 code requires its
matching pre-migration data backup. A new-code backup includes backend selection;
remote power ownership is machine state and is never copied into a restored
workspace.

## Local service controls and manual access

From the checkout root, using the same Linux account that owns the services:

```sh
scripts/neo4j_local.sh status
scripts/neo4j_local.sh activate
# Inspect/connect to the retained local instances.
scripts/neo4j_local.sh park
```

These commands control services; they do not change the application's active
backend. `activate` runs `systemctl --user enable --now <unit>` and waits up to
120 seconds for Bolt. `park` runs `systemctl --user stop <unit>` followed by
`systemctl --user disable <unit>` and prints RSS freed from `ps` measurements.
The legacy unsuffixed service and Browser proxy are included. Previously parked
incomplete instances remain excluded from activation. No sudo is used.
`GRAPHMINE_PYTHON` can select the installed application Python for this script.
The deployed environment configuration supplies production registry/data paths;
explicit environment settings take precedence.

While parked, local Bolt connections fail normally. Activate first, then use the
`bolt://127.0.0.1:<port>` addresses in the registry. Each entry names its password
environment variable. Their private values live in `.database-workspace/demo.env`
or the operator's `GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE` (owner-only). Configured
sources may use `GRAPHMINE_DATABASE_CREDENTIALS_FILE`. Let the driver or interactive
client consume the credentials; keep values out of command arguments and logs.
Use the registry's actual ports; the old workspace uses 17687 and the retained
benchmark instances use their own ports. Park again when manual access ends.

## IU connection

Bring up `wg-iu` as described in [IU_NEO4J.md](IU_NEO4J.md). Use direct
`bolt://10.2.147.169:7689`, with no authentication. Do not use `neo4j://` routing
or the advertised port 7687: the remote discovery document advertises the wrong
port. HTTP 7474 is separate and is not the Bolt endpoint.

Merge the entry from
[the configured-source example](../deploy/database-workspace/iu-source.json.example)
into the environment's `GRAPHMINE_DATABASE_SOURCES_FILE`, mode 0600. Keep existing
local entries for later switching. The file grants network access to exactly
10.2.147.169:7689 for the listed users. It grants no general private-network
exemption. Only configured sources can use `auth_disabled`; user-created
connections still require credentials. When using a curated dataset allowlist,
`default` includes the configured IU graph while IU is selected.

Read queries, schema discovery and connectivity verification use read
transactions. Explicit SQL-to-Neo4j synchronization/reconciliation remains a
write feature; configuring SQL mappings and requesting sync can mutate its
selected graph. The supplied IU example has no SQL mappings, so sync is
unavailable. Local provisioning/loaders are explicitly pinned to `local`.

## Wake and idle sleep

`GRAPHMINE_IU_NEO4J_AUTOWAKE=false` is the default. Set it to `true` only in the
application service environment when enabling remote power control. Supply
`GRAPHMINE_IU_SSH_PASSWORD` privately, for example via the operator's `agent/.env`
when using `deploy/start-agent.sh`. The environment controller uses its configured
service environment; a checkout's `.env` is not automatically imported by that
controller. Never copy this password into source files or shell arguments.

Only an explicit database action (source open, query, preview, sync, or admin
switch) can wake IU. Page loads, capabilities and health/status requests never
wake it or extend idle activity. Users see “Starting the database, about 40
seconds…” while the app waits, up to 120 seconds. A failed SSH operation backs
off for five minutes; a missing VPN route produces “VPN tunnel is down”.

Shutdown requires proven ownership of the start, no active query/session or
database job across registered environments, and at least
`GRAPHMINE_IU_NEO4J_IDLE_MINUTES=30` without use. A server GraphMine did not start
is never stopped. Switching away from IU only releases activity; it sends no
stop command. Setting AUTOWAKE back to `false` disables both start and stop.

All environments must share `GRAPHMINE_IU_NEO4J_STATE_DIR`, defaulting to
`$XDG_STATE_HOME/graphmine/iu-neo4j` or `~/.local/state/graphmine/iu-neo4j`.
It holds private locks, ownership, leases and job-store registrations. A host
reboot invalidates uncertain ownership. No remote file is created or changed.
