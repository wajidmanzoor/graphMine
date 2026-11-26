# Step 2: Neo4j inventory

Read-only inventory of commit 2ed3292a, completed 2026-11-26 before application
changes. The user approved Step 3 after receiving this inventory. This record
preserves that inventory; it does not claim later implementation is complete.

## Application paths

Paths below are relative to `agent/graphmine_agent/`.

| Paths | Responsibility |
| --- | --- |
| `config.py`, `neo4j_registry.py`, `benchmark_mappings.py` | Environment/configuration, verified localhost registry, endpoint matching |
| `database_sources.py`, `database_connections.py`, `database_pools.py` | URI reads, password validation, private-network policy, driver creation, owner-scoped pools |
| `database_queries.py`, `neo4j_schema.py`, `database_schema.py` | Read Cypher, EXPLAIN, schema sampling; READ_ACCESS with explicit transactions |
| `database_datasets.py`, `benchmark_datasets.py`, `data_sources.py` | Dataset and source inventories |
| `database_sync.py`, `database_reconciliation.py` | Explicit SQL-to-Neo4j writes, constraints, creates, updates, deletes |
| `database_jobs.py`, `database_job_context.py` | Query/sync jobs, progress, cancellation, commit boundaries |
| `connectors.py`, `managed_connectors.py` | Additional HTTP Neo4j Query API path at `/db/{database}/query/v2`, using read access |
| `mcp_database.py` | API-backed discovery, queries, jobs, snapshots, dataset operations, exports |
| `admin_monitor.py` | TCP checks of Neo4j endpoints |
| `backend_learning/benchmark_graphs.py`, `benchmark_profiles.py` | Neo4j-derived benchmark graph extraction |
| `datasets.py`, `dataset_index.py`, `query_previews.py`, `query_results.py`, `table_artifacts.py`, `graph_store.py` | Snapshot/dataset/file persistence and provenance |
| `analytics.py`, `workflow_index.py`, `result_index.py`, `analytics_exports.py`, `history.py`, `capture.py` | Workflows, results, indexes, exports, history and capture copies |

The UI implementation is under `static/`, including `analytics-connection-settings.js`,
`analytics-connectors.js`, `analytics-data-source.js`, `analytics-database.js`,
`analytics-source-settings.js`, `analytics-table-mappings.js`,
`analytics-benchmark-datasets.js`, `analytics-query-editor.js`, and
`analytics-query-drafts.js`. `agent/frontend` also contains generated contracts
and frontend checks.

## Deployment and runtime paths

- `deploy/neo4j-datasets/registry.json` and `common.py`: localhost endpoints,
  instance layout, credential references, direct drivers.
- `create_instance.py`: creates configuration/stores, initializes credentials,
  starts/enables units, checks connectivity.
- `load_dataset.py`, `ldbc_bulk.py`: data writes, offline import, unit start/stop.
- `verify_dataset.py`, `parameter_values.py`: connection and query checks.
- `prepare_import_dir.py`: local file preparation; no database connection.
- `cypher.py`, `source_pages.py`, dataset `load/`, `queries/`, and `reference/`
  directories: parsers, archived source material, loading/query programs.
- `deploy/database-workspace/init_demo.py`, `compose.yaml`: local endpoints,
  credential generation, service definitions.
- `deploy/database-workspace/legacy/`: preserved graph bulk loader and SQL/input
  preparation; `build-benchmark-graphs.py` directly connects and starts/stops the
  old local Neo4j service.
- `deploy/start-agent.sh`, `configure-v1.sh`, `install-user-services.py`,
  `environments.py`: environment generation/loading and application launchers.
- Installed units: `~/.config/systemd/user/graphmine-neo4j*.service`.
- Private runtime helpers: `.database-workspace/deployment/start-branch.sh`,
  `serve-branch.py`, service templates and `neo4j-browser-proxy.py`. The proxy
  forwards local HTTP/Bolt and has a localhost HTTP endpoint literal.

Current sources files are `graphmine-data/environments/config/{production,testing,devlopment}-datasets.json`.
They configure `local-transfers` at bolt://127.0.0.1:17700. Its password reference
is GRAPHMINE_NEO4J_TRANSFERS_DEMO_PASSWORD. Benchmark password references and the
configured-source credentials reside in private `.database-workspace/demo.env`.
No credential values were copied into this inventory.

The registry contains Yelp (17701), MovieLens 32M (17702), MovieLens Genome
(17703), and LDBC SNB (17706). All four use bolt://127.0.0.1.

## Stored record types

Production application root: `/data/labdata/wajid/graphmine_data/store`.
Development and testing have separate roots under `graphmine_data/environments/`.

| Record | Storage |
| --- | --- |
| Configured connections | Environment source JSON and dataset registry |
| Account connections | `database-connections/<owner-hash>/*.json`; zero at inspection |
| Import connectors | Configured connector file and `agent.sqlite3:user_connectors`; zero account rows |
| Curated database datasets | Registry; `neo4j-instances/<slug>/status.json`, verification reports and physical stores; original downloads under `graphmine_data/datasets` |
| Query snapshots | `agent.sqlite3:query_previews`, `query_preview_blobs`, associated indexes |
| Saved datasets | `dataset_versions`, `dataset_catalog`, `dataset_summaries`; 34 versions across 33 datasets |
| Synced graph state | Neo4j nodes/relationships with gm_* provenance; receipts in `database_jobs.document` |
| Saved queries | 52 historical `query_library` rows remain; current code removed that UI/API and does not create the table in new stores |
| Query drafts | Browser localStorage, scoped by identity, connection, dataset, conversation/input |
| Imported files | `agent.sqlite3:files`; `sessions/<session>/files/<file>/`, with provenance |
| Workflows | `analytics/workflows.sqlite3`, 47 workflow records; indexed summaries/reviewed examples |
| Results | `analytics/<workflow>/revision-*/inputs.json`, `step-*.json`, `result.json`, views/indexes, exports; legacy SQL results table |
| Other copies/references | Project items, history, captures, caches, backups |

Counts are totals, not assertions that every dataset or workflow derives from
Neo4j. Provenance must decide which records receive a backend tag.

## Services and memory

Seven services were active/enabled: the four registry databases, Transfers demo,
`graphmine-neo4j.service`, and `graphmine-neo4j-browser.service`. OnTime was
inactive/disabled with a preserved partial store. Do not interpret a retained
unit or store as a verified dataset.

RSS across those service processes was approximately 16.158 GiB. `free -h`
reported 251 GiB total, 73 GiB used, 120 GiB free and 177 GiB available. This is an
inventory snapshot, not the required measurement immediately before parking.

The wildcard `graphmine-neo4j-*` misses `graphmine-neo4j.service`; the latter must
also be parked to achieve zero local database RAM. The browser unit is a proxy,
not a Bolt server. Local management must distinguish it when waiting for Bolt.

## Write paths and documentation

SQL synchronization/reconciliation is an explicit graph write path, including
constraint creation, node/relationship creation, property/label changes and
deletes. Dataset loaders and administrative bulk imports also write. Interactive
Cypher, schema sampling and HTTP connector imports enforce reads. No IU write or
remote SSH command was performed during this inventory.

Documentation: `README.md`, `docs/DATABASE_CYPHER_WORKSPACE.md`,
`docs/ANALYTICS_WORKSPACE.md`, `docs/ADMIN_CONSOLE.md`,
`docs-internal/ENVIRONMENTS.md`, `docs-internal/WORKSPACE_IMPROVEMENTS.md`,
`deploy/neo4j-datasets/README.md`, `deploy/database-workspace/legacy/README.md`.
Configuration examples are in `agent/.env.example`.
