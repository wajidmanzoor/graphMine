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

`graphMine-repo` is a detached, pinned native-runtime checkout. Its compiled
engine, analytics Python environment, and vLLM environment support production.
Do not use it as a development checkout or install packages into its runtime
environments. Native engine changes need a separately built and verified
runtime; changing an app branch alone does not replace native binaries.

Each application environment has its own Python environment, data store,
accounts, captures, history, backups, Studio workspace, and login cookie names.
Development and testing start with empty database-connection configurations.
Use disposable test databases or separately provisioned read-only benchmark
connections; never copy production write credentials into these configurations.

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
