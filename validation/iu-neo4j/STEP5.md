# Step 5: remote power control

IU wake/sleep is opt-in and defaults off. The SSH client pins the supplied
SHA256 host-key fingerprint before authentication, reads its password only from
GRAPHMINE_IU_SSH_PASSWORD, and permits only the three exact systemctl commands.
It requests a terminal and sends the sudo password through stdin after the
password prompt; remote output and exceptions are never forwarded to logs/UI.
No remote SSH command was run for this implementation or its tests.

Power ownership, activity leases, and a process/file lock are shared across
development, testing and production. This prevents one environment from stopping
the remote while another has an active session or database job. The default
state directory is ~/.local/state/graphmine/iu-neo4j (respecting XDG_STATE_HOME);
GRAPHMINE_IU_NEO4J_STATE_DIR can override it. All environments must use the same
directory. A host reboot discards uncertain ownership. Idle shutdown requires
proven ownership, no live operation, no queued/running/cancelling database job,
and 30 minutes without activity by default.

User database sessions, connector imports, and explicit source opening acquire
activity leases and call ensure_awake. Metadata, page loads, capabilities and
health checks never wake or extend idle time. The existing event bus persists
bounded, owner-scoped progress, including the requested wake message. Durable
jobs carry the same message. The database UI polls this progress while an
explicit open is pending.

Validation: 20 power-control tests, including separate-process lock contention,
exact-command enforcement, host-key rejection, timeouts, back-off, ownership,
cross-environment jobs, and generated-secret log checks. Five integration tests
exercise passive requests, explicit opening, disabled wake, owner-isolated
progress across event-bus instances, and durable job progress. The broader
regression result is recorded in step5-tests.xml. Frontend tests: 31 passed;
all three changed JavaScript files passed node --check, and git diff --check
passed.

As documented in Step 4, the existing native k-core evidence/self-test failure
is excluded from this scoped regression run. It was reproduced on the original
source; its correctness gate remains intact.
