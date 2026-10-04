# GraphMine v1 deployment

The base setup runs as two processes on the GPU server: vLLM owns one physical GPU
and the API/GraphMine worker owns the other. The browser is served by the API
process and can be opened from a separate machine on a trusted private LAN.
The business-adapter pilot described next adds a local routing service.

## Business adapter user-testing pilot

The installed pilot on this host uses three processes:

- Existing vLLM FP8 server at `127.0.0.1:8001` for turn classification, planning
  and answers. Its process and model weights were retained during this deployment.
- `graphmine-pilot-router.service` at `127.0.0.1:8002` for the verified business
  routing adapter. It loads the pinned base and adapter locally, uses NF4 and
  greedy constrained decoding, and shares GPU 1 with native computations.
- `graphmine-pilot-api.service` serving the app at port `18000`, with the existing
  `.graphmine-v1` data root and API token. Both new services are installed as
  **user** services for `wajid`, with restart-on-failure enabled.

The authoritative pilot settings are in the existing ignored `agent/.env`:

```text
GRAPHMINE_ROUTER_BASE_URL=http://127.0.0.1:8002
GRAPHMINE_ROUTER_MODEL=graphmine-business-v1
GRAPHMINE_ROUTER_ADAPTER_SHA256=dd7017735094300c4a89f217cb094c0d8b9981d1c7d86182596a7a6f7ef5f4d6
GRAPHMINE_ROUTER_SUITE=/home/wajid/projects/graphDatabaseAgent/graphMine-repo/.graphmine-learning/adapter-business-suite-new-v1
GRAPHMINE_DEPLOYMENT_VERSION=business-v1-pilot.1
```

### Restart the stopped pilot

The pilot is stopped at the user's request. The API and router user services are
disabled for automatic startup, but remain installed and can be started manually.
The FP8 model server is also stopped. Saved chats, uploads, feedback, results,
model weights and the existing `agent/.env` are preserved. Training and evaluation
remain paused; the commands below start only the application and its models.

Run these commands on the GPU server as `wajid`.

In terminal 1, start the base model and keep this terminal open:

```bash
cd /home/wajid/projects/graphDatabaseAgent/graphMine-repo
./deploy/start-vllm.sh
```

Wait for vLLM to report `Application startup complete`. In terminal 2, start the
trained router and app:

```bash
systemctl --user start graphmine-pilot-router.service graphmine-pilot-api.service
journalctl --user -u graphmine-pilot-router.service -u graphmine-pilot-api.service -f
```

Allow the router's weights to finish loading. Pressing Ctrl+C in terminal 2 exits
the log viewer without stopping these two services. Open
`http://10.33.76.25:18000` on the private LAN, `http://100.102.13.108:18000` over
Tailscale, or `http://127.0.0.1:18000` on the server. Use the existing API token in
the UI gear menu if requested. The start scripts load the existing configuration;
do not rerun `configure-v1.sh` when resuming this installation.

To stop everything again:

```bash
systemctl --user stop graphmine-pilot-api.service graphmine-pilot-router.service
```

Then press Ctrl+C in terminal 1 to stop vLLM and release its GPU memory. Closing
the browser alone does not stop the application.

Inspect and operate the installed pilot:

```bash
systemctl --user status graphmine-pilot-api.service graphmine-pilot-router.service
journalctl --user -u graphmine-pilot-api.service -u graphmine-pilot-router.service -n 100

# After changing app configuration; wait for active user work to finish first.
systemctl --user restart graphmine-pilot-api.service

# Router restart reloads its verified weights; allow startup to finish.
systemctl --user restart graphmine-pilot-router.service
```

User-service definitions are in `~/.config/systemd/user/`, with copies in
`.graphmine-learning/pilot-deployment-v1/units/`. They are currently disabled for
automatic startup. Manual `systemctl --user start` still works. The FP8 endpoint
must also be running; start it with `deploy/start-vllm.sh` using the existing
environment. Do not start a second copy while port 8001 is occupied.
For a manual router start without systemd, use `deploy/start-router.sh` only when
its service is stopped and port 8002 is free.

The router uses the existing internal LLM API key, listens only on loopback, and
checks the saved adapter hash, training configuration, base files and runtime
prompt/schema. The API verifies the router's model identity and adapter hash on
health checks and responses. An unavailable or mismatched adapter produces a
visible error; it does not silently substitute the old routing model.

The deployment backup is `.graphmine-learning/pilot-deployment-v1/`:
`agent-before.sqlite3` is an online SQLite backup, `agent.env.before` is the prior
private configuration, and `before.json`/`cutover.json` record the state and
preservation checks. Original uploaded files and histories remain in place.
Do not restore the old database just to switch model versions: that would discard
new pilot records.

