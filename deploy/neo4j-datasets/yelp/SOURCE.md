# Yelp — PropGBench Neo4j source

Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
Copied: 2026-11-15T22:51:58+00:00
Page SHA-256: `61da51cf20b05065905bd5bae0dc633e9126eb79ccf6804f19b1670be32a7458`

`page.html` is the archived publisher page. `source-manifest.json` records
the exact code blocks, order, and hashes. GQL alternatives are excluded.
GDS examples are retained for source completeness and must not be executed.

## Input files

- `yelp/yelp_academic_dataset_business.json`
- `yelp/yelp_academic_dataset_review.json`
- `yelp/yelp_academic_dataset_tip.json`
- `yelp/yelp_academic_dataset_user.json`

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

Yelp Q01–Q19 passed during the earlier exhaustive attempt. Q09 took 1,048.716
seconds. Q20 was stopped at the user's request; that interrupted attempt and
its successful results are retained in the instance directory as
`full-attempt-verify_report.json` and `full-attempt-verify.log`. The final
representative report executes Q01, Q02, Q08 and Q24.

The selected verification queries are Q01, Q02, Q08 and Q24.
