# Accounts and daily limits

Account login is enabled by default for both `/` and `/classic`. You create the
usernames and passwords through an administrator login or the server console;
there is **no public registration endpoint or signup form**. Each account sees only its own conversations, uploads,
jobs, results, workflow examples, history downloads and event streams.

## Create accounts yourself

Run these commands from the installed repository, after setting up the existing
`.venv` and `agent/.env` as usual. The helper loads that environment so it uses
the same persistent database as `deploy/start-agent.sh`.

```bash
deploy/manage-accounts.sh create wajid --admin
deploy/manage-accounts.sh create alice
deploy/manage-accounts.sh create bob
deploy/manage-accounts.sh list
deploy/manage-accounts.sh reset-password alice
deploy/manage-accounts.sh disable bob
deploy/manage-accounts.sh enable bob
```

The `--admin` flag creates an administrator. After signing in, open **Settings**
in the top bar. **Usage** shows a token progress bar, tokens used and remaining,
the automatic reset time, and remaining graph jobs. **Account** shows your
username and lets you change your password by entering your current password.
Changing a password signs out all devices and preserves usage.

Administrators also see **Settings → Manage users**, where you can create ordinary
accounts with a username, password and daily token allowance. Select a user to
see their usage, edit their allowance, reset token usage, reset their password,
or disable and re-enable access. Search helps find accounts in a larger list.
Ordinary users cannot use those controls or
their API endpoints. Only the local CLI can create another administrator.
Administrators have the same usage limits and workspace privacy rules as other
accounts; the administrator role grants account management, not automatic access
to everyone else's research. The browser prevents you from disabling yourself.

`create` and `reset-password` prompt twice for a password without displaying it.
Passwords must be 12–128 characters. Usernames are case-insensitive, 3–64
characters, and accept letters, digits, dots, underscores and hyphens. Give each
person their own account and provide the credentials privately. No initial
account or default password is included. Password reset and disabling an
account revoke its existing logins; resetting a password does not reset usage.

For a service with a custom data directory, use its exact directory:

```bash
deploy/manage-accounts.sh --data-root /var/lib/graphmine create alice
```

Run as the service's OS user, which must be able to write the data directory.
Account operations can run while the API is running. Keep the data directory
persistent and private to that OS user; SQLite stores password hashes, login
sessions and quota counters there. Existing database backups therefore also
contain account data. Deleting or replacing the database loses the accounts
and usage records.

## Defaults for a small shared server

| Limit | Default | Environment variable |
| --- | ---: | --- |
| Accounts the operator can create | 100 | `GRAPHMINE_MAX_ACCOUNTS` |
| AI tokens per account per 24 hours | 50,000 | `GRAPHMINE_ACCOUNT_DAILY_TOKENS` |
| AI tokens across the server per 24 hours | 1,000,000 | `GRAPHMINE_SERVER_DAILY_TOKENS` |
| Graph jobs per account per 24 hours | 10 | `GRAPHMINE_ACCOUNT_DAILY_JOBS` |
| Graph jobs across the server per 24 hours | 100 | `GRAPHMINE_SERVER_DAILY_JOBS` |
| Simultaneous model requests across the server | 2 | `GRAPHMINE_MAX_MODEL_CALLS` |
| Queued/running graph requests across the server | 8 | `GRAPHMINE_ACCOUNT_PENDING_JOBS` |
| Simultaneous graph calculations across both UIs (one per account) | 4 | `GRAPHMINE_ACCOUNT_RUNNING_JOBS` |
| Waiting for an execution slot | 900 seconds | `GRAPHMINE_ACCOUNT_QUEUE_SECONDS` |
| Execution time once started | 300 seconds | `GRAPHMINE_ACCOUNT_JOB_SECONDS` |
| One raw upload | 64 MiB | `GRAPHMINE_ACCOUNT_UPLOAD_BYTES` |
| Uploads plus saved analyses per account | 512 MiB | `GRAPHMINE_ACCOUNT_STORAGE_BYTES` |
| Delete conversations idle for this many days (0 = keep) | 0 | `GRAPHMINE_RETENTION_DAYS` |
| Login lifetime | 24 hours | `GRAPHMINE_ACCOUNT_SESSION_SECONDS` |

