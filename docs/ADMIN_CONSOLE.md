# GraphMine administrator console

The console is served at `/admin` and reuses the GraphMine sign-in cookie. Accounts
with the `admin` role see an Admin link beside Settings. A signed-out or member
request to every `/api/admin/*` route receives 403. Browser mutations retain the
`X-GraphMine-Request: 1` check.

Phase 1 provides the shared navigation, Users, Activity, Add/Edit/Delete user,
password resets, token resets, forced sign-out, Studio sync, and support access.
The remaining Monitor, Manage, and Configure pages are delivered in subsequent
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

Normal administrative APIs expose operational metadata. Reading a conversation
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
contains only operational records: `id`, `ts`, `user_id`, `type`, `summary`, `outcome`,
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
The supplied design link currently presents security verification to the automated
browser, so artboard comparison remains outstanding.
