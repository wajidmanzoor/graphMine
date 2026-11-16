# LDBC SNB SF100 BI — PropGBench Neo4j source

Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
Copied: 2026-11-15T22:51:58+00:00
Page SHA-256: `4db6ccfb31b55a4c48ca873528e8bcff602f678850b1e99bb91514e1bb6ec7f6`

`page.html` is the archived publisher page. `source-manifest.json` records
the exact code blocks, order, and hashes. GQL alternatives are excluded.
GDS examples are retained for source completeness and must not be executed.

## Input files


The page publishes an administrative bulk-import shell script, not a
Cypher node/edge loader. It is archived under `reference/` and is never
executed directly: it contains system-wide and destructive commands.
The user authorized adapting this published bulk importer for a separate
Neo4j 5.26 Community instance. Record every compatibility change here.
The copied schema alone does not load this dataset.

## Verification and count differences

No database has been loaded or verified yet. Published counts are unchanged.

## Approved bulk-import compatibility preparation

PropGBench links the LDBC reference implementation for system-specific CSV
headers. The 31 original headers are copied under `reference/headers/`, pinned
to commit `47dd38b40844ecdb0e42e5a610c369535304786d`.
`reference/headers-source.json` records every source URL and Git blob hash.
The eight node and 23 relationship groups are read from PropGBench's published
`add_nodes` / `add_rels` declarations, preserving its labels and types.

The linked dataset page describes headerless shards, but the downloaded SF100
archive contains column-name headers. This was confirmed directly in an archive
member as well as its extraction. Neo4j 5.26's automatic subsequent-header skip
failed an isolated test with these raw headers and the reference typed headers.
Import preparation therefore writes derived, decompressed shards with only the
verified first header line removed; every subsequent data byte is copied
unchanged. Original gzip files and the archive are preserved. Each derived
shard records source/output hashes and its removed header in a receipt.

The import uses the reference typed headers, including `speaks:STRING[]` for
the raw `language` column and `:LABEL` for Place/Organisation types. These are
upstream definitions, not locally invented properties.

## Host compatibility and memory (2026-11-15)

The prescribed APOC 5.26.0 JAR failed to start on this existing Neo4j 5.26.32
installation (`ObjectUtils.getIfNull` / `NoSuchMethodError`). As explicitly
permitted by the task, the isolated instances use the matching APOC Core
5.26.32 JAR bundled in the existing distribution's `labs/` directory.
SHA-256: `ea6f46b541c473ab79fff4359524027a462d031f21048b8a8acbceb4fa46a92f`.
Upstream release: https://github.com/neo4j/apoc/releases/tag/5.26.32.
No shared distribution or existing instance plugin was changed.

Every new instance starts with a 4 GiB heap. Planned page caches are 12, 8, 8,
40, 16, and 56 GiB for Yelp, ML32M, Genome, Stack Overflow, OnTime, and LDBC,
respectively. The six systemd hard memory limits total 176 GiB, including
2 GiB per instance beyond heap and cache, leaving about 75 GiB on this host.
Stack Overflow is deferred, so its reservation is not currently allocated.
Actual memory and disk use are recorded after loading. Transaction-log
retention is `2 days 2G`, matching the existing host configuration; this does
not change the graph mapping. All listeners bind to loopback with auth enabled.

## Neo4j 5.26 bulk-import compatibility

A two-node synthetic import proved that 5.26 cannot combine the raw header
rows with the typed upstream headers: the raw `creationDate` field is parsed
as a date value even with `--auto-skip-subsequent-headers=true`. Removing only
the already-verified raw header row succeeded. The prepared real shards use
that exact approach; their data bytes are unchanged.

The same synthetic check found that 5.26's `--schema` reader rejects the
published combined schema (`Variable n already declared`). The adaptation
will apply those unchanged schema statements individually through the Python
driver after the offline import. The newer script's unsupported `--temp-path`
option is omitted. No labels, properties, relationship types, or column
mappings are changed.

## Verification scope approved by the user

On 2026-11-15 (America/New_York), the user changed the rollout gate from
exhaustive query execution to representative published queries. Full label/type
counts and index checks remain required. `verify_dataset.py` selects four
published queries for this dataset and records every other query as untested
or explicitly out of scope. Passing these checks does not establish that every
remaining workload query will succeed. `--all-queries` remains available for a
separate exhaustive run.

The selected verification queries are Q01, Q04, Q07 and Q08.

## Default-database restart compatibility

A separate authenticated temporary Neo4j 5.26.32 instance was started empty,
stopped, bulk-loaded with two Person rows, and restarted while keeping its
original system database. Both imported nodes were queryable after restart.
The empty bootstrap was retained throughout the test. The receipt is
`neo4j-instances/ldbc-snb/compatibility/import-restart-smoke.json`; the temporary
test store was removed after success. No deployed store was modified.

## Concurrent loading approved by the user

On 2026-11-15 (America/New_York), the user asked to keep OnTime loading in the
background and start LDBC immediately. LDBC therefore requires the already
verified Yelp and both MovieLens datasets, but does not wait for OnTime to
finish. The two loaders use separate instances and controllers. The LDBC bulk
import retains its 40 GiB memory cap; its Neo4j service is stopped during that
offline stage. Each dataset must independently finish loading and pass its
count, index and representative-query checks before it enters the registry.
The published mappings and source records are unchanged.
