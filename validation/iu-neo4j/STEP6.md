# Step 6: administrator backend switch

The existing administrator dependency protects GET /api/admin/neo4j and
POST /api/admin/neo4j/switch. The status includes selection, local units/RSS,
remote reachability/ownership/activity, per-backend record counts, and pending
database jobs. Counts classify untagged historical Neo4j provenance as local;
Step 7 adds persisted tags and workspace visibility.

Switching closes admission to new database operations, rejects pending jobs or
requests their cancellation when force=true, and waits for active sessions and
in-progress commits. It starts the target, verifies RETURN 1 with execute_read,
publishes the atomic selection, drains old pools, and parks local services or
releases remote ownership for the idle policy. Rollback restores the original
selection and local service states; incomplete recovery is reported explicitly.
Leaving remote never sends a stop command. Every accepted attempt, including
conflicts, failures and no-ops, reaches the existing administrator activity log.

Inline query publication and connector imports hold session leases through
snapshot storage. File locks fence requests and simultaneous switches. Because
the three deployment environments share per-user local services, lifecycle
commands use a common unit-directory lock, switches use the shared power-state
directory, and a switch refuses to park services if another running environment
still selects local. That environment must be stopped before parking; active
work in another environment is never silently interrupted.

The Data & storage admin page includes the two-backend card, active/status/RAM
information, counts, confirmation of workspace visibility changes, optional
job cancellation, disabled switch controls, and live progress. Its source is
agent/frontend/admin-neo4j.js; build.mjs copies the source to static assets.

Validation: step6-tests.xml records 377 passing regression tests and the same
one pre-existing native correctness-evidence exclusion documented in Step 4.
After the shared-service guard and restoration checks, the focused admin/local
suite passed 22 tests (step6-shared-services.xml). Frontend: 33 tests passed,
including switch confirmation/progress/error behavior; generated API contracts,
TypeScript checking, JavaScript syntax and git diff --check passed.

All switch service controls and Neo4j reads in tests are fakes. No local service
was activated and no remote SSH command was executed for this step. Deployment
and live verification remain pending the visibility migration and final checks.
