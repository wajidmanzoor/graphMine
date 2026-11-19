"""Server-side monitoring: bounded probes, durable incidents and sampled history."""

import asyncio
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import admin_settings
from .admin_summary import percentile
from .identity import AccountError
from .llm_power import server_root


def safe_address(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    return urlunsplit((parsed.scheme, host + (f":{parsed.port}" if parsed.port else ""), parsed.path, "", ""))


async def command(*args, timeout=3, env=None):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise OSError("Command is unavailable")
        return output.decode(errors="replace")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def redacted_log(raw):
    lines = []
    for line in raw.splitlines()[-200:]:
        # Arbitrary tracebacks and model logs can contain private user text.
        # Extract only known operational fields rather than guessing secret names.
        access = re.search(r'"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (/[^?\s"]*)(?:\?[^\s"]*)? HTTP/[0-9.]+" (\d{3})', line)
        lifecycle = re.search(r'(Application startup complete|Application shutdown complete|Waiting for application startup|Waiting for application shutdown|Started server process|Finished server process|Shutting down)\b', line)
        date = re.match(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+", line)
        timestamp = date.group(0) if date else ""
        if access:
            lines.append(f"{timestamp} {access[1]} {access[2]} {access[3]}")
        elif lifecycle:
            lines.append(f"{timestamp} {lifecycle[1]}")
        else:
            lines.append("[Application detail omitted: it may contain private data]")
    return "\n".join(lines)


class Monitor:
    def __init__(self, runtime, *, clock=time.time, timeout=3):
        self.runtime, self.clock, self.timeout = runtime, clock, timeout
        self.started = clock()
        self.lock = asyncio.Lock()
        self.cached = None
        self.task = self.selftest_task = None
        self.http = httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False)
        with runtime.database._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS admin_incidents (
                    id INTEGER PRIMARY KEY, service TEXT NOT NULL, status TEXT NOT NULL,
                    summary TEXT NOT NULL, opened_at REAL NOT NULL, closed_at REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS admin_incidents_open ON admin_incidents(service) WHERE closed_at IS NULL;
                CREATE TABLE IF NOT EXISTS admin_warning_since (service TEXT PRIMARY KEY, since REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_gpu_samples (ts REAL NOT NULL, gpu INTEGER NOT NULL,
                    used_bytes INTEGER NOT NULL, total_bytes INTEGER NOT NULL, model_bytes INTEGER,
                    PRIMARY KEY(ts,gpu));
                CREATE TABLE IF NOT EXISTS admin_monitor_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("UPDATE admin_monitor_state SET value=json_set(value,'$.status','interrupted') WHERE key='selftest' AND json_extract(value,'$.status')='running'")

    def start(self):
        self.task = asyncio.create_task(self._poll())

    async def _poll(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self.snapshot()
            except Exception:
                # One failed sample must not stop all future incident monitoring.
                continue

    async def close(self):
        tasks = [task for task in (self.task, self.selftest_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()

    async def probe(self, key, name, work):
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(work(), self.timeout)
            return {"id": key, "name": name, "checked_at": self.clock(),
                    "response_ms": None if result.get("status") == "unavailable" else (time.monotonic() - started) * 1000, **result}
        except TimeoutError:
            return {"id": key, "name": name, "status": "critical", "reason": f"Check timed out after {self.timeout:g} seconds", "checked_at": self.clock(), "response_ms": None}
        except (OSError, ValueError, httpx.HTTPError, KeyError, TypeError):
            return {"id": key, "name": name, "status": "critical", "reason": "The service could not be reached or returned an invalid response", "checked_at": self.clock(), "response_ms": None}

    async def unit(self, service):
        key = {"agent": "GRAPHMINE_ADMIN_AGENT_UNIT", "model": "GRAPHMINE_ADMIN_MODEL_UNIT"}[service]
        name = os.getenv(key, "graphmine-agent.service" if service == "agent" else "graphmine-vllm.service")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", name):
            return None
        try:
            raw = await command("systemctl", "--user", "show", name, "--property=MainPID,ActiveState,WorkingDirectory")
            data = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            if Path(data.get("WorkingDirectory", "/")).resolve() != self.runtime.settings.repository_root.resolve():
                return None
            if service == "agent" and int(data.get("MainPID", 0)) != os.getpid():
                return None
            return {"unit": name, "active": data.get("ActiveState"), "pid": int(data.get("MainPID", 0))}
        except (OSError, ValueError, TimeoutError):
            return None

    async def agent(self):
        started = time.monotonic()
        with self.runtime.database._connect() as db:
            db.execute("SELECT 1").fetchone()
        ping = (time.monotonic() - started) * 1000
        connections = None
        try:
            inodes = {os.readlink(p)[8:-1] for p in Path('/proc/self/fd').iterdir() if p.is_symlink() and os.readlink(p).startswith('socket:[')}
            sockets = [line.split() for name in ("tcp", "tcp6") for line in Path("/proc/net", name).read_text().splitlines()[1:]]
            local = [s for s in sockets if int(s[1].split(":")[1], 16) == self.runtime.settings.api_port and s[9] in inodes]
            if any(s[3] == "0A" for s in local):
                connections = sum(s[3] == "01" for s in local)
        except OSError:
            pass
        try:
            commit = (await command("git", "-C", str(self.runtime.settings.repository_root), "rev-parse", "--short=12", "HEAD")).strip()
        except (OSError, TimeoutError):
            commit = None
        return {"status": "healthy", "uptime_seconds": self.clock() - self.started,
                "database_ping_ms": ping,
                "open_connections": connections, "connections_reason": None if connections is not None else "No listener at the configured API port was found in this process",
                "connection_limit": 256 if self.runtime.settings.accounts_enabled else None,
                "commit": commit, "service": await self.unit("agent")}

    async def vllm(self):
        settings = self.runtime.settings
        if not settings.llm_enabled:
            return {"status": "unavailable", "reason": "The language model is disabled in this deployment"}
        root = server_root(settings.llm_base_url)
        headers = {"Authorization": "Bearer " + settings.llm_api_key}
        response = await self.http.get(root + "/metrics", headers=headers)
        response.raise_for_status()
        metrics = {}
        for line in response.text.splitlines():
            match = re.match(r"(vllm:[a-zA-Z0-9_:]+)(?:\{[^}]*\})?\s+([0-9.eE+-]+)(?:\s|$)", line)
            if match:
                value = float(match[2])
                if math.isfinite(value):
                    metrics[match[1]] = metrics.get(match[1], 0) + value
        power = self.runtime.llm_power.for_url()
        try:
            state = await power.refresh_status()
        except Exception:
            state = power.status()
        return {"status": "healthy", "address": safe_address(settings.llm_base_url), "power": state,
                "running": metrics.get("vllm:num_requests_running"), "waiting": metrics.get("vllm:num_requests_waiting"),
                "kv_cache_percent": metrics.get("vllm:kv_cache_usage_perc", metrics.get("vllm:gpu_cache_usage_perc", 0)) * 100
                    if "vllm:kv_cache_usage_perc" in metrics or "vllm:gpu_cache_usage_perc" in metrics else None,
                "service": await self.unit("model")}

    async def gpus(self):
        raw = await command("nvidia-smi", "--query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw", "--format=csv,noheader,nounits")
        items = []
        number = lambda value: float(value.strip()) if re.fullmatch(r"\s*[0-9.]+\s*", value) else None
        for row in csv.reader(raw.splitlines()):
            if len(row) != 8:
                continue
            used, total, util, temp, power = [number(x) for x in row[3:]]
            items.append({"index": int(row[0]), "uuid": row[1].strip(), "name": row[2].strip(),
                          "used_bytes": int(used * 2**20) if used is not None else None,
                          "total_bytes": int(total * 2**20) if total is not None else None,
                          "utilisation": util, "temperature": temp, "power_watts": power})
        processes = {}
        try:
            raw = await command("nvidia-smi", "--query-compute-apps=gpu_uuid,process_name,used_gpu_memory", "--format=csv,noheader,nounits")
            for row in csv.reader(raw.splitlines()):
                if len(row) == 3 and "vllm" in row[1].lower() and number(row[2]) is not None:
                    processes[row[0].strip()] = processes.get(row[0].strip(), 0) + int(number(row[2]) * 2**20)
        except (OSError, TimeoutError):
            pass
        for item in items:
            item["model_bytes"] = processes.get(item["uuid"])
        leases = self.runtime.analytics.scheduler.snapshot()
        by_allocation = {(w.get("allocation") or {}).get("id"): w for w in self.runtime.analytics._all() if w.get("status") == "running"}
        with self.runtime.database._connect() as db:
            for lease in leases:
                workflow = by_allocation.get(lease["id"], {})
                owner = db.execute("SELECT a.username FROM sessions s JOIN accounts a ON a.id=s.owner_id WHERE s.id=?", (workflow.get("session_id"),)).fetchone()
                lease.update(username=owner[0] if owner else None, workflow_id=workflow.get("id"),
                             operations=[s["operation"] for s in workflow.get("validation", {}).get("plan", {}).get("steps", [])], started_at=workflow.get("started_at"))
        return {"status": "healthy" if items else "unavailable", "reason": None if items else "nvidia-smi returned no GPUs",
                "items": items, "leases": leases}

    async def disk(self):
        data = shutil.disk_usage(self.runtime.settings.data_root)
        percent = data.used / data.total * 100
        return {"status": "critical" if percent >= 90 else "warning" if percent >= 80 else "healthy",
                "used_bytes": data.used, "total_bytes": data.total, "percent": percent,
                "reason": "Disk usage is over 90%" if percent >= 90 else "Disk usage is over 80%" if percent >= 80 else None}

    async def http_check(self, url):
        if not url:
            return {"status": "unavailable", "reason": "No public URL is configured"}
        response = await self.http.get(url)
        return {"status": "healthy" if 200 <= response.status_code < 400 else "critical",
                "http_status": response.status_code, "address": safe_address(url)}

    async def studio(self):
        result = await self.http_check(os.getenv("GRAPHMINE_STUDIO_HEALTH_URL", "http://127.0.0.1:8877/"))
        from .studio_sync import auth_directory
        try:
            path = auth_directory(self.runtime.settings) / "users.json"
            data = json.loads(path.read_text())
            result["linked_accounts"] = sum(bool(user.get("graphmine")) for user in data.get("users", {}).values())
        except (OSError, ValueError, TypeError):
            result.update(linked_accounts=None, accounts_reason="Studio's account file is unavailable")
        return result

    async def tcp(self, address, default_port):
        target = urlsplit(address)
        _, writer = await asyncio.open_connection(target.hostname, target.port or default_port)
        writer.close()
        await writer.wait_closed()
        return {"status": "healthy", "check": "TCP connection", "address": safe_address(address)}

    async def databases(self):
        path = self.runtime.settings.database_path
        with self.runtime.database._connect() as db:
            db.execute("SELECT 1").fetchone()
        size = sum(p.stat().st_size for p in (path, Path(str(path) + "-wal"), self.runtime.analytics.path) if p.exists())
        directory = self.runtime.settings.backup_directory
        last = None
        if directory and directory.is_dir():
            manifests = sorted(directory.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
            if manifests:
                last = {"name": manifests[-1].parent.name, "created_at": manifests[-1].stat().st_mtime,
                        "verified": None, "reason": "Run Verify to check this snapshot's current contents"}
        return {"status": "healthy", "sqlite_bytes": size, "slow_queries": None,
                "slow_queries_reason": "SQLite slow-query instrumentation is not installed", "last_backup": last}

    async def snapshot(self, *, force=False):
        async with self.lock:
            if self.cached and not force and self.clock() - self.cached["checked_at"] < 10:
                return self.cached
            checks = [("agent", "GraphMine agent", self.agent), ("vllm", "vLLM", self.vllm),
                      ("gpus", "GPUs", self.gpus), ("disk", "Disk", self.disk),
                      ("databases", "Databases", self.databases), ("studio", "Dataset Studio", self.studio),
                      ("tunnel-graphmine", "Cloudflare · GraphMine", lambda: self.http_check(os.getenv("GRAPHMINE_PUBLIC_URL"))),
                      ("tunnel-studio", "Cloudflare · Studio", lambda: self.http_check(os.getenv("GRAPHMINE_STUDIO_PUBLIC_URL")))]
            try:
                from .database_sources import configured, source_secret
                from .neo4j_registry import sources
                inventory = configured(self.runtime.settings) + sources(self.runtime.settings)
                for source in inventory:
                    if source.neo4j_uri:
                        checks.append(("neo4j-" + source.id, "Neo4j · " + source.name, lambda s=source: self.tcp(s.neo4j_uri, 7687)))
                    if source.sql_type == "postgres":
                        dsn = source_secret(source, source.sql_dsn_env)
                        checks.append(("postgres-" + source.id, "Postgres · " + source.name, lambda uri=dsn: self.tcp(uri, 5432)))
            except (ValueError, OSError, AccountError):
                checks.append(("database-registry", "Database registry", lambda: self._unavailable("Database inventory is unavailable")))
            if not any(k.startswith("neo4j-") for k, _, _ in checks):
                checks.append(("neo4j", "Neo4j datasets", lambda: self._unavailable("No Neo4j datasets are configured")))
            if not any(k.startswith("postgres-") for k, _, _ in checks):
                checks.append(("postgres", "Postgres", lambda: self._unavailable("No Postgres source is configured")))
            results = await asyncio.gather(*(self.probe(*check) for check in checks))
            power = self.runtime.llm_power.for_url()
            gpu_data = next(c for c in results if c["id"] == "gpus")
            model_bytes = sum(g.get("model_bytes") or 0 for g in gpu_data.get("items", [])
                              if g["uuid"] == self.runtime.settings.llm_gpu_uuid or not self.runtime.settings.llm_gpu_uuid and g["index"] == 0)
            if model_bytes and self.runtime.settings.llm_enabled and not power.enabled:
                results.append({"id": "model-memory", "name": "Model memory", "status": "warning", "checked_at": self.clock(),
                                "reason": f"vLLM holds {model_bytes / 2**30:.2f} GB on the GPU while sleep mode is off", "link": "model"})
            elif gpu_data["status"] == "healthy":
                results.append({"id": "model-memory", "name": "Model memory", "status": "healthy", "checked_at": self.clock()})
            self.persist(results)
            self.cached = {"checked_at": self.clock(), "checks": results,
                           "healthy": sum(r["status"] == "healthy" for r in results),
                           "attention": sum(r["status"] in {"critical", "warning"} for r in results),
                           "unavailable": sum(r["status"] == "unavailable" for r in results),
                           "incidents": self.incidents(), "selftest": self.state("selftest")}
            return self.cached

    async def _unavailable(self, reason):
        return {"status": "unavailable", "reason": reason}

    def persist(self, checks):
        now = self.clock()
        with self.runtime.database._connect() as db:
            for check in checks:
                key, status = check["id"], check["status"]
                if status == "warning":
                    db.execute("INSERT OR IGNORE INTO admin_warning_since VALUES (?,?)", (key, now))
                    since = db.execute("SELECT since FROM admin_warning_since WHERE service=?", (key,)).fetchone()[0]
                else:
                    db.execute("DELETE FROM admin_warning_since WHERE service=?", (key,))
                    since = now
                if status == "critical" or status == "warning" and now - since >= 900:
                    db.execute("INSERT OR IGNORE INTO admin_incidents(service,status,summary,opened_at) VALUES (?,?,?,?)",
                               (key, status, check.get("reason") or check["name"] + " needs attention", now))
                elif status == "healthy":
                    db.execute("UPDATE admin_incidents SET closed_at=? WHERE service=? AND closed_at IS NULL", (now, key))
                for gpu in check.get("items", []) if key == "gpus" else []:
                    if gpu["used_bytes"] is not None and gpu["total_bytes"] is not None:
                        db.execute("INSERT OR REPLACE INTO admin_gpu_samples VALUES (?,?,?,?,?)",
                                   (now, gpu["index"], gpu["used_bytes"], gpu["total_bytes"], gpu.get("model_bytes")))
            db.execute("DELETE FROM admin_gpu_samples WHERE ts<?", (now - 86400,))

    def incidents(self):
        with self.runtime.database._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM admin_incidents ORDER BY opened_at DESC LIMIT 30")]

    def state(self, key):
        with self.runtime.database._connect() as db:
            row = db.execute("SELECT value FROM admin_monitor_state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_state(self, key, value):
        with self.runtime.database._connect() as db:
            db.execute("INSERT INTO admin_monitor_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    async def logs(self):
        unit = await self.unit("agent")
        if not unit:
            return {"lines": None, "reason": "This agent is not running in its configured systemd unit"}
        try:
            raw = await command("journalctl", "--user", "-u", unit["unit"], "-n", "200", "--no-pager", "--output=short-iso")
        except (OSError, TimeoutError):
            return {"lines": None, "reason": "The journal could not be read within three seconds"}
        return {"lines": redacted_log(raw), "reason": "Private payloads and credential-bearing lines are omitted"}

    async def restart(self, service, confirm):
        if confirm is not True:
            raise ValueError("Confirm the service restart.")
        unit = await self.unit(service)
        if not unit:
            raise AccountError("This service is not managed by this deployment's systemd unit.", "service_unavailable", 409)
        with self.runtime.database._connect() as db:
            self.runtime.accounts._audit(db, "service.restart_requested", service, before=unit, after={"state": "restart_requested"})
        try:
            await command("systemctl", "--user", "restart", "--no-block", unit["unit"])
        except (OSError, TimeoutError) as error:
            with self.runtime.database._connect() as db:
                self.runtime.accounts._audit(db, "service.restart_failed", service, before={"state": "restart_requested"}, after={"state": "command_failed"})
            raise AccountError("Systemd did not accept the restart; check Health before retrying.", "restart_failed", 503) from error
        if service == "model":
            # The new process reads the same override table in start-vllm.sh.
            desired = admin_settings.load(self.runtime.settings, self.runtime.database)
            from dataclasses import replace
            admin_settings.apply_live(self.runtime, replace(self.runtime.settings, llm_sleep_mode=desired.llm_sleep_mode))
            manager = self.runtime.llm_power.for_url()
            manager.configured = manager.enabled = desired.llm_sleep_mode
            manager.sleeping = None
        with self.runtime.database._connect() as db:
            self.runtime.accounts._audit(db, "service.restart_queued", service, before={"state": unit["active"]}, after={"state": "restart_queued"})
        return {"status": "restart_queued", "unit": unit["unit"], "reason": "Check Health for the result; existing connections may close"}

    async def model(self):
        health = await self.snapshot()
        settings = self.runtime.settings
        desired = admin_settings.load(settings, self.runtime.database)
        now = self.clock()
        from datetime import datetime, timezone
        day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.runtime.database._connect() as db:
            calls = [json.loads(r[0]) for r in db.execute("SELECT payload FROM conversation_events WHERE type='workflow.diagnostics' AND created_at>=?", (day,))]
            wakes = db.execute("SELECT count(*) FROM admin_activity WHERE action='model.wake' AND at>=?", (day,)).fetchone()[0]
            busy = db.execute("SELECT count(*) FROM events WHERE type='error' AND ts>=? AND outcome IN ('concurrency_limit','llm_busy')", (datetime.fromisoformat(day).timestamp(),)).fetchone()[0]
            history = [dict(row) for row in db.execute("SELECT * FROM admin_gpu_samples WHERE gpu=0 AND ts>=? ORDER BY ts", (now - 86400,))]
        durations = [c["seconds"] * 1000 for c in calls if isinstance(c.get("seconds"), (float, int))]
        generation = sum((c.get("usage") or {}).get("completion_tokens", 0) or 0 for c in calls)
        gpu = next((c for c in health["checks"] if c["id"] == "gpus"), {})
        model_gpu = next((g for g in gpu.get("items", []) if g["uuid"] == settings.llm_gpu_uuid or not settings.llm_gpu_uuid and g["index"] == 0), None)
        hold = None
        if model_gpu and model_gpu.get("model_bytes"):
            for sample in reversed(history):
                if not sample["model_bytes"]:
                    break
                hold = sample["ts"]
        return {"name": settings.llm_model, "address": safe_address(settings.llm_base_url),
                "power": self.runtime.llm_power.for_url().status(), "health": next(c for c in health["checks"] if c["id"] == "vllm"),
                "values": admin_settings.values(desired), "effective": admin_settings.values(settings),
                "gpu": model_gpu, "memory_observed_since": hold,
                "loaded": {"base_model": settings.llm_model, "planner_adapter": settings.analytics_planner_model or settings.llm_planner_model,
                           "analyst_adapter": settings.analytics_answer_model or settings.llm_analyst_model,
                           "context_length": None, "max_requests": None, "gpu_memory_share": None,
                           "reason": "The running model server has not reported its launch configuration", **await self.loaded()},
                "ram_check": await self.ram_check(),
                "today": {"calls": len(calls), "median_ms": percentile(durations, .5), "slowest_ms": max(durations, default=None),
                          "tokens_per_second": generation / (sum(durations) / 1000) if generation and sum(durations) else None,
                          "manual_wakes": wakes, "wakes": None, "wake_reason": "Automatic wake counts were not recorded", "busy_errors": busy},
                "gpu_history": history, "now": now}

    async def loaded(self):
        unit = await self.unit("model")
        if not unit or not unit["pid"]:
            return {}
        try:
            args = Path(f"/proc/{unit['pid']}/cmdline").read_bytes().decode().split("\0")
            result = {}
            for option, key, cast in (("--max-model-len", "context_length", int), ("--max-num-seqs", "max_requests", int), ("--gpu-memory-utilization", "gpu_memory_share", float)):
                if option in args:
                    result[key] = cast(args[args.index(option) + 1])
            if len(result) == 3:
                result["reason"] = "Launch settings read from the running model process"
            return result
        except (OSError, ValueError, IndexError):
            return {}

    async def ram_check(self):
        script = self.runtime.settings.repository_root / "deploy/vllm_sleep_memory.py"
        if not script.is_file():
            return {"safe": None, "reason": "The free-RAM checker is not installed"}
        try:
            # Reuse exactly the launcher's check; it never mutates model state.
            result = (await command("python3", str(script), env={**os.environ, "GRAPHMINE_LLM_MODEL": self.runtime.settings.llm_model})).strip()
            return {"safe": result == "1", "reason": "Enough free host RAM for level-1 sleep" if result == "1" else "Sleep will stay off: insufficient free RAM or model weight size is unknown"}
        except (OSError, TimeoutError):
            return {"safe": None, "reason": "The free-RAM check could not finish"}
