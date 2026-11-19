import asyncio
from dataclasses import replace
import time
import sys

import httpx
import pytest

from graphmine_agent.llm_power import (
    LLMPower, LLMPowerBusy, LLMPowerRegistry, LLMUnavailable,
    get_registry, model_run, power_notice,
)


class Server:
    def __init__(self, *, sleeping=True, supported=True):
        self.sleeping, self.supported = sleeping, supported
        self.calls, self.sleep_failure, self.stuck = [], False, False

    async def __call__(self, request):
        assert request.headers['Authorization'] == 'Bearer test-key'
        self.calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == '/is_sleeping':
            return httpx.Response(200, json={'is_sleeping': self.sleeping}) if self.supported else httpx.Response(404)
        if request.url.path == '/wake_up':
            await asyncio.sleep(.005)
            if not self.stuck:
                self.sleeping = False
        elif request.url.path == '/sleep':
            assert request.url.params['level'] == '1'
            if self.sleep_failure:
                return httpx.Response(500)
            self.sleeping = True
        elif request.url.path == '/v1/models':
            assert not self.sleeping
            return httpx.Response(200, json={'data': [{'id': 'test'}]})
        else:
            raise AssertionError(request.url)
        return httpx.Response(200)

    def count(self, path):
        return sum(url == path for _, url, _ in self.calls)


def manager(tmp_path, server, **kwargs):
    return LLMPower('http://model.test/v1', 'test-key', transport=httpx.MockTransport(server),
                    lease_dir=tmp_path, poll_seconds=.005, **kwargs)


async def test_ten_concurrent_requests_wake_once_and_verify_models(tmp_path):
    server = Server()
    power = manager(tmp_path, server)
    try:
        await asyncio.gather(*(power.ensure_awake() for _ in range(10)))
        assert server.count('/wake_up') == server.count('/v1/models') == 1
        assert not power.status()['sleeping'] and power.status()['in_flight'] == 0
        assert power.status()['last_wake_seconds'] >= 0
    finally:
        await power.close()


async def test_404_disables_controls_and_is_rechecked_after_ten_minutes(tmp_path):
    server, now = Server(supported=False), [time.time()]
    power = manager(tmp_path, server, clock=lambda: now[0])
    try:
        await power.ensure_awake()
        assert not power.status()['enabled']
        await power.ensure_awake()
        now[0] += 599
        await power.sleep_now()
        assert server.count('/is_sleeping') == 1
        assert server.count('/sleep') == server.count('/wake_up') == 0
        now[0] += 2
        server.supported = True
        await power.ensure_awake()
        assert power.enabled and server.count('/wake_up') == 1
    finally:
        await power.close()


async def test_idle_sleep_and_stream_lifetime_including_cancellation(tmp_path):
    server, now = Server(sleeping=False), [time.time()]
    power = manager(tmp_path, server, clock=lambda: now[0])
    try:
        now[0] += 1201
        await power.idle_once()
        assert server.count('/sleep') == 1  # First idle period, not two periods.
        entered = asyncio.Event()

        async def stream():
            async with power.request():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(stream())
        await entered.wait()
        now[0] += 3000
        await power.idle_once()
        with pytest.raises(LLMPowerBusy):
            await power.sleep_now()
        assert power.in_flight == 1 and server.count('/sleep') == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert power.in_flight == 0
        await power.idle_once()
        assert server.count('/sleep') == 1
        now[0] += 1201
        await power.idle_once()
        assert server.count('/sleep') == 2
    finally:
        await power.close()


async def test_failed_idle_sleep_retries_without_stopping_the_agent(tmp_path, caplog):
    server, now = Server(sleeping=False), [time.time()]
    power = manager(tmp_path, server, clock=lambda: now[0])
    try:
        server.sleep_failure = True
        now[0] += 1201
        await power.idle_once()
        assert 'retry next minute' in caplog.text
        server.sleep_failure = False
        now[0] += 60
        await power.idle_once()
        assert power.sleeping and server.count('/sleep') == 2
    finally:
        await power.close()


async def test_wake_timeout_is_clear_and_releases_leases(tmp_path):
    server = Server()
    server.stuck = True
    power = manager(tmp_path, server, wake_timeout=.035)
    states = []
    try:
        with power_notice(states.append), pytest.raises(LLMUnavailable, match='The model is waking up and did not respond in time'):
            await power.ensure_awake()
        assert states == ['waking'] and power.in_flight == 0
        assert not power._waking
        server.stuck = False
        await power.ensure_awake()
        await power.sleep_now()
        assert server.count('/sleep') == 1
    finally:
        await power.close()


