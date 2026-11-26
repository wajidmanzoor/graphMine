"""Opt-in power controls for the fixed IU server, with shared ownership and leases."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import threading
import time
import uuid

from .database_job_context import checkpoint
from .errors import AnalyticsError
from .neo4j_backend import atomic_json, get_active_neo4j

COMMANDS = {
    "start": "sudo systemctl start neo4j",
    "stop": "sudo systemctl stop neo4j",
    "status": "sudo systemctl status neo4j",
}
HOST_KEY = "SHA256:/irl3Zjs7PpOCCtWsrt3tZsF65YSIcQFsuyja7Qa+r8"
WAKE_MESSAGE = "Starting the database, about 40 seconds…"
_guard = threading.Lock()
_locks = {}
_managers = {}


def error(message, code="database_unavailable"):
    return AnalyticsError(message, code, 503)


def verify_host_key(key):
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    if not hmac.compare_digest(fingerprint, HOST_KEY):
        raise error("The database SSH host key does not match the pinned key.", "database_host_key")


class PinnedSSH:
    """No shell, files, agent keys or host-key persistence; only three exact commands."""

    def __init__(self, settings, *, client_factory=None, clock=time.monotonic, sleep=time.sleep):
        self.settings, self.client_factory = settings, client_factory
        self.clock, self.sleep = clock, sleep

    def run(self, command):
        if command not in COMMANDS.values():
            raise ValueError("Remote Neo4j command is not allowed")
        if command != COMMANDS["status"] and not self.settings.iu_neo4j_autowake:
            raise error("Automatic database wake and sleep are disabled.", "database_autowake_disabled")
        password = os.environ.get("GRAPHMINE_IU_SSH_PASSWORD")
        if not password:
            raise error("Configure the database SSH password in the server environment.", "database_ssh_configuration")
        import paramiko

        class Pin(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                verify_host_key(key)

        client = (self.client_factory or paramiko.SSHClient)()
        host, _ = get_active_neo4j(self.settings, target="iu-remote").connection.address
        try:
            # The empty in-memory key stores force the pin check on every connection.
            client.set_missing_host_key_policy(Pin())
            client.connect(host, port=22, username="exouser", password=password,
                           allow_agent=False, look_for_keys=False, timeout=5,
                           banner_timeout=5, auth_timeout=10, channel_timeout=10)
            # sudo reads its terminal when -S is not in the permitted command.
            stdin, stdout, _ = client.exec_command(command, timeout=15, get_pty=True)
            channel = stdout.channel
            deadline = self.clock() + 15
            prompt, sent = b"", False
            while not channel.exit_status_ready():
                # Wait until sudo has disabled terminal echo and requested its
                # password. Sending before the prompt can echo or lose input.
                if channel.recv_ready():
                    chunk = channel.recv(4096)
                    if not sent:
                        prompt = (prompt + chunk)[-1024:]
                        if b"password" in prompt.lower() and prompt.rstrip().endswith(b":"):
                            stdin.write(password + "\n")
                            stdin.flush()
                            channel.shutdown_write()
                            prompt, sent = b"", True
                if channel.recv_stderr_ready():
                    channel.recv_stderr(4096)
                if self.clock() >= deadline:
                    raise TimeoutError
                self.sleep(.05)
            code = channel.recv_exit_status()
            if code and not (command == COMMANDS["status"] and code == 3):
                raise error("The database service command failed.", "database_ssh")
            return code
        except AnalyticsError:
            raise
        except Exception:
            raise error("The database SSH operation failed.", "database_ssh") from None
        finally:
            try:
                client.close()
            except Exception:
                pass


def _boot():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _process_stamp(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return _boot() + ":" + fields[19]
    except (OSError, IndexError):
        return None


class RemoteNeo4j:
    def __init__(self, settings, *, tcp=None, verify=None, reachable=None, ssh=None,
                 clock=None, monotonic=None, sleep=None, jobs_running=None, publish=None):
        self.settings = settings
        self.endpoint = get_active_neo4j(settings, target="iu-remote").connection
        self.clock, self.monotonic, self.sleep = clock or time.time, monotonic or time.monotonic, sleep or time.sleep
        self.tcp, self.verify = tcp or self._tcp, verify or self._verify
        self.reachable = reachable or self._reachable
        self.transport = PinnedSSH(settings)
        self.ssh = ssh or self.transport.run
        self.jobs_running, self.publish = jobs_running or self._jobs_running, publish
        # Development, testing and production share one VM. Their activity and
        # ownership must therefore share one lock/state directory too.
        directory = settings.iu_neo4j_state_dir or (
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "graphmine/iu-neo4j")
        self.path = Path(directory) / "remote_neo4j.json"
        self._cache_lock = threading.Lock()
        self._cached_at, self._cached_up = float("-inf"), False
        self._task = None
        self.wake_timeout = 120
        key = (os.getpid(), str(self.path.absolute()))
        with _guard:
            self._process_lock = _locks.setdefault(key, threading.Lock())

    @staticmethod
    def _tcp(address, timeout):
        try:
            with socket.create_connection(address, timeout=timeout):
                return True
        except OSError:
            return False

    def _verify(self, timeout):
        from neo4j import GraphDatabase
        with GraphDatabase.driver(self.endpoint.uri, auth=self.endpoint.auth, connection_timeout=timeout,
                                  connection_acquisition_timeout=timeout, max_connection_pool_size=1) as driver:
            driver.verify_connectivity()
        return True

    def is_up(self, *, refresh=False, timeout=3):
        """A bounded TCP+Bolt probe. It never invokes SSH or records user activity."""
        with self._cache_lock:
            now = self.monotonic()
            if not refresh and now - self._cached_at < 10:
                return self._cached_up
            deadline, up = now + timeout, False
            try:
                if timeout > 0 and self.tcp(self.endpoint.address, min(1, timeout)):
                    remaining = deadline - self.monotonic()
                    up = remaining > 0 and bool(self.verify(remaining))
            except Exception:
                up = False
            self._cached_at, self._cached_up = self.monotonic(), bool(up)
            return self._cached_up

    def _reachable(self):
        host, _ = self.endpoint.address
        try:
            route = subprocess.run(["ip", "-json", "route", "get", host], text=True,
                                   capture_output=True, timeout=3, check=True)
            if not any(row.get("dev") == "wg-iu" for row in json.loads(route.stdout)):
                return False
            with socket.create_connection((host, 22), timeout=3):
                return True
        except OSError as exc:
            # An explicit refusal proves the host answered at the network level.
            return exc.errno == errno.ECONNREFUSED
        except (ValueError, subprocess.SubprocessError):
            return False

    def _new_state(self):
        return {"version": 1, "boot": _boot(), "started_by_graphmine": False,
                "started_at": None, "last_used": None, "released_at": None,
                "retry_after": None, "last_failure": None, "phase": "unknown", "leases": {}, "stores": []}

    def _load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > 1024 * 1024):
                    raise ValueError
                state = json.load(stream)
            if (not isinstance(state, dict) or state.get("version") != 1
                    or type(state.get("started_by_graphmine")) is not bool
                    or not isinstance(state.get("leases"), dict)):
                raise ValueError
            for key in ("started_at", "last_used", "released_at", "retry_after"):
                value = state.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError
            if (state.get("phase") not in {"unknown", "waking", "up", "asleep", "failed"}
                    or state.get("last_failure") not in {None, "ssh", "wake_timeout"}
                    or state["started_by_graphmine"] and state.get("started_at") is None
                    or not isinstance(state.get("stores"), list) or len(state["stores"]) > 256
                    or any(not isinstance(path, str) or not Path(path).is_absolute() for path in state["stores"])):
                raise ValueError
            for key, lease in state["leases"].items():
                if (not re.fullmatch(r"[0-9a-f]{32}", key) or not isinstance(lease, dict)
                        or type(lease.get("pid")) is not int or lease["pid"] < 1
                        or not isinstance(lease.get("process"), str)
                        or not re.fullmatch(r"[0-9a-f-]{36}:[0-9]+", lease["process"])):
                    raise ValueError
            if state.get("boot") != _boot():
                # After a host reboot, remote ownership cannot be proven.
                return self._new_state()
            return state
        except FileNotFoundError:
            return self._new_state()
        except (OSError, ValueError, TypeError):
            raise error("Database power state is unavailable.", "database_configuration") from None

    @contextmanager
    def _locked(self):
        deadline = self.monotonic() + 160
        while not self._process_lock.acquire(timeout=.1):
            checkpoint()
            if self.monotonic() >= deadline:
                raise error("Timed out waiting for database power controls.", "database_busy")
        fd = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            while True:
                checkpoint()
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.monotonic() >= deadline:
                        raise error("Timed out waiting for database power controls.", "database_busy")
                    self.sleep(.1)
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self._process_lock.release()

    def _save(self, state):
        store = str((Path(self.settings.data_root) / "agent.sqlite3").absolute())
        if store not in state["stores"]:
            state["stores"].append(store)
        atomic_json(self.path, state)

    def _emit(self, phase, message):
        checkpoint(phase, message=message)
        if self.publish:
            try:
                self.publish({"backend_id": "iu-remote", "phase": phase, "message": message})
            except Exception:
                pass

    def register_store(self):
        """Register job storage without connecting to or waking the remote server."""
        with self._locked():
            self._save(self._load())

    def touch(self):
        with self._locked():
            state = self._load()
            state.update(last_used=self.clock(), phase="up")
            self._save(state)

    def ensure_awake(self):
        if self.is_up():
            self.touch()
            return
        if not self.reachable():
            raise error("VPN tunnel is down", "database_vpn_down")
        if not self.settings.iu_neo4j_autowake:
            raise error("The database is unavailable and automatic wake is disabled.", "database_autowake_disabled")
        self._emit("waking", WAKE_MESSAGE)
        with self._locked():
            state = self._load()
            if self.is_up(refresh=True):
                state.update(last_used=self.clock(), phase="up")
                self._save(state)
                return
            if state.get("retry_after") is not None and self.clock() < state["retry_after"]:
                raise error("The previous database wake failed. Retry after the five-minute back-off.", "database_wake_backoff")
            if not self.reachable():
                raise error("VPN tunnel is down", "database_vpn_down")
            state.update(phase="waking")
            self._save(state)
            try:
                self.ssh(COMMANDS["start"])
            except Exception:
                state.update(retry_after=self.clock() + 300, last_failure="ssh", phase="failed")
                self._save(state)
                raise error("The database could not be started. Retrying is paused for five minutes.", "database_ssh") from None
            state.update(started_by_graphmine=True, started_at=self.clock(), last_used=self.clock(),
                         retry_after=None, last_failure=None)
            self._save(state)
            deadline = self.monotonic() + self.wake_timeout
            while self.monotonic() < deadline:
                checkpoint()
                if self.is_up(refresh=True, timeout=min(3, deadline - self.monotonic())):
                    state.update(last_used=self.clock(), phase="up")
                    self._save(state)
                    self._emit("ready", "Database is ready.")
                    return
                self.sleep(min(2, max(0, deadline - self.monotonic())))
            state.update(phase="failed", last_failure="wake_timeout", retry_after=self.clock() + 300)
            self._save(state)
            raise error("The database did not become ready within 120 seconds.", "database_wake_timeout")

    @staticmethod
    def _live_leases(state):
        return {key: row for key, row in state["leases"].items() if isinstance(row, dict)
                and type(row.get("pid")) is int and row["pid"] > 0
                and row.get("process") is not None and _process_stamp(row["pid"]) == row["process"]}

    @contextmanager
    def request(self, *, wake=True):
        """Track a real user operation for its entire database session."""
        if not wake:
            yield
            return
        identifier = uuid.uuid4().hex
        with self._locked():
            state = self._load()
            state["leases"] = self._live_leases(state)
            state["leases"][identifier] = {"pid": os.getpid(), "process": _process_stamp(os.getpid())}
            state["last_used"] = self.clock()
            self._save(state)
        try:
            self.ensure_awake()
            yield
        finally:
            with self._locked():
                state = self._load()
                state["leases"].pop(identifier, None)
                state["last_used"] = self.clock()
                self._save(state)

    def release(self):
        with self._locked():
            state = self._load()
            state.update(released_at=self.clock(), last_used=self.clock())
            self._save(state)

    def _jobs_running(self):
        paths = {*self._load()["stores"], str((Path(self.settings.data_root) / "agent.sqlite3").absolute())}
        try:
            for name in paths:
                path = Path(name)
                if not path.exists():
                    continue
                with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as db:
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='database_jobs'").fetchone():
                        continue
                    if db.execute("SELECT 1 FROM database_jobs WHERE status IN ('queued','running','cancelling') LIMIT 1").fetchone():
                        return True
            return False
        except sqlite3.Error:
            return True

    def idle_once(self):
        if not self.settings.iu_neo4j_autowake:
            return False
        with self._locked():
            state = self._load()
            state["leases"] = self._live_leases(state)
            if (not state["started_by_graphmine"] or state["leases"] or self.jobs_running()
                    or state.get("last_used") is None
                    or self.clock() - state["last_used"] < self.settings.iu_neo4j_idle_minutes * 60
                    or state.get("retry_after") is not None and self.clock() < state["retry_after"]):
                return False
            if not self.reachable():
                return False
            try:
                self.ssh(COMMANDS["stop"])
            except Exception:
                state.update(retry_after=self.clock() + 300, last_failure="ssh")
                self._save(state)
                return False
            state.update(started_by_graphmine=False, phase="asleep", retry_after=None, last_failure=None)
            self._save(state)
            with self._cache_lock:
                self._cached_at, self._cached_up = float("-inf"), False
            return True

    def status(self):
        state = self._load()
        return {"vpn_reachable": bool(self.reachable()), "is_up": self.is_up(),
                "started_by_graphmine": state["started_by_graphmine"], "started_at": state.get("started_at"),
                "last_used": state.get("last_used"), "released_at": state.get("released_at"),
                "phase": state.get("phase"), "active_sessions": len(self._live_leases(state)),
                "autowake": self.settings.iu_neo4j_autowake, "idle_minutes": self.settings.iu_neo4j_idle_minutes,
                "retry_after": state.get("retry_after")}

    async def _idle(self):
        while True:
            await asyncio.sleep(30)
            worker = asyncio.create_task(asyncio.to_thread(self.idle_once))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise
            except Exception:
                # State or network failures must never cause an unowned stop.
                continue

    def start(self):
        if self.settings.iu_neo4j_autowake and self._task is None:
            self._task = asyncio.create_task(self._idle(), name="iu-neo4j-idle")

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self.publish = None
        key = (os.getpid(), str(Path(self.settings.data_root).absolute()))
        with _guard:
            if _managers.get(key) is self:
                _managers.pop(key)


def get_remote(settings):
    key = (os.getpid(), str(Path(settings.data_root).absolute()))
    with _guard:
        manager = _managers.get(key)
    if manager is None:
        candidate = RemoteNeo4j(settings)
        with _guard:
            manager = _managers.setdefault(key, candidate)
    manager.settings = manager.transport.settings = settings
    return manager
