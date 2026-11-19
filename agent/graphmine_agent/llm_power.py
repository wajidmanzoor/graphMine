"""On-demand vLLM memory, shared by callers without waking for health checks."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
from functools import wraps
import hashlib
import inspect
import logging
import os
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from .llm_errors import LLMUnavailable, LLMPowerBusy

log = logging.getLogger(__name__)
_registry = ContextVar("llm_power_registry", default=None)
_notice = ContextVar("llm_power_notice", default=None)


def configure_logging():
    # Uvicorn configures its own loggers, not the application's root logger.
    # Keep wake timings and failed idle transitions visible in the journal.
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def server_root(base):
    parsed = urlsplit(str(base).rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTP model base URL without credentials, query or fragment")
    # Treat the two common IPv4 loopback names as one server for process leases.
    netloc = parsed.netloc
    if parsed.hostname == "localhost":
        netloc = "127.0.0.1" + (f":{parsed.port}" if parsed.port else "")
    return urlunsplit((parsed.scheme, netloc, parsed.path.removesuffix("/v1"), "", ""))


@contextmanager
def power_notice(callback):
    token = _notice.set(callback)
    try:
        yield
    finally:
        _notice.reset(token)


@contextmanager
def use_registry(registry):
    registry.shared = True
    token = _registry.set(registry)
    try:
        yield registry
    finally:
        _registry.reset(token)


class LLMPower:
    def __init__(self, base, api_key, *, enabled=True, level=1, idle_minutes=20,
                 transport=None, lease_dir=None, wake_timeout=120, poll_seconds=.5,
                 clock=time.time, monotonic=time.monotonic):
        if level != 1:
            raise ValueError("GRAPHMINE_LLM_SLEEP_LEVEL supports only level 1")
        if not 0 < idle_minutes < float("inf"):
            raise ValueError("GRAPHMINE_LLM_IDLE_SLEEP_MINUTES must be positive")
        self.base, self.level = server_root(base), level
        self.configured, self.enabled = bool(enabled), bool(enabled)
        self.idle_minutes, self.wake_timeout, self.poll_seconds = idle_minutes, wake_timeout, poll_seconds
        self._clock, self._monotonic = clock, monotonic
        self.last_activity, self.last_wake_seconds = clock(), None
        self.sleeping, self.in_flight, self._waking = None, 0, False
        self._recheck_at, self._lock, self._task = 0, asyncio.Lock(), None
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._transport, self._client = transport, None
        runtime = Path(os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        shared = runtime if runtime.is_dir() else Path(os.getenv("HF_HOME", str(Path.home() / ".cache/huggingface")))
        self._directory = Path(lease_dir or os.getenv("GRAPHMINE_LLM_POWER_LEASE_DIR") or shared / "graphmine-llm-power")
        self._key = hashlib.sha256(self.base.encode()).hexdigest()
        try:
            self.last_activity = (self._directory / (self._key + ".requests")).stat().st_mtime
        except FileNotFoundError:
            pass
        self._run = None

    def _http(self):
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base + "/", headers=self._headers,
                transport=self._transport, timeout=httpx.Timeout(self.wake_timeout, connect=5),
                follow_redirects=False, trust_env=False)
        return self._client

    @asynccontextmanager
    async def _file_lock(self, *, exclusive=False, transition=False, wait=True):
        """Shared run leases also protect evaluations in other local processes.

        Kernel locks disappear on process death. A separate transition lock
        serializes sleep/wake without holding the asyncio loop in flock().
        """
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._directory.is_symlink() or self._directory.stat().st_uid != os.getuid():
            raise LLMUnavailable("The model power lease directory is not owned by this service")
        path = self._directory / (self._key + (".transition" if transition else ".requests"))
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.utime(fd, (self.last_activity, self.last_activity))
        except FileExistsError:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        acquired = False
        try:
            while True:
                try:
                    fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if not wait:
                        break
                    await asyncio.sleep(self.poll_seconds)
            yield acquired
        finally:
            os.close(fd)

    def _activity(self):
        path = self._directory / (self._key + ".requests")
        try:
            return max(self.last_activity, path.stat().st_mtime)
        except FileNotFoundError:
            return self.last_activity

    def _used(self):
        self.last_activity = self._clock()
        path = self._directory / (self._key + ".requests")
        if path.exists():
            os.utime(path, (self.last_activity, self.last_activity), follow_symlinks=False)

    async def _state(self):
        if not self.configured or not self.enabled and self._clock() < self._recheck_at:
            return None
        response = await self._http().get("is_sleeping")
        if response.status_code == 404:
            self.enabled, self.sleeping = False, None
            self._recheck_at = self._clock() + 600
            return None
        response.raise_for_status()
        sleeping = response.json()["is_sleeping"]
        if type(sleeping) is not bool:
            raise ValueError("Invalid model sleep status")
        self.enabled, self.sleeping = True, sleeping
        return sleeping

    async def _announce(self, state):
        callback = _notice.get()
        if callback:
            value = callback(state)
            if inspect.isawaitable(value):
                await value

    async def _awake_locked(self, *, wake=True):
        async with self._file_lock(exclusive=True, transition=True):
            if await self._state() is not True:
                return
            if not wake:
                raise LLMUnavailable("The model is asleep; the saved calculation remains available.")
            self._waking = True
            started = self._monotonic()
            try:
                await self._announce("waking")
                response = await self._http().post("wake_up")
                response.raise_for_status()
                while await self._state() is True:
                    await asyncio.sleep(self.poll_seconds)
                response = await self._http().get("v1/models")
                response.raise_for_status()
                self.last_wake_seconds = round(self._monotonic() - started, 3)
                self._used()
                log.info("Model at %s woke in %.3f seconds", self.base, self.last_wake_seconds)
                await self._announce("awake")
            finally:
                self._waking = False

    @asynccontextmanager
    async def request(self, *, wake=True, _run_lease=False):
        if self._run is not None and not _run_lease and wake:
            await self._run.hold(self)
        if not self.configured:
            self.in_flight += 1
            try:
                yield
            finally:
                self.in_flight -= 1
                self.last_activity = self._clock()
            return
        # Acquire a shared lease before probing/waking; reserve the local slot
        # under the same lock as sleep so no sleep can slip between the two.
        async with AsyncExitStack() as stack:
            try:
                async with asyncio.timeout(self.wake_timeout):
                    await stack.enter_async_context(self._file_lock())
                    waiting = self._waking
                    if waiting:
                        await self._announce("waking")
                    async with self._lock:
                        await self._awake_locked(wake=wake)
                        if waiting:
                            await self._announce("awake")
                        self.in_flight += 1
            except (TimeoutError, httpx.TimeoutException) as error:
                raise LLMUnavailable("The model is waking up and did not respond in time") from error
            except (httpx.HTTPError, ValueError, KeyError) as error:
                raise LLMUnavailable("The model service is unavailable. Please try again.") from error
            except OSError as error:
                log.exception("Cannot acquire model power leases for %s", self.base)
                raise LLMUnavailable("The model power controls are unavailable. Please try again.") from error
            try:
                yield
            finally:
                self.in_flight -= 1
                self._used()

    async def ensure_awake(self):
        async with self.request():
            pass

    async def wake_now(self):
        await self.ensure_awake()
        return self.status()

    async def refresh_status(self):
        async with self._lock:
            try:
                await self._state()
            except (httpx.HTTPError, ValueError, KeyError) as error:
                raise LLMUnavailable("The model service is unavailable. Please try again.") from error
        return self.status()

    def status(self):
        return {"enabled": self.enabled, "sleeping": self.sleeping,
                "last_activity": datetime.fromtimestamp(self._activity(), timezone.utc).isoformat(),
                "in_flight": self.in_flight, "last_wake_seconds": self.last_wake_seconds,
                "idle_sleep_minutes": self.idle_minutes}

    async def _sleep(self, *, idle=False):
        async with self._lock:
            if self.in_flight:
                raise LLMPowerBusy("The model has requests in progress. Try again when they finish.")
            async with self._file_lock(exclusive=True, wait=False) as acquired:
                if not acquired:
                    raise LLMPowerBusy("The model is in use by another GraphMine process.")
                if idle and self._clock() - self._activity() < self.idle_minutes * 60:
                    return
                async with asyncio.timeout(self.wake_timeout):
                    async with self._file_lock(exclusive=True, transition=True):
                        sleeping = await self._state()
                        if sleeping is None:
                            return
                        if not sleeping:
                            response = await self._http().post("sleep", params={"level": self.level, "mode": "wait"})
                            response.raise_for_status()
                            self.sleeping = True
                            log.info("Model at %s put to sleep (level %s)", self.base, self.level)

    async def sleep_now(self):
        try:
            await self._sleep()
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError) as error:
            raise LLMUnavailable("The model could not go to sleep. Please try again.") from error
        return self.status()

    async def idle_once(self):
        try:
            if not self.configured or self.in_flight or self._clock() - self._activity() < self.idle_minutes * 60:
                return
            await self._sleep(idle=True)
        except LLMPowerBusy:
            pass
        except Exception:
            log.exception("Idle sleep failed for %s; will retry next minute", self.base)

    async def _idle(self):
        while True:
            await asyncio.sleep(60)
            await self.idle_once()

    def start(self):
        if self.configured and self._task is None:
            self._task = asyncio.create_task(self._idle(), name="llm-idle-sleep")

    async def close(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None


class LLMPowerRegistry:
    """One manager per server; a learning run holds leases until its last call."""
    def __init__(self, settings):
        self.settings, self.managers = settings, {}
        self.shared = False
        self._started, self._stack = False, None
        self._held, self._hold_lock = set(), asyncio.Lock()

    def for_url(self, base=None):
        root = server_root(base or self.settings.llm_base_url)
        if root not in self.managers:
            power = self.managers[root] = LLMPower(root, self.settings.llm_api_key,
                enabled=self.settings.llm_sleep_mode, level=self.settings.llm_sleep_level,
                idle_minutes=self.settings.llm_idle_sleep_minutes)
            power._run = self if self._stack is not None else None
            if self._started:
                power.start()
        return self.managers[root]

    def start(self):
        configure_logging()
        self._started = True
        for base in (self.settings.llm_base_url, self.settings.analytics_router_base_url, self.settings.llm_route_base_url):
            if base:
                self.for_url(base).start()

    async def hold(self, power):
        async with self._hold_lock:
            if power.base not in self._held:
                await self._stack.enter_async_context(power.request(_run_lease=True))
                self._held.add(power.base)

    async def close(self):
        if self._stack:
            await self._stack.aclose()
        await asyncio.gather(*(power.close() for power in self.managers.values()))


def get_registry(settings):
    current = _registry.get()
    return current if current is not None and current.settings.llm_api_key == settings.llm_api_key else LLMPowerRegistry(settings)


@asynccontextmanager
async def power_request(settings, *, base=None, registry=None, wake=True):
    current = _registry.get()
    supplied = registry is not None
    registry = registry or get_registry(settings)
    owner = not supplied and registry is not current
    try:
        async with registry.for_url(base or settings.llm_base_url).request(wake=wake):
            yield
    finally:
        if owner:
            await registry.close()


@asynccontextmanager
async def model_run(settings):
    """Hold only servers actually used, so audits and remote-only runs don't wake."""
    current = _registry.get()
    if current is not None and current._stack is not None and current.settings.llm_api_key == settings.llm_api_key:
        yield current
        return
    registry = LLMPowerRegistry(settings)
    registry._stack = AsyncExitStack()
    try:
        with use_registry(registry):
            yield registry
    finally:
        await registry.close()


