"""Read installed performance artifacts and supervise explicitly requested tests.

The optional perf suite is never installed or executed just by opening a page.
Its config and summary are reduced to operational metadata before returning them.
"""

import asyncio
import json
import logging
import math
import os
import re
import signal
import sys
import time
from pathlib import Path
from uuid import uuid4

from .admin_data import timestamp
from .admin_settings import ALLOWLIST, load, values
from .identity import AccountError

_logger = logging.getLogger(__name__)
METRICS = (
    ("answer_p50_ms", "Time to answer · median", "ms"),
    ("answer_p95_ms", "Time to answer · p95", "ms"),
    ("question_error_percent", "Question errors", "%"),
    ("busy_percent", "Model / queue busy", "%"),
    ("model_calls_per_question", "Model calls per question", "calls"),
    ("routing_reasoning_share_percent", "Routing reasoning share", "%"),
    ("peak_GPU 0 memory", "GPU 0 memory peak", "MiB"),
    ("job_queue_p95_ms", "Calculation queue · p95", "ms"),
)


def number(value):
    return value if type(value) in {int, float} and math.isfinite(value) else None


def read_json(path, maximum=16 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Artifact is missing or exceeds the metadata byte limit.")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid artifact metadata.")
    return value


class Performance:
    def __init__(self, runtime):
        self.runtime = runtime
        self.task = self.process = None
        self.lock = asyncio.Lock()
        with runtime.database._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS admin_perf_jobs (id TEXT PRIMARY KEY,document TEXT NOT NULL)")
            for row in db.execute("SELECT id,document FROM admin_perf_jobs").fetchall():
                job = json.loads(row[1])
                if job["status"] in {"starting", "running"}:
                    job.update(status="interrupted", finished_at=time.time(), reason="The agent restarted before this test finished. Inspect the retained run before starting another test.")
                    db.execute("UPDATE admin_perf_jobs SET document=? WHERE id=?", (json.dumps(job), row[0]))
                    runtime.accounts._audit(db, "performance.interrupted", row[0], before={"status": "running"}, after=job)

    @property
    def root(self):
        return self.runtime.settings.repository_root

    @property
    def directory(self):
        return self.root / "var" / "perf"

    @property
    def installed(self):
        return (self.root / "perf" / "run.py").is_file()

    def path(self, identifier):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,180}", identifier):
            raise ValueError("Invalid performance run name.")
        path = self.directory / identifier
        if path.is_symlink() or path.resolve().parent != self.directory.resolve() or not path.is_dir():
            raise AccountError("Performance run not found.", "not_found", 404)
        return path

    def runs(self):
        result = []
        for path in self.directory.iterdir() if self.directory.is_dir() else []:
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                self.path(path.name)
                config = read_json(path / "config.json")
                summary = read_json(path / "summary.json") if (path / "summary.json").exists() else {}
                headline = summary.get("headline", {})
                flags = [{"message": str(flag["message"])[:300]} for flag in summary.get("flags", [])[:100] if isinstance(flag, dict) and isinstance(flag.get("message"), str)]
                settings = config.get("capacity", {})
                note = ", ".join(f"{name} {settings[key]}" for key, name in (("GRAPHMINE_MAX_MODEL_CALLS", "model calls"), ("GRAPHMINE_ACCOUNT_RUNNING_JOBS", "calculations"), ("GRAPHMINE_ANALYTICS_CPU_WORKERS", "CPU workers")) if type(settings.get(key)) is int)
                report = path / "report.html"
                result.append({"id": path.name, "label": str(config.get("label", path.name))[:120], "type": str(config.get("test", "unknown"))[:30],
                               "created_at": timestamp(config.get("prepared_at")), "finished_at": timestamp(config.get("finished_at")),
                               "users": number(headline.get("users_requested", config.get("requested_users"))),
                               "settings_note": note or "Settings were not recorded", "flags": flags,
                               "metrics": {key: number(headline.get(key)) for key, *_ in METRICS},
                               "status": "failed" if config.get("infrastructure_error") else "completed" if config.get("finished_at") else "running",
                               "report": report.is_file() and not report.is_symlink(), "summary_available": bool(summary)})
            except (OSError, ValueError, KeyError, TypeError, AttributeError, AccountError):
                continue  # Partially written and unrecognized directories are not reports.
        return sorted(result, key=lambda row: row["created_at"] or 0, reverse=True)

    def snapshot(self):
        runs = self.runs()
        with self.runtime.database._connect() as db:
            jobs = [json.loads(row[0]) for row in db.execute("SELECT document FROM admin_perf_jobs ORDER BY rowid DESC LIMIT 20")]
        for job in jobs:
            matching = next((run for run in runs if run["label"] == job["run_label"]), None)
            job["run_id"] = matching["id"] if matching else None
            job["progress"] = "Report available" if matching and matching["report"] else "Test running; report is generated when it finishes" if job["status"] == "running" else job["status"].capitalize()
        return {"installed": self.installed, "runs": runs, "jobs": jobs,
                "allowed_tests": ["benchmark", "load", *(["stress", "spike", "soak"] if self.runtime.settings.perf_confirm_shared_gpu else [])],
                "metrics": [{"key": key, "label": label, "unit": unit} for key, label, unit in METRICS],
                "install_url": "https://github.com/wajidmanzoor/graphMine/pull/2",
                "install_reason": "Install the reviewed perf suite in this deployment (perf/run.py and its dependencies), then reload this page."}

    def report(self, identifier):
        path = self.path(identifier) / "report.html"
        if path.is_symlink() or not path.is_file():
            raise AccountError("The report is not available yet.", "not_found", 404)
        return path

    def store(self, job, before):
        with self.runtime.database._connect() as db:
            db.execute("INSERT INTO admin_perf_jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document", (job["id"], json.dumps(job)))
            self.runtime.accounts._audit(db, "performance." + job["status"], job["id"], before=before, after=job)

    async def begin(self, *, test, label, lab_window, confirm, unit):
        if confirm is not True:
            raise ValueError("Confirm the test and its agreed time slot.")
        if not self.installed:
            raise AccountError("The performance suite is not installed in this deployment.", "suite_unavailable", 409)
        allowed = {"benchmark", "load"} | ({"stress", "spike", "soak"} if self.runtime.settings.perf_confirm_shared_gpu else set())
        if test not in allowed:
            raise AccountError("This test requires GRAPHMINE_PERF_CONFIRM_SHARED_GPU to be enabled by the operator.", "shared_gpu_confirmation", 403)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", label) or not lab_window.strip():
            raise ValueError("Use a short label with letters, numbers, hyphens or underscores and record the agreed slot.")
        if not unit or not unit.get("pid") or unit.get("active") != "active":
            raise AccountError("The suite requires this deployment's running systemd model service.", "service_unavailable", 409)
        async with self.lock:
            if self.task and not self.task.done():
                raise AccountError("A test is already running. Wait for its report.", "test_running", 409)
            identifier = uuid4().hex
            job = {"id": identifier, "type": test, "label": label, "run_label": label + "-" + identifier[:8], "lab_window": lab_window.strip(), "status": "starting", "created_at": time.time()}
            self.store(job, {"status": "not_started"})
            self.task = asyncio.create_task(self.run(job, unit["unit"]))
            return job

    async def run(self, job, unit):
        private = self.runtime.settings.data_root / "admin-perf"
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = private / (job["id"] + ".json")
        before = dict(job)
        try:
            env = {key: value for key, value in os.environ.items() if key.startswith("GRAPHMINE_")}
            desired = load(self.runtime.settings, self.runtime.database)
            for key, value in values(desired, ALLOWLIST).items():
                # The suite's normal environment parser expects the prefixed spelling.
                key = "GRAPHMINE_MODEL_QUEUE_SECONDS" if key == "MODEL_QUEUE_SECONDS" else key
                env[key] = ",".join(value) if isinstance(value, (list, tuple)) else str(int(value)) if type(value) is bool else str(value)
            with os.fdopen(os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
                json.dump(env, handle)
            args = [sys.executable, str(self.root / "perf" / "run.py"), job["type"], "--label", job["run_label"], "--app-env", str(config), "--app-python", sys.executable,
                    "--output", str(self.directory), "--lab-window", job["lab_window"], "--vllm-service", unit]
            if job["type"] in {"stress", "spike", "soak"}:
                args.append("--confirm-shared-gpu")
            # Suite-owned artifacts retain detailed diagnostics. Raw stdout may
            # contain configuration, so it is never exposed through the console.
            self.process = await asyncio.create_subprocess_exec(*args, cwd=self.root, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                                stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            job.update(status="running", started_at=time.time())
            self.store(job, before)
            code = await self.process.wait()
            before = dict(job)
            job.update(status="completed" if code == 0 else "failed", exit_code=code, finished_at=time.time())
            if code:
                job["reason"] = "The suite failed. Inspect its retained run artifacts for the diagnostic report."
            self.store(job, before)
        except asyncio.CancelledError:
            await self.stop()
            previous = dict(job)
            job.update(status="interrupted", finished_at=time.time(), reason="The agent stopped during this test.")
            self.store(job, previous)
            raise
        except Exception:
            _logger.exception("Performance test %s could not finish", job["id"])
            previous = dict(job)
            job.update(status="failed", finished_at=time.time(), reason="The test could not start or finish. Check the server log and installed suite dependencies.")
            self.store(job, previous)
        finally:
            config.unlink(missing_ok=True)
            self.process = None

    async def stop(self):
        process = self.process
        if process is None or process.returncode is not None:
            return
        descendants = []
        def children(pid):
            try:
                for item in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
                    child = int(item)
                    children(child)
                    descendants.append(child)
            except OSError:
                pass
        children(process.pid)
        owned = [*descendants, process.pid]
        for pid in owned:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            for pid in owned:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await process.wait()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