To use the original routing model while keeping the new UI and all collected
data, set `GRAPHMINE_ROUTER_BASE_URL=` and `GRAPHMINE_DEPLOYMENT_VERSION=base` in
`agent/.env`, then restart **only** `graphmine-pilot-api.service`. The unused router
may subsequently be stopped to release its GPU memory. The API unit's `Wants`
relationship can start that router again on a later API start; remove that
relationship if permanently retiring the adapter service. Restoring the business
settings above and restarting the API reconnects the trained candidate.

See the [user guide](../agent/README.md#user-testing-pilot-business-v1-pilot1)
for exact UI steps, command examples, feedback exports and known limitations.

## Local acceptance deployment

```bash
deploy/validate-v1.sh
deploy/configure-v1.sh --origin http://GPU_SERVER_LAN_IP:8000

# terminal 1
deploy/start-vllm.sh

# terminal 2
deploy/start-agent.sh

# terminal 3, after both services are ready
.venv/bin/graphmine-agent smoke-test
```

The generated `agent/.env` contains a private API token and is ignored by Git.
Use the UI gear button to enter that token. Do not send it in a URL.

If port 8000 is already occupied, choose one port consistently, for example
`deploy/configure-v1.sh --port 18000 --origin http://GPU_SERVER_LAN_IP:18000`,
and browse to that origin. The configurator discovers both GPU UUIDs, assigns
the first to Qwen and the second to GraphMine, generates a random API token,
and writes the environment file with mode `0600`.

## Persistent installation

The supplied systemd units expect:

- repository: `/opt/graphmine`;
- service account: `graphmine`;
- environment: `/etc/graphmine/graphmine.env`;
- writable state and model cache: `/var/lib/graphmine`.

Create those locations, copy the repository and environment file, then install
the two unit files. Keep the environment file owned by root with mode `0600`
and the state directory owned by the service account. The API unit starts after
and requires the vLLM unit.

Generate the production environment after the repository is installed at
`/opt/graphmine`, using `--data-root /var/lib/graphmine` and an output file that
can then be installed as `/etc/graphmine/graphmine.env`. `HF_HOME`,
`XDG_CACHE_HOME`, and `VLLM_CACHE_ROOT` are placed below the same writable data
root because the hardened services cannot read a user home directory. Download
or copy the model cache there as the `graphmine` service account before the
first unattended start.

After installing the units, verify process and application readiness:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now graphmine-vllm.service graphmine-agent.service
sudo systemctl status graphmine-vllm.service graphmine-agent.service
curl -H "Authorization: Bearer $GRAPHMINE_API_TOKEN" \
  http://127.0.0.1:8000/api/health
```

## Network security

The built-in server is HTTP. It is suitable only for a trusted private LAN.
For any shared or untrusted network, put a TLS reverse proxy in front of port
8000, allow only the reverse proxy to reach the API, and preserve WebSocket
upgrade headers. `nginx-graphmine.conf.example` is a starting point; replace
the hostname and certificate paths before enabling it.

Use a host firewall to expose only the TLS listener to research clients. vLLM
binds to loopback and must never be exposed directly.

## Backup and recovery

The data root contains SQLite metadata plus uploaded files, normalized graphs,
commands, logs, and results. For a consistent backup, stop the API service or
use SQLite's online backup facility, then copy the complete data root. Test a
restore into a separate directory before relying on the backup.

The simplest offline backup sequence is:

```bash
sudo systemctl stop graphmine-agent.service
sudo tar --xattrs --acls -C /var/lib -czf /SAFE_DESTINATION/graphmine-data.tgz graphmine
sudo systemctl start graphmine-agent.service
sha256sum /SAFE_DESTINATION/graphmine-data.tgz
```

Restore only while the API is stopped, into an empty staging path first. Check
the archive hash, ownership, SQLite readability, uploaded-file hashes, and a
smoke execution before replacing the production data root. The model cache can
be rebuilt, but SQLite, session files, and job workspaces are authoritative
state and must be restored together.

Queued jobs are resumed after restart. Jobs that were running or interpreting
when the process stopped are marked failed with `server_restarted`; GraphMine
does not silently repeat potentially expensive work.

## Operations

- Readiness: authenticated `GET /api/health`.
- Counters: authenticated `GET /api/metrics`.
- API schema: `/docs` or `/openapi.json`.
- Logs: `journalctl -u graphmine-vllm -u graphmine-agent`.
- GPU ownership: `nvidia-smi` should show vLLM on the configured LLM UUID and
  GraphMine jobs only on the configured compute UUID.
- Rotate the API token by updating the environment file and restarting only the
  API service.
