# Step 7: backend provenance and visibility

Neo4j connections, curated sources, snapshots, browser query drafts, imported
files, workflows, results, shared items and conversation events carry their
backend provenance. Lists, search, recent-work cards, pickers, cached table
reads, exports and direct links enforce the active selection. Hidden records
return 404 and reappear when their backend is selected again. Ordinary uploads
and their results remain available in either backend. Mixed backend inputs are
rejected rather than classified as uploads.

Schema 13 tags existing Neo4j metadata as local, including the legacy
query_library table. A result metadata index preserves immutable result bytes.
Connection migrations preserve private credentials and file permissions.
Backups include the selected backend. Complete history bundles, manifests and
model notes return 404 while they contain inactive evidence; their bytes are
retained for access after switching back. Individual upload access remains
available. Browser drafts use separate backend scopes and retain legacy local
keys. Conversation polling refreshes cached UI records after a switch.

Validation: step7-tests.xml records 439 passing checks and 24 explicitly opt-in
integration skips. Coverage includes hidden URLs, saved searches, recent lists,
warm table indexes, project membership and shared links, history downloads,
metadata migration, result-byte preservation and uploads visible on both
backends. All 35 frontend tests pass, as do TypeScript, generated contracts,
JavaScript syntax and whitespace checks.

A separate native workflow run reproduced the prior correctness-evidence
failure. Diagnosis found exactly one changed native dependency:
/usr/lib/x86_64-linux-gnu/libz.so.1.3. The existing evidence gate correctly
refuses admission. Native verification must be rerun and evidence refreshed
before the testing/production promotion; the gate has not been weakened.

No real local service was activated and no remote SSH command was run.
