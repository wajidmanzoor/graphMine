# GraphMine administrator console

The console is served at `/admin` and reuses the GraphMine sign-in cookie. Accounts
with the `admin` role see an Admin link beside Settings. A signed-out or member
request to every `/api/admin/*` route receives 403. Browser mutations retain the
`X-GraphMine-Request: 1` check.

Phase 1 provides the shared navigation, Users, Activity, Add/Edit/Delete user,
password resets, token resets, forced sign-out, Studio sync, and support access.
Phase 2 adds Overview, Health, the API self-test, incident history, and Model.
The remaining Manage and Configure pages and Usage are delivered in subsequent
phase PRs. Empty measurements have an availability explanation; the browser does
not contain sample account counts or traffic measurements.

## Accounts and support access

Account limits and access are edited through `PATCH /api/admin/users/{username}`.
Changing role, username, access, or the required-password-change state revokes
existing GraphMine sessions when the value actually changes. Temporary passwords
are returned only from creation/reset when the server generated them, and never
appear in the user list, event stream, or audit snapshots. Users flagged for a
password change can only inspect their identity, change their password, or sign out.

Token resets clear the user's charged tokens in their existing rolling 24-hour
allowance. They preserve job charges, storage, and the shared server pool.

The last active administrator cannot be demoted, disabled, deleted, or stripped
of GraphMine access. This check and each account mutation run in one immediate
SQLite transaction. Each mutation writes secret-free before and after JSON to
`admin_activity` in the same transaction.

Delete previews count conversations, saved workflows, uploaded files and bytes,
project snapshots, and charged storage on the server. Deletion requires `confirm:
true` and an exact `confirm_username`. Transfer reassigns owned records and project
memberships to the acting administrator. Erase removes the owned records and queues
physical artifacts for deletion. Active work prevents deletion. File cleanup is
durable and resumes on startup; failed Studio updates remain retryable even after
the GraphMine account is gone.

Normal administrative APIs expose problemal metadata. Reading a conversation
requires a reason and a support grant, bound to the administrator's current login
session. A grant lasts one hour or until that session expires, whichever applies,
and also stops working on sign-out, role change, or disable. Its only endpoint is a
read-only conversation view. The owner sees grants under Settings → Account →
Account history.

## Dataset Studio

Set `GRAPHMINE_STUDIO_AUTH_DIR` to the running Studio's `workspace/auth` directory.
The default is `<repository>/dataset-studio/workspace/auth`. GraphMine updates
`users.json` through `studio_sync.sync_user`, with an atomic replacement and a
nonblocking `users.lock` advisory lock. GraphMine changes commit even when Studio
is missing, locked, or rejects removal of its last active administrator. The
Users page displays the failed update and its retry action.

Deploy the included Studio authentication changes with the console: Studio reloads
its JSON files under the same cross-process lock, checks linked GraphMine access,
and rejects temporary passwords until they have been changed in GraphMine.
GraphMine-linked Studio accounts use the GraphMine password; no password is copied
into Studio's JSON.

## SSH management

```sh
graphmine-agent users create alice --studio --must-change-password
graphmine-agent users create another-admin --admin --studio
graphmine-agent users set-role alice admin
```

The `accounts` command remains an alias. Passwords are entered through a hidden
terminal prompt. `--data-root` belongs immediately after `users` or `accounts` and
selects the same store as the running agent.

## Operational events and migration

Schema 12 renames the old private `events` table to `conversation_events`, preserving
its sequence numbers, payloads, and conversation timeline. The new `events` table
contains only problemal records: `id`, `ts`, `user_id`, `type`, `summary`, `outcome`,
`duration_ms`, `details_json`, and `request_id`. The types are question, calculation,
sign_in, error, admin_change, and support_access. Indexes cover timestamp, user and
timestamp, and type and timestamp. `GRAPHMINE_ADMIN_EVENT_RETENTION_DAYS` defaults to
180; audit records and support history remain separately stored.

Question text and model reasoning remain in the private conversation log. Aggregate
question events contain recorded timing and token usage where available, with no
invented queue timings. Failed sign-ins truncate network addresses before storage.
CSV exports escape spreadsheet-formula prefixes.

The recording-start timestamp is persisted, and the Users page labels the coverage
of new activity counts. Existing account sessions backfill known sign-in dates;
missing historical sign-in data is not labelled as a never-used account.