Only one model call and one pending graph request per account are admitted at a
time. A classic multi-step analysis shares one pending request slot but each
step counts toward the daily job budget. Native workflows count as one job;
their steps share the execution time allowance. Waiting for a slot does not
use that allowance. A job that times out or is cancelled before it starts is
refunded to the daily job budget. Existing workflow validation,
memory reservations, result-size and upload-parser limits still apply. Expensive
API requests also have an eight-request server limit per kind of work. Each user
may have one planning request, one other expensive request and two graph
previews at a time, so a long planning request does not block previews,
uploads or approvals. Planning requests may run for the planner's own
360-second deadline plus a margin; other expensive requests stop after 300
seconds. The calculation catalog is verified once and shared by all users for
up to five minutes; reconnecting re-verifies it. Polling, cancellation and
logout remain available. Rejected requests receive a
clear error and, for quota/admission limits, HTTP 429 with `Retry-After`.

The shared limits are first-come, first-served: calculations and model calls
wait in arrival order, and an account already at its own limit does not hold up
the people behind it. Model calls wait up to 60 seconds for a free slot before
asking you to retry. Within the calculation limit, the GPU/CPU memory scheduler
still admits only work that fits. The server budget does **not**
promise every one of 100 accounts all 50,000 tokens each day. Accounts can browse
saved work after their AI allowance runs out. Expert calculations consume the
graph-job budget even when they do not call the model.

Each account can have its own token limit, stored in the database. Existing
accounts and accounts created without an override use the configured default.
An administrator can set a whole-number limit from 0 to the shared server limit;
0 pauses new AI requests while saved work remains accessible. Saving a new limit
preserves spent tokens and takes effect on the next request. Lowering a limit
below current usage leaves no tokens remaining; requests already running finish.

**Reset token usage** clears only the selected user's spent tokens. It preserves
their scheduled 24-hour reset, graph-job usage, and shared server usage. Resetting
is refused while that user has an active AI request; retry after it finishes.
An individual reset cannot bypass an exhausted server allowance. The Usage tab
shows the shared server allowance to administrators as a separate progress bar.

These are starting limits, not a 100-concurrent-user capacity measurement. Graph
algorithms have very different costs. Monitor CPU, GPU memory, execution time
and disk use before raising them. The storage allowance counts raw uploads, including
projected files, plus each conversation's saved analysis inputs and results. It
does not cap history archives, model weights or all disk use. **Settings → Usage**
shows both parts. Deleting a conversation or an uploaded file frees its space. The existing model server must
also retain its configured context length, sequence and GPU memory limits.

## How the 24-hour token allowance works

Input and generated tokens both count, including routing, planning,
interpretation and repair/retry requests in either workspace. Before each chat
request, the API asks the configured model server's `/tokenize` endpoint to count
the rendered prompt with the same chat and thinking settings. It reserves those
input tokens plus the maximum completion allowance, rather than treating the
request's JSON bytes (including its output schema) as tokens. Token counting does
not run inference and shares the same concurrency limit as model calls.
Transports without a compatible tokenizer retain the conservative byte estimate
and template headroom. A successful response
with valid usage settles the reservation to the reported token count. If the
request never reaches the model server, or that server returns an error, nothing
is charged. A timeout or cancellation charges only the counted input tokens and
refunds the unused output allowance. A successful reply without usage keeps the
reservation, because the actual work cannot be established. A long prompt can still be rejected when its input
plus maximum output exceeds the remaining allowance. The error reports the
required reservation, remaining tokens, reset time, and whether the user or
shared server limit was reached. A job can make several model calls; each is
counted separately. Model servers that omit usage exhaust budgets sooner.

Counters are stored in SQLite and reservations are atomic. Concurrent requests,
restarting the API, signing out and resetting a password do not restore tokens.
Each account has consecutive 24-hour windows anchored at account creation;
the server has its own shared window. Rollover happens automatically on the next
request, with no cron job. **Settings → Usage** shows the token bar and reset time;
`/api/auth/me` includes usage and exact reset timestamps.
Pending jobs are marked interrupted after a server restart and can be resubmitted;
their previous daily charges remain. Stale concurrency reservations are released
without resetting the daily budgets.

## Local testing and later Internet hosting

For a local HTTP preview, explicitly set this in `agent/.env`:

```dotenv
GRAPHMINE_ACCOUNT_COOKIE_SECURE=false
```

For an HTTPS domain, including a Cloudflare Tunnel, keep
`GRAPHMINE_ACCOUNT_COOKIE_SECURE=true` (the default). Set
`GRAPHMINE_ALLOWED_ORIGINS=https://your-domain.example` and restart the API after
changing settings. Login uses an HttpOnly, SameSite=Strict cookie. Passwords are
stored as salted scrypt hashes, and API session tokens are stored only as hashes.
Login attempts and simultaneous password checks are bounded. The browser does
not store a password or account token in localStorage.

