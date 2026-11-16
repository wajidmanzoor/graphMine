# Stack Overflow — PropGBench Neo4j source

Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
Copied: 2026-11-15T22:51:58+00:00
Page SHA-256: `aa9917211ff240572ba2e0c84f3c39ebe62237687dc2aea6fed3132b0af22f39`

`page.html` is the archived publisher page. `source-manifest.json` records
the exact code blocks, order, and hashes. GQL alternatives are excluded.
GDS examples are retained for source completeness and must not be executed.

## Input files

- `stackoverflow/badges.csv`
- `stackoverflow/comments.csv`
- `stackoverflow/edge_tag_to_question.csv`
- `stackoverflow/posts_answers_clean.csv`
- `stackoverflow/posts_links.csv`
- `stackoverflow/posts_questions_clean.csv`
- `stackoverflow/posts_tag_wiki_clean.csv`
- `stackoverflow/posts_tag_wiki_excerpt.csv`
- `stackoverflow/tags.csv`
- `stackoverflow/users_clean.csv`
- `stackoverflow/votes.csv`

## Verification and count differences

No database has been loaded or verified yet. Published counts are unchanged.

## Publisher preprocessing

The workload calls `clean_posts_csv.py` before loading post CSVs. It is published
in [the Neo4j instructions document](https://pgraphbenchweb.vercel.app/assets/neo4j_stackoverflow.docx), linked from
[the download index](https://pgraphbenchweb.vercel.app/download.html).
Copied on 2026-11-15 to `preprocessing/`; the original document and script hashes
are recorded in `preprocessing/SOURCE.json`. The code is unchanged.

`posts_answers_clean.csv` and `posts_questions_clean.csv` are generated from the
verified original `posts_answers.csv` and `posts_questions.csv`, using that
script with its default options. Raw originals are preserved. No similarly
named alternate dataset is substituted. Generation must finish successfully
before the import-folder gate passes.

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

## Deferred by the user (2026-11-15)

All 88 files in Dataverse version 1.0 are present, but the required cleaned
post files are not published. The publisher's Word document contains the
exact cleaning helper; it fails with `unexpected end of data` after processing
about 24 million answer records. The final answer part ends mid-body at
`<Visual`; the final question part also ends inside a quoted body. Their MD5
checksums match the publisher metadata:

- `posts_answers.csv_part_015`: `181369b867a198bc34c94ca1e58bad7e` (563818496 bytes).
- `posts_questions.csv_part_007`: `660aa7db476c7945ba57061871f94f16` (1572855808 bytes).

The user said to set this dataset aside because complete inputs are unavailable.
No truncated rows are discarded or repaired, and no Stack Overflow database
has been created or loaded. Original downloads remain untouched. Resume only
with complete publisher inputs and verified provenance; rerun preparation
before the instance gate. Stack Overflow must stay out of the app registry.

## Import aliases on APOC 5.26.32

APOC 5.26.32 rejects a symlink whose resolved target is outside the configured
import directory. The published import filenames remain symlinks, but they now
resolve to hard links under `import/.source-files/`. Each hard link shares the
original verified file's inode; no source bytes change and no second large copy
is created. The configured import boundary and both required APOC flags remain
unchanged. Loading and verification still use the publisher's exact Cypher.