Schema 12 must not be opened concurrently by an older agent. Stop the previous
agent before opening its shared store with this version. A rollback to the previous
agent requires the pre-upgrade database snapshot; older agents reject schema 12.

[Phase 1 browser evidence](../validation/admin-console/phase-1/README.md) includes the
Users and Activity pages, all dialogs, support view, mobile layout, and access denial.
The local `GraphMine Admin Console.html` supplied by the user provides all twelve
artboards. Reference captures and implementation images are shown side by side
in the phase evidence, with actual measurements kept separate from design examples.

## Monitoring and model controls

For a TLS-enabled local Studio, set `GRAPHMINE_STUDIO_HEALTH_URL` to its HTTPS
address. Probes trust the configured agent TLS certificate in addition to system
roots, while retaining hostname and certificate verification.

Health probes run on the server in parallel, each bounded to three seconds. The
console reuses snapshots for ten seconds; a background sampler runs every thirty
seconds. Red checks open incidents immediately, warnings after fifteen continuous
minutes, and a healthy observation closes the incident. An unavailable check does
not falsely close an incident. GPU samples retain twenty-four hours of actual
measurements, without backfilling missing history.

Set `GRAPHMINE_PUBLIC_URL` and `GRAPHMINE_STUDIO_PUBLIC_URL` for public HTTP probes.
Studio defaults to `http://127.0.0.1:8877/`; `GRAPHMINE_STUDIO_HEALTH_URL` can select
the deployed local health URL. Configured Neo4j and Postgres sources receive TCP
reachability checks, labelled as such; these do not claim database-query success.
SQLite size includes its WAL and the workflow database. Slow-query counts remain
unavailable until instrumentation is installed. Email controls are hidden because
this deployment has no incident-mail integration.

Agent logs and restart controls require a systemd unit whose working directory
matches this checkout. The agent unit must also have this process as its MainPID.
The defaults are `graphmine-agent.service` and `graphmine-vllm.service`; override
them with `GRAPHMINE_ADMIN_AGENT_UNIT` and `GRAPHMINE_ADMIN_MODEL_UNIT`. Restarts use
an allowlisted service name, require `confirm: true`, and record both the request
and queued action. A queued restart is not reported as completed. Model launch
settings are read from its running process, when available, without exposing API
keys or arbitrary command-line arguments.

The self-test uses the real sign-in, question, upload, workflow, and result APIs.
Its `selftest` account is marked `login_disabled`, and both password login and
issued tokens are rejected outside the internal runner. No HTTP header can enable
that identity. Passwords are random for each run and never returned. The last
step results persist in SQLite; interrupted runs are marked on startup. This is
an on-demand test that consumes the normal model and job allowances.

Model settings persist in `settings_overrides` with the actor and update time.
Idle timeout and thinking switches apply to new calls immediately; enabled thinking
switches preserve existing provider defaults. Sleep-mode changes require a model
restart. `deploy/start-vllm.sh` loads the validated saved value over the environment
and retains the existing free-RAM safeguard. The console's restart action applies
the matching power-client setting; an out-of-band model restart should be followed
by an agent restart so both processes reload the same saved settings.

Overview uses UTC calendar days, while account token limits retain their existing
rolling twenty-four-hour window. Timing percentiles and token totals come from
recorded events; incomplete provider usage is labelled unavailable. All-time
problem counts come from saved successful workflow plans. Model call statistics
cover stored diagnostics; missing historical automatic wake counts remain
unavailable rather than being inferred from manual admin actions.

[Phase 2 browser evidence](../validation/admin-console/phase-2/README.md) covers
Overview, Health, Model, and the narrow-screen layout.


## Jobs and usage

Jobs & queue refreshes every five seconds. Model-call tracking stores owner,
known schema stage, queue/start times and provider-reported usage in memory;
it never stores prompts or generated content. Unknown streaming token counts
remain unavailable until the provider reports them. Calculation rows include
saved input metadata, safe plan fields and step status, with active, finished
today and failed filters. Lists are capped at 500 rows and report truncation.

Cancellation follows the existing worker paths and emits “Cancelled by an
administrator” to the owner. It records before/after metadata under the actor's
identity and refunds the daily calculation once. Cancelling a job from a batch
cannot consume another job's refund. Disabled owners' existing jobs remain
cancellable by an active administrator. Completed work rejects cancellation.