### HTTPS on a LAN without a proxy

The API can serve HTTPS itself. Give it a certificate and key, enable Secure
cookies, list the HTTPS origin, and restart:

```dotenv
GRAPHMINE_TLS_CERTFILE=/path/to/graphmine.crt
GRAPHMINE_TLS_KEYFILE=/path/to/graphmine.key
GRAPHMINE_ACCOUNT_COOKIE_SECURE=true
GRAPHMINE_ALLOWED_ORIGINS=https://GPU_SERVER_LAN_IP:18000
```

A certificate from your institution's internal CA avoids browser warnings. For a
short pilot, a self-signed certificate works after each tester accepts it once:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout graphmine.key -out graphmine.crt \
  -subj "/CN=GPU_SERVER_LAN_IP" -addext "subjectAltName=IP:GPU_SERVER_LAN_IP"
chmod 600 graphmine.key
```

When accounts are enabled, Secure cookies are off and the API listens on a
non-loopback address, `serve` prints a warning that passwords travel unencrypted.

Forward only the GraphMine web/API port through your proxy or tunnel. Keep the
model endpoint, database files and native workers private. Run one API process
per data directory, as required by the existing worker ownership locks. This
feature creates no domain, tunnel or public listener beyond the existing serve
command; installation and a restart are needed before it affects a running API.

## API and MCP clients

Account mode ignores the old shared `GRAPHMINE_API_TOKEN` for API authentication.
An API client logs in with `POST /api/auth/login`, header
`X-GraphMine-Request: 1`, and this JSON body:

```json
{"username":"alice","password":"your password","issue_token":true}
```

Send the returned `access_token` as `Authorization: Bearer ...` for subsequent
API requests. It has the same daily limits, ownership and expiry as a browser
login. Never place it in a URL. Cookie clients must include
`X-GraphMine-Request: 1` for mutations. Cross-origin browser requests also need an
allowed origin. The MCP bridge's existing API token setting can receive this
account session token; renew it by logging in when it expires. Existing live
smoke checks likewise need an account session token rather than the legacy
shared secret. Server-local operator CLI workflows are trusted and do not use
HTTP account quotas.

## Existing data and legacy mode

The database migration preserves existing conversations with no account owner.
They stay hidden from signed-in users until you explicitly assign them:

```bash
deploy/manage-accounts.sh adopt-legacy alice
```

This assigns **all** currently unowned conversations and their associated data
to Alice. It does not reassign any conversation already owned by another user.
Use this only if that account should receive all previous shared workspace data.

`GRAPHMINE_ACCOUNTS_ENABLED=false` restores the original shared-token/private-LAN
behavior, with shared visibility and no account quotas. Keep accounts enabled
for a shared public deployment. Do not alternate between these modes on a
multi-user data directory if users expect their work to remain private.

## Conversation management and retention

People can rename, archive and delete their own conversations, and remove an
uploaded file. Deleting a conversation removes its uploads, saved analyses,
reviewed examples and history snapshots; it is refused while an analysis in it
is still running. Existing database backups keep their copies until they are
rotated.

`GRAPHMINE_RETENTION_DAYS` (default 0, off) deletes conversations whose last
activity, such as a question or upload, is older than that many days. The sweep
runs at startup and every six hours, and skips conversations with running work.

## Backups

Snapshots can be taken while the API runs. Each copies both databases with
SQLite's online backup (accounts, quotas, conversations and the analysis
ledger), then uploads, saved analyses and history. Model caches, exports and
earlier backups are excluded. Every uploaded file is checked against its stored
hash.

```bash
graphmine-agent backup /path/outside/data/graphmine-2026-10-15
graphmine-agent verify-backup /path/outside/data/graphmine-2026-10-15
graphmine-agent restore-backup /path/outside/data/graphmine-2026-10-15 /new/data-root
```

Set `GRAPHMINE_BACKUP_DIR` (outside the data directory) to take a snapshot at
startup and every `GRAPHMINE_BACKUP_HOURS`, verify it, and keep the newest
`GRAPHMINE_BACKUP_KEEP`. A restore always goes into a new directory; point
`GRAPHMINE_AGENT_DATA_ROOT` at it to use it. Pending work in a restored copy is
marked cancelled, never replayed. Backups contain password hashes and private
research data, so keep the backup directory private.
