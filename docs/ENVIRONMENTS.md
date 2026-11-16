# Development, testing, and production

GraphMine and Dataset Studio live in this repository and move through the same
commits. The branch name `devlopment` intentionally follows the requested name.

| Branch | Purpose |
| --- | --- |
| `devlopment` | Make and commit changes here. |
| `testing` | The exact candidate currently being validated. |
| `production` | The version served to users. |
| `main` | The last successfully promoted version. |

All four branches start at the same baseline. Promotions use fast-forward
updates, preserving the exact tested commit. Existing feature history remains
available; model weights, user data, credentials, and virtual environments are
not committed.

## Installed host layout

The workspace root is `/home/wajid/projects/graphDatabaseAgent`.

| Environment | Code directory | Agent / Studio ports | Access |
| --- | --- | --- | --- |
| Production | `graphMine-production` | 18000 / 8877 | Existing public HTTPS routes |
| Development | `graphMine-database-cypher` | 18002 / 8879 | Loopback; SSH forwarding |
| Testing | `graphMine-testing` | 18001 / 8878 | Loopback; SSH forwarding |

`graphMine-runtime-20261116-views` is the detached, pinned native-runtime
checkout for the completed CPU graph-view migration. Its compiled engine and
execution evidence are promoted together with the application. The existing
`graphMine-repo` checkout still supplies the analytics Python and vLLM
environments. Do not develop in these pinned checkouts or install packages into
their runtime environments. Native engine changes need a separately built and
verified runtime; changing an app branch alone does not replace native binaries.

The new native build keeps its Kokkos/KokkosKernels dependencies under
`library/build/native-dependencies/` in its pinned checkout. These dependencies
must remain available for rebuilding; the previous temporary installation under
`/tmp/pggc-deps` had been cleared. The release's build settings, dependency
versions, source hashes and validation reports are recorded in
`validation/native_views_release/`. Later GPU graph-view migration steps remain
separate work; this release retains the existing GPU adapters.

Each application environment has its own Python environment, data store,
accounts, captures, history, backups, Studio workspace, and login cookie names.
All three environments use the same five published, isolated read-query
datasets: Transfers demo, Yelp, MovieLens 32M, MovieLens Tag Genome and LDBC SNB
SF100 BI. Each environment reads the registry from its own checkout and keeps
application accounts, conversations and snapshots separate. The demo's optional
SQL enrichment uses `graphmine_reader`; production write credentials are not
copied into testing or development.

`GRAPHMINE_DATABASE_DATASET_ALLOWLIST` selects those five entries and enables
the single dataset picker. `GRAPHMINE_DATABASE_CREDENTIALS_FILE` and
`GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE` reference the private, owner-only
`.database-workspace/demo.env`. No credentials are stored in Git. A registry
entry is queryable only after its dataset verification passes. See
[Database workspace](DATABASE_CYPHER_WORKSPACE.md#benchmark-datasets-and-schemas)
for ports, storage, loading gates, paused OnTime and deferred Stack Overflow.

Production keeps its existing `/data/labdata/wajid/graphmine_data/store` data.
Studio's production workspace and dataset root are under
`/data/labdata/wajid/graphmine_data/dataset-studio/`. Development and testing data
are under `graphmine_data/environments/devlopment/` and
`graphmine_data/environments/testing/`. Raw benchmark downloads and model weights
remain shared files on the data disk.

Private host configuration, the installed controller, and deployment state live
under `graphmine-data/environments/`, outside the Git checkout. The installed
command is:

```sh
/home/wajid/projects/graphDatabaseAgent/graphmine-data/environments/gm-env status
```

For the shorter commands below, define a shell alias:

```sh
alias gm-env=/home/wajid/projects/graphDatabaseAgent/graphmine-data/environments/gm-env
```

Each checkout also needs its locked Node dependencies in both `agent/frontend`
and `agent/visualization` (`npm ci` in each directory). The visualization
dependencies are needed by the running application as well as tests.

The configuration selects exact code, Python, service, and storage paths.
`deploy/environments.py` validates that writable paths, ports, and services do
not overlap. A developer shell cannot override its GraphMine storage settings.

## Workflow

1. Work in `graphMine-database-cypher` on `devlopment`; Studio code is its
   `dataset-studio/` subdirectory. Commit your changes and push `devlopment`.
2. Use `gm-env start-dev` for private UI development and `gm-env stop-dev` when
   finished. Development disables live model calls and hides GPUs by default.
3. Schedule downtime for users, then run `gm-env begin-testing --commit devlopment`.
   The controller checks for clean checkouts and active work, advances testing,
   stops the production and development apps, and starts the testing apps.
   Production URLs are unavailable during this interval.
4. Exercise the private testing apps. They use the existing vLLM server and
   model weights with separate application data. Run `gm-env verify-testing` to
   execute the configured automated checks. A failed check prevents promotion.
5. After the candidate passes both automated checks and your manual acceptance,
   run `gm-env promote --push`. It backs up production application and Studio
   data, stops testing, advances production to the exact verified commit,
   starts production, checks HTTP health, advances `main`, and atomically pushes
   the four environment branches.
6. If testing fails, use `gm-env cancel-testing` to stop testing and resume the
   unchanged production release.

The controller never stops the vLLM, PostgreSQL, or Neo4j services. The model
stays loaded in GPU memory throughout ordinary app testing and deployment. A
machine reboot is unnecessary. Changes to inference dependencies, weights, or
the native runtime need their own maintenance procedure.

Testing is private by default. For example, forward ports 18001 and 8878 over
SSH and open the forwarded localhost URLs. The production Cloudflare routes
continue to target ports 18000 and 8877; they are never redirected to test data.

## Private environment sign-in

Development and testing have separate accounts and initially contain no users.
Create an administrator in each environment before signing into its private UI
(the command prompts for a password). Dataset Studio accepts that environment's
GraphMine accounts.

```sh
cd /home/wajid/projects/graphDatabaseAgent/graphMine-database-cypher
GRAPHMINE_AGENT_DATA_ROOT=/data/labdata/wajid/graphmine_data/environments/devlopment/store \
  .venv/bin/python -m graphmine_agent accounts create wajid --admin

cd /home/wajid/projects/graphDatabaseAgent/graphMine-testing
GRAPHMINE_AGENT_DATA_ROOT=/data/labdata/wajid/graphmine_data/environments/testing/store \
  .venv/bin/python -m graphmine_agent accounts create wajid --admin
```

Production accounts and existing Studio sign-ins are preserved.

## Database changes and recovery

Validate schema changes against disposable data before promotion. Code rollback
alone may not be compatible with a migrated production database. If production
startup fails after promotion, the controller retains the previous commit and
backup location in its testing-session record and does not overwrite live data
automatically. Review compatibility and writes before restoring a backup.

The installed controller is a separate copy so editing its source cannot change
an in-progress deployment. Deploy controller updates deliberately after their
tests pass. Host environment files contain credentials and stay outside Git.

The future Studio design that reads original captures and stores edits by
reference is recorded in `latter plans.md`; this environment setup does not
implement that separate feature.

## Baseline validation limitations

The initial full agent regression run identified eight existing failures in
`agent/tests/test_native_uploads.py`, reproduced against the original deployed
checkout. Those tests require the older native cuDF upload path; the current
CSV upload path uses `csv_ingestion.py`. This environment change preserves the
current behavior. Resolve that test/implementation mismatch separately; the
full agent suite is not currently green.

The deployment gate runs the controller, account, capture, backup/recovery,
Studio exchange, Dataset Studio, chart compiler, and frontend checks. Hardware
and disposable-database integration tests require their separate opt-in setup.