Usage accepts 7, 14, 30 or 90 days and caches each aggregate for sixty seconds.
Periods use UTC calendar dates, comparing today's elapsed hours with equivalent
elapsed hours in the prior period. Counts and provider usage cover recorded
question/calculation events. Partial provider token reports do not become complete
totals; reasoning share also requires coverage. Error rate counts failed or
interrupted questions/calculations once, excluding cancellation from failures.
Per-stage charts show measured aggregate seconds across calls and calculations;
missing model queue times are not inferred. Dataset counts use recorded calculation
inputs. Free-text feedback is not classified as a routing mistake; without a
structured routing correction, that metric remains unavailable.

Six fixed Vega-Lite specifications render with the vendored Vega expression
interpreter under the existing CSP. Charts accept inline measured data only and
cannot fetch external resources. Regenerate pinned assets with `npm ci` followed
by `node vendor.mjs` in `agent/visualization`. The interpreter's ESM wrapper reuses
the helpers from the pinned Vega runtime. Its license and source hashes are kept
with the vendor manifest.

[Phase 3 browser evidence](../validation/admin-console/phase-3/README.md) includes
both pages beside their supplied artboards, details and mobile Usage.

## Capacity, storage and performance

Capacity exposes the fourteen validated settings in `admin_settings.py`: model
concurrency, vLLM requests, model queue wait, the shared token pool, calculation
and per-user concurrency, CPU workers, calculation/queue deadlines, default token
and storage allowances, upload size, backup count and problemal-event retention.
Saves require confirmation, compare against the values loaded by the page, and
record before/after values. A conflicting edit returns 409. New work receives live
settings; vLLM request changes wait for a model restart. The displayed effective
vLLM limit comes from the running process, not from the desired override. The
launcher reads validated overrides before starting vLLM. `MODEL_QUEUE_SECONDS`
is the stored key; `GRAPHMINE_MODEL_QUEUE_SECONDS` and the older unprefixed name
are accepted from the environment. Upload overrides also update the account and
transport upload ceilings, while storage quotas still apply.
Editing an existing user's access preserves blank, inherited token/storage limits;
the form does not silently turn the current default into an individual override.

Data & storage measures managed files and embedded SQLite payloads. Model caches
are excluded, and archived history/database overhead appear under Other. Cleanup
previews contain at most 500 items. Confirmation rechecks the preview fingerprint,
references and active owner work under the existing workflow edit lock and an
attached SQLite transaction. It rejects stale previews, referenced files, unsafe
paths, and work in progress. File removal is queued durably and retried at startup.
Authenticated file/result reads record access timestamps; offline backup and
inspection helpers remain read-only. Historical results without an observed open
are kept for the entire 90/180-day period after tracking began. Saved views,
snapshots, templates and project references protect results. Cleanup retains plans
and inputs, removes result indexes, and explains how to calculate results again.
Deleting embedded results frees reusable database pages; it does not promise an
immediate reduction in the SQLite file's physical size. External history retains
its independent retention policy.

Back up now, Verify and Restore reuse `backup.py`. Successful integrity checks are
recorded with the manifest hash and verification time. A failure clears the
verified status. Restore requires the exact snapshot name and stages data in a
new directory; activating that directory remains an operator deployment step.
Manual backups work even when automatic backups are unconfigured. The built-in
scheduled retention default is fourteen snapshots; an existing environment value
still takes precedence until changed in Capacity. Manual snapshots are not rotated
by the scheduled job.

Performance reads the optional installed `perf/run.py` suite's `var/perf` config,
summary and report artifacts. The console returns allowlisted metadata, not raw
queries or configuration secrets. Reports run in an opaque CSP sandbox with no
network, forms, popups or same-origin privileges. Benchmark and ten-user load
tests are available only when the suite is installed. Stress, spike and soak also
require `GRAPHMINE_PERF_CONFIRM_SHARED_GPU=1`; every launch records the agreed slot
and confirmation. Fixed argv starts the suite as a background job, using a private
0600 environment file that is removed on completion. Jobs expose status and report
availability, not raw subprocess output. Shutdown terminates owned test processes.
Opening the page never installs the suite or starts model/GPU work.

[Phase 4 browser evidence](../validation/admin-console/phase-4/README.md) places all
three pages beside their supplied artboards and includes cleanup and mobile views.
