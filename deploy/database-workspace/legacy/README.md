# Retired shared benchmark import path

These scripts prepared PostgreSQL tables and a single Neo4j store with `GM_*`
dataset labels. They are retained for reference and recovery of that older
installation. Do not run them to load or publish isolated benchmark instances.
Use `deploy/neo4j-datasets/` for the current development workflow.

The new preparer still reuses `benchmark_import.Builder.source()` to assemble
verified byte-split files, as required by the migration specification. It uses
that method without invoking the constructor or opening either old database.
Its source receipts and the new preparer's content checks remain in force.

The existing PostgreSQL and Neo4j stores, old prepared imports, and raw downloads
are preserved. Moving these scripts does not remove or migrate those stores.