def model_run_scope(function):
    """Also protect direct evaluation entry points, not just their CLI caller."""
    @wraps(function)
    async def run(*args, **kwargs):
        from .config import Settings
        settings = kwargs.get('settings') or (args[0] if args and isinstance(args[0], Settings) else Settings.from_env())
        async with model_run(settings):
            return await function(*args, **kwargs)
    return run


async def _cli(action):
    import json
    configure_logging()
    power = LLMPower("http://127.0.0.1:8001", os.getenv("GRAPHMINE_LLM_API_KEY", "local-graphmine"),
        enabled=os.getenv("GRAPHMINE_LLM_SLEEP_MODE", "1") == "1",
        level=int(os.getenv("GRAPHMINE_LLM_SLEEP_LEVEL", "1")),
        idle_minutes=float(os.getenv("GRAPHMINE_LLM_IDLE_SLEEP_MINUTES", "20")))
    try:
        status = await {"sleep": power.sleep_now, "wake": power.wake_now, "status": power.refresh_status}[action]()
        print(json.dumps(status))
        if action == "sleep" and not status['enabled']:
            raise LLMUnavailable("Sleep mode is disabled on this model server")
    finally:
        await power.close()


if __name__ == "__main__":
    import sys
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"sleep", "wake", "status"}:
            raise ValueError("Usage: python -m graphmine_agent.llm_power sleep|wake|status")
        asyncio.run(_cli(sys.argv[1]))
    except (LLMUnavailable, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