async def test_other_manager_cannot_sleep_during_a_shared_run(tmp_path):
    server, now = Server(sleeping=False), [time.time()]
    first = manager(tmp_path, server, clock=lambda: now[0])
    second = manager(tmp_path, server, clock=lambda: now[0])
    try:
        async with first.request():
            now[0] += 3000
            await second.idle_once()
            with pytest.raises(LLMPowerBusy, match='another GraphMine process'):
                await second.sleep_now()
            assert server.count('/sleep') == 0
        await second.idle_once()
        assert server.count('/sleep') == 0  # Completion resets the shared idle clock.
        now[0] += 1201
        await second.idle_once()
        assert server.count('/sleep') == 1
    finally:
        await first.close()
        await second.close()


async def test_live_evaluation_process_holds_a_kernel_lease_until_exit(tmp_path):
    server = Server(sleeping=False)
    power = manager(tmp_path, server)
    process = None
    try:
        await power.ensure_awake()
        path = power._directory / (power._key + '.requests')
        process = await asyncio.create_subprocess_exec(sys.executable, '-c',
            'import fcntl,sys\nf=open(sys.argv[1],"r+")\nfcntl.flock(f,fcntl.LOCK_SH)\nprint("leased",flush=True)\nsys.stdin.readline()\n',
            str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        assert await asyncio.wait_for(process.stdout.readline(), 5) == b'leased\n'
        assert process.returncode is None
        with pytest.raises(LLMPowerBusy):
            await power.sleep_now()
        assert server.count('/sleep') == 0
        process.stdin.write(b'finish\n')
        await process.stdin.drain()
        await asyncio.wait_for(process.wait(), 5)
        await power.sleep_now()
        assert server.count('/sleep') == 1
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        await power.close()


async def test_status_and_saved_calculations_never_wake(tmp_path):
    server = Server()
    power = manager(tmp_path, server)
    try:
        assert (await power.refresh_status())['sleeping']
        with pytest.raises(LLMUnavailable, match='asleep'):
            async with power.request(wake=False):
                pytest.fail('A sleeping server must not receive optional composition')
        assert server.count('/wake_up') == server.count('/v1/models') == 0
    finally:
        await power.close()


async def test_disabled_mode_has_no_power_http_calls(tmp_path):
    server = Server()
    power = manager(tmp_path, server, enabled=False)
    try:
        async with power.request():
            assert power.in_flight == 1
        await power.idle_once()
        await power.refresh_status()
        assert not server.calls
    finally:
        await power.close()


async def test_registry_separates_servers_and_learning_run_holds_between_calls(tmp_path, settings):
    settings = replace(settings, llm_base_url='http://model.test/v1', llm_api_key='test-key',
                       llm_sleep_mode=True, analytics_router_base_url='http://router.test/v1')
    server = Server()
    async with model_run(settings) as registry:
        assert get_registry(settings) is registry
        power = registry.for_url()
        power._directory, power._transport = tmp_path, httpx.MockTransport(server)
        assert registry.for_url('http://model.test') is power
        assert registry.for_url(settings.analytics_router_base_url) is not power
        async with power.request():
            assert power.in_flight == 2  # One run lease plus the HTTP call.
        assert power.in_flight == 1
        with pytest.raises(LLMPowerBusy):
            await power.sleep_now()
        async with power.request():
            assert power.in_flight == 2
        assert server.count('/wake_up') == 1
    assert power.in_flight == 0


async def test_idle_task_is_cancelled_on_shutdown(tmp_path):
    power = manager(tmp_path, Server())
    power.start()
    task = power._task
    assert not task.done()
    await power.close()
    assert task.cancelled() and power._task is None


async def test_router_404_does_not_disable_main_server(settings, tmp_path):
    settings = replace(settings, llm_base_url='http://model.test/v1', llm_api_key='test-key',
                       llm_sleep_mode=True, analytics_router_base_url='http://router.test/v1')
    registry = LLMPowerRegistry(settings)
    main_server, router_server = Server(), Server(supported=False)
    main, router = registry.for_url(), registry.for_url(settings.analytics_router_base_url)
    for power, server in [(main, main_server), (router, router_server)]:
        power._directory, power._transport = tmp_path, httpx.MockTransport(server)
    try:
        await router.ensure_awake()
        await main.ensure_awake()
        assert not router.enabled and main.enabled
        assert main_server.count('/wake_up') == 1 and router_server.count('/wake_up') == 0
    finally:
        await registry.close()


async def test_lease_stat_failure_does_not_stop_idle_checks(tmp_path, monkeypatch, caplog):
    power = manager(tmp_path, Server())
    def unavailable():
        raise PermissionError('Lease directory unavailable')
    monkeypatch.setattr(power, '_activity', unavailable)
    await power.idle_once()
    assert 'retry next minute' in caplog.text
    await power.close()
