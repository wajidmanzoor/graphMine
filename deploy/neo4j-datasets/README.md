# PropGBench Neo4j dataset migration

This directory is being prepared on `devlopment`. The production application,
the existing shared Neo4j store, PostgreSQL, and original downloads are preserved.
An archived source page or prepared import folder does not mean a dataset is
loaded, verified, or available to the application.

## Source fidelity

Each dataset contains the original workload page, source metadata and hashes,
ordered loading Cypher, numbered queries, unchanged published counts, and a
`SOURCE.md` record. Only Neo4j examples are selected; alternate GQL examples are
excluded. GDS examples are retained for attribution but are outside execution
scope. Audit the copies with:

```sh
python3 deploy/neo4j-datasets/source_pages.py audit all
```

OnTime publishes its edge loader inside a shell loop. The copied Cypher expands
the same 36 filenames, with each path substitution commented. No mapping is
changed. LDBC publishes an administrative bulk importer. Its original shell
script is reference material only; it includes commands unsuitable for this
shared host. The user approved adapting that published importer for its own
Neo4j 5.26 Community instance, loaded last.

## Import preparation

Use the existing import Python environment, which supplies the dependencies of
`benchmark_import.Builder.source()`:

```sh
.database-workspace/import-venv/bin/python \
  deploy/neo4j-datasets/prepare_import_dir.py yelp --check-only
.database-workspace/import-venv/bin/python \
  deploy/neo4j-datasets/prepare_import_dir.py yelp
```

Files are prepared under `$GRAPHMINE_LAB_DATA_ROOT/neo4j-instances/<dataset>/`.
Raw-file receipts and content hashes are checked. Byte-split parts use the
existing source assembler without running its database-changing constructor;
the joined bytes are checked against the exact ordered input concatenation.
Individual files are symlinked under the publisher's exact import paths. An
existing different file or link is never overwritten. Missing inputs stop
preparation before any database is created or loaded.

APOC 5.26.32 requires symlinks to resolve inside its import boundary. The
published paths therefore point to hard links under `import/.source-files/`.
These share the original verified inode and do not duplicate or change the raw
data. LDBC's offline importer uses the separately verified headerless derived
shards and the pinned upstream typed headers.

## Instance, load and verification gates

After preparation passes, create one instance using the application Python
environment (which includes the Neo4j driver):

```sh
.venv/bin/python deploy/neo4j-datasets/create_instance.py yelp
tmux new-session -s graphmine-yelp
.venv/bin/python -u deploy/neo4j-datasets/load_dataset.py yelp
# Only after a successful load:
.venv/bin/python -u deploy/neo4j-datasets/verify_dataset.py yelp
```

`create_instance.py` refuses an existing store or configuration. It reuses the
existing 5.26.32 binaries with separate configuration, data, logs, transactions,
plugin and run directories. The original prescribed APOC 5.26.0 failed on this
host; the matching bundled 5.26.32 build passed the startup checks. Each dataset's
`SOURCE.md` records the failure, replacement and checksum. Only the private
`.database-workspace/demo.env` stores the generated plaintext passwords.

The loader requires tmux, acquires an exclusive operation lock, rechecks input
hashes and emptiness, and executes each unchanged published statement. It treats
APOC's failed batches, failed operations, error messages, failed parameters and
termination flags as failures. A failed load stops only its dedicated instance
to prevent queued APOC worker batches from continuing after the outer failure. Per-statement receipts and `status.json` stay
under the instance directory on the data disk. A finished load remains in the
`loading` state with phase `awaiting_verification`; it is not yet available.

The verifier compares per-label and per-type counts, checks every index, and
executes four representative published non-GDS read queries, consuming all their
results. The user approved this scope on 2026-11-15 (local time); other queries
are explicitly marked untested. `--all-queries` opts in to exhaustive execution. EXPLAIN
classifies writing statements before execution; reads use READ_ACCESS and
rollback. Query text is unchanged, and typed parameter values, timings, row
counts, result hashes and small samples are recorded in `verify_report.json`.
A selected query timeout fails verification; the default is five minutes per query. Missing published Cypher and excluded GDS
or writing statements are explicitly identified in the report.

Count differences fail until exact expected/actual counts and evidence are
recorded in `count_explanations.json`, with the same explanation in `SOURCE.md`.
The original expected counts and graph mapping are never adjusted to conceal
a mismatch. Only a passed report can set `status=ready` and add the dataset to
`registry.json`. Memory and disk measurements are included in the final report.

For LDBC, `load_dataset.py` uses `ldbc_bulk.py` after the other four active
datasets are verified. The adapter preserves the published eight node and 23
relationship groups and rejects every bad entry. It stops only the dedicated
LDBC service, preserves its verified-empty initial store, uses a 40 GiB process
memory limit, imports into its default `neo4j` database, restarts that instance,
and applies the unchanged published schema one statement at a time. The source
record explains the 5.26 header/schema compatibility checks. A failed bulk store
is preserved and the original empty bootstrap restored; automatic retries never
overwrite that attempt.

## Deferred dataset

The user deferred Stack Overflow on 2026-11-15. Its downloaded answer and
question CSVs are truncated inside records even though their checksums match
the publisher. The publisher's Word document supplied the missing cleaner, but
that cleaner correctly rejected the incomplete input. Original files and the
diagnosis are retained. Stack Overflow is absent from the registry and has no
new database service. Complete inputs are required before resuming preparation.

## Application integration

The development app reads this registry and the instance statuses through
`agent/graphmine_agent/neo4j_registry.py`. Set
`GRAPHMINE_NEO4J_DATASETS_REGISTRY`, `GRAPHMINE_NEO4J_INSTANCES_ROOT` and
`GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE` in its private environment configuration.
A matching passed report is required before any connection is listed. Each
connection retains the app's read-only validation and resource limits; benchmark
snapshots carry load provenance and have no SQL enrichment or write path.

The old shared-store scripts are retained in `deploy/database-workspace/legacy/`.
The new preparer continues to use their byte-part assembler without opening the
old databases. The [workspace documentation](../../docs/DATABASE_CYPHER_WORKSPACE.md#benchmark-datasets-and-schemas)
explains configuration, UI behavior and verification commands. The runtime
registry and instance reports, not the presence of these tools, determine which
datasets have completed rollout.
