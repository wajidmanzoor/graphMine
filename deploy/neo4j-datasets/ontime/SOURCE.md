# OnTime — PropGBench Neo4j source

Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
Copied: 2026-11-15T22:51:58+00:00
Page SHA-256: `c30b2dc0eae4be1fa911682f41dced90d22b2395d46aff943036167fd3397ce5`

`page.html` is the archived publisher page. `source-manifest.json` records
the exact code blocks, order, and hashes. GQL alternatives are excluded.
GDS examples are retained for source completeness and must not be executed.

## Input files

- `ontime20-22/2020_1.csv`
- `ontime20-22/2020_10.csv`
- `ontime20-22/2020_11.csv`
- `ontime20-22/2020_12.csv`
- `ontime20-22/2020_2.csv`
- `ontime20-22/2020_3.csv`
- `ontime20-22/2020_4.csv`
- `ontime20-22/2020_5.csv`
- `ontime20-22/2020_6.csv`
- `ontime20-22/2020_7.csv`
- `ontime20-22/2020_8.csv`
- `ontime20-22/2020_9.csv`
- `ontime20-22/2021_1.csv`
- `ontime20-22/2021_10.csv`
- `ontime20-22/2021_11.csv`
- `ontime20-22/2021_12.csv`
- `ontime20-22/2021_2.csv`
- `ontime20-22/2021_3.csv`
- `ontime20-22/2021_4.csv`
- `ontime20-22/2021_5.csv`
- `ontime20-22/2021_6.csv`
- `ontime20-22/2021_7.csv`
- `ontime20-22/2021_8.csv`
- `ontime20-22/2021_9.csv`
- `ontime20-22/2022_1.csv`
- `ontime20-22/2022_10.csv`
- `ontime20-22/2022_11.csv`
- `ontime20-22/2022_12.csv`
- `ontime20-22/2022_2.csv`
- `ontime20-22/2022_3.csv`
- `ontime20-22/2022_4.csv`
- `ontime20-22/2022_5.csv`
- `ontime20-22/2022_6.csv`
- `ontime20-22/2022_7.csv`
- `ontime20-22/2022_8.csv`
- `ontime20-22/2022_9.csv`

The published shell loop is retained under `reference/`. Its Cypher
here-document is copied once per month; only `${FILE}` is substituted,
with every substitution recorded in that script's header.

## Verification and count differences

No database has been loaded or verified yet. Published counts are unchanged.

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

## Import aliases on APOC 5.26.32

APOC 5.26.32 rejects a symlink whose resolved target is outside the configured
import directory. The published import filenames remain symlinks, but they now
resolve to hard links under `import/.source-files/`. Each hard link shares the
original verified file's inode; no source bytes change and no second large copy
is created. The configured import boundary and both required APOC flags remain
unchanged. Loading and verification still use the publisher's exact Cypher.

## Verification scope approved by the user

On 2026-11-15 (America/New_York), the user changed the rollout gate from
exhaustive query execution to representative published queries. Full label/type
counts and index checks remain required. `verify_dataset.py` selects four
published queries for this dataset and records every other query as untested
or explicitly out of scope. Passing these checks does not establish that every
remaining workload query will succeed. `--all-queries` remains available for a
separate exhaustive run.

The selected verification queries are Q01, Q04, Q05 and Q08.

## Loading memory adjustment

The initial 4 GiB heap completed the airport loader but exhausted Java heap
during the first FLIGHT file. The service was stopped to halt residual APOC
workers, and its partial data, logs, status and unit were preserved under
`neo4j-instances/failed-attempts/ontime-20261116T005635Z/`. The retry uses a fresh
empty store, the same verified inputs and unchanged published Cypher, with
16 GiB heap, 12 GiB page cache and a 30 GiB service cap. The six-instance plan
still leaves at least 64 GiB for other services. The retry receipt is
`neo4j-instances/ontime/retry-receipt.json`.
