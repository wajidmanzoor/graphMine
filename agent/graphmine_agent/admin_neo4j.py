"""Audited backend switches with admission fencing, verification and rollback."""

import asyncio
from contextlib import nullcontext
import fcntl
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .database import RecordNotFound
from .database_progress import topic
from .errors import AnalyticsError
from .neo4j_access import admission, drained, switching
from .neo4j_backend import active_backend_id, set_active_backend, verification_endpoints
from .neo4j_local import LocalNeo4j
from .neo4j_records import counts


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["local", "iu-remote"]
    force: bool = Field(default=False, strict=True)


class BackendSwitch:
    def __init__(self, runtime, *, local=None, verify=None):
        self.runtime, self.settings = runtime, runtime.settings
        self.local = local or LocalNeo4j(runtime.settings)
        self.remote = runtime.remote_neo4j
        self.verify = verify or self._verify
        self.drain_seconds = 120

    def jobs(self):
        with self.runtime.database._connect() as db:
            return [{key: value[key] for key in ("id", "owner_id", "kind", "source_id", "status", "cancellable")}
                    for (document,) in db.execute("SELECT document FROM database_jobs WHERE status IN ('queued','running','cancelling')")
                    for value in [json.loads(document)]]

    def status(self):
        return {"active_backend": active_backend_id(self.settings), "local": self.local.status(),
                "remote": self.remote.status(), "record_counts": counts(self.runtime),
                "running_jobs": self.jobs(), "switching": switching(self.settings) or switching(self._shared_settings())}

    def _shared_settings(self):
        return SimpleNamespace(data_root=self.remote.path.parent)

    def _other_local_workspace(self):
        for name in self.remote._load()["stores"]:
            path = Path(name)
            if path.parent == Path(self.settings.data_root).absolute():
                continue
            try:
                fd = os.open(path.with_name(path.name + ".worker.lock"), os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:
                continue
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    if active_backend_id(SimpleNamespace(data_root=path.parent)) == "local":
                        return True
            finally:
                os.close(fd)
        return False

    def emit(self, target, phase, message):
        self.runtime.events.notify(topic(), "database.switch",
            {"backend_id": target, "phase": phase, "message": message})

    def _verify(self, target):
        from neo4j import GraphDatabase, READ_ACCESS, unit_of_work
        endpoints = verification_endpoints(self.settings, target)
        if not endpoints:
            raise AnalyticsError("No database connection is configured for this backend.", "database_configuration", 503)
        @unit_of_work(timeout=5)
        def read(transaction):
            row = transaction.run("RETURN 1 AS connected").single(strict=True)
            return row["connected"] == 1
        try:
            for endpoint in endpoints:
                if target == "iu-remote":
                    from .database_connections import network_address
                    network_address(self.settings, *endpoint.address)
                with GraphDatabase.driver(endpoint.uri, auth=endpoint.auth, connection_timeout=3,
                        connection_acquisition_timeout=5, max_transaction_retry_time=0) as driver:
                    with driver.session(database=endpoint.database, default_access_mode=READ_ACCESS) as session:
                        if not session.execute_read(read):
                            raise ValueError
        except Exception:
            raise AnalyticsError("The target database did not pass its read-only connection check.",
                                 "database_verification", 503) from None

    def _cancel_jobs(self):
        deadline = time.monotonic() + self.drain_seconds
        while True:
            pending = self.jobs()
            if not pending:
                return
            for job in pending:
                if job["cancellable"]:
                    try:
                        self.runtime.database_jobs.cancel(job["id"], administrator=True)
                    except RecordNotFound:
                        pass  # Completed between the read and cancellation.
                    except AnalyticsError as exc:
                        if exc.code != "database_committing":
                            raise
            if time.monotonic() >= deadline:
                raise AnalyticsError("Database jobs have not finished cancelling. The backend was not changed.",
                                     "database_jobs_busy", 409)
            time.sleep(.05)

    def switch(self, target, *, force=False):
        previous = active_backend_id(self.settings)
        outcome, failure = "failed", None
        try:
            with admission(self._shared_settings(), switching=True), admission(self.settings, switching=True):
                previous = active_backend_id(self.settings)
                if target == "iu-remote" and previous == "local" and self._other_local_workspace():
                    raise AnalyticsError("Another running workspace has the local backend selected. Stop that workspace before parking these shared services.",
                                         "database_local_in_use", 409)
                if self.jobs():
                    if not force:
                        raise AnalyticsError("Database jobs are running. Wait for them or confirm cancellation before switching.",
                                             "database_jobs_busy", 409)
                    self.emit(target, "cancelling", "Cancelling database jobs…")
                    self._cancel_jobs()
                self.emit(target, "draining", "Waiting for active database sessions…")
                with drained(self.settings, timeout=self.drain_seconds):
                    result = self._switch(previous, target)
            outcome = "unchanged" if previous == target else "completed"
            self.emit(target, "completed", "Database backend is ready. The workspace now shows its datasets and saved work.")
            return result
        except AnalyticsError as exc:
            failure = exc.code
            self.emit(target, "failed", str(exc))
            raise
        except Exception:
            failure = "database_switch_failed"
            self.emit(target, "failed", "The database switch failed. Check its status before retrying.")
            raise AnalyticsError("The database switch failed. Check its status before retrying.", failure, 503) from None
        finally:
            with self.runtime.database._connect() as db:
                self.runtime.accounts._audit(db, "neo4j.switch", target,
                    before={"active_backend": previous},
                    after={"active_backend": active_backend_id(self.settings), "target": target,
                           "force": force, "result": outcome, "error": failure})

    def _switch(self, previous, target):
        if previous == target:
            return {"active_backend": previous, "changed": False}
        old_local = self.local.status()
        published, local_changed = False, False
        activity = self.remote.request() if target == "iu-remote" else nullcontext()
        try:
            self.emit(target, "starting", "Starting local databases…" if target == "local" else "Connecting to the IU database…")
            if target == "local":
                local_changed = True
                self.local.activate()
            with activity:
                self.emit(target, "verifying", "Verifying the target database with a read query…")
                self.verify(target)
                self.emit(target, "selecting", "Changing the active database backend…")
                set_active_backend(self.settings, target)
                published = True
                self.runtime.database_pools.drain(timeout=self.drain_seconds)
                self.emit(target, "releasing", "Parking local databases…" if previous == "local" else "Releasing the IU database…")
                if previous == "local":
                    local_changed = True
                    self.local.park()
                else:
                    self.remote.release()
            return {"active_backend": target, "changed": True}
        except Exception as original:
            self.emit(target, "rollback", "Restoring the previous database backend…")
            restored = True
            if local_changed:
                try:
                    self.local.restore(old_local)
                except Exception:
                    restored = False
            if published:
                try:
                    set_active_backend(self.settings, previous)
                    self.runtime.database_pools.drain(timeout=self.drain_seconds)
                except Exception:
                    restored = False
            # Waking IU never gives a failed switch permission to stop it.
            if target == "iu-remote":
                try:
                    self.remote.release()
                except Exception:
                    restored = False
            if not restored:
                raise AnalyticsError("The switch failed and recovery is incomplete. Check the database service status before retrying.",
                                     "database_rollback_incomplete", 503) from None
            if isinstance(original, AnalyticsError):
                raise
            raise AnalyticsError("The switch failed; the previous backend was restored.", "database_switch_failed", 503) from None


def register(router):
    # The parent router uses account_api.administrator for every route.
    @router.get("/neo4j")
    async def status(request: Request):
        return await run_in_threadpool(BackendSwitch(request.app.state.runtime).status)

    @router.post("/neo4j/switch")
    async def switch(body: Switch, request: Request):
        controller = BackendSwitch(request.app.state.runtime)
        work = asyncio.create_task(run_in_threadpool(controller.switch, body.target, force=body.force))
        # A disconnect must not release admission or strand a half-finished switch.
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            await work
            raise
