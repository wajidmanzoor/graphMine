"""Remote power tests use fake sockets/SSH; no command is sent to the IU VM."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import multiprocessing
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent import remote_neo4j as remote


class Clock:
    def __init__(self):
        self.now = 1000.0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def power(settings):
    settings = replace(settings, iu_neo4j_autowake=True)
    clock, commands, events = Clock(), [], []
    up, reachable, busy = [False], [True], [False]
    def ssh(command):
        commands.append(command)
        up[0] = command == remote.COMMANDS["start"]
    manager = remote.RemoteNeo4j(settings, tcp=lambda *_: up[0], verify=lambda _: up[0],
        reachable=lambda: reachable[0], ssh=ssh, clock=clock, monotonic=clock, sleep=clock.sleep,
        jobs_running=lambda: busy[0], publish=events.append)
    return SimpleNamespace(manager=manager, clock=clock, commands=commands, events=events,
                           up=up, reachable=reachable, busy=busy)


def test_probe_caches_for_ten_seconds_and_never_wakes_or_records_activity(power):
    p = power
    p.up[0] = True
    assert p.manager.is_up()
    p.up[0] = False
    p.clock.sleep(9)
    assert p.manager.is_up()
    p.clock.sleep(1)
    assert not p.manager.is_up()
    assert not p.manager.path.exists() and not p.commands and not p.events


def test_probe_budget_includes_tcp_and_driver_verification(power):
    p = power
    remaining = []
    def tcp(address, timeout):
        assert address == ("10.2.147.169", 7689) and timeout == 1
        p.clock.sleep(1)
        return True
    p.manager.tcp = tcp
    p.manager.verify = lambda timeout: remaining.append(timeout) or True
    assert p.manager.is_up()
    assert remaining == [2]


def test_wake_records_ownership_and_safe_progress(power):
    p = power
    p.manager.ensure_awake()
    assert p.commands == ["sudo systemctl start neo4j"]
    state = p.manager._load()
    assert state["started_by_graphmine"] and state["started_at"] == p.clock.now
    assert p.manager.path.stat().st_mode & 0o777 == 0o600
    assert p.events[0]["message"] == "Starting the database, about 40 seconds…"
    p.manager.ensure_awake()
    assert len(p.commands) == 1


def test_disabled_autowake_allows_existing_server_but_never_starts_or_stops(power):
    p = power
    p.manager.settings = replace(p.manager.settings, iu_neo4j_autowake=False)
    with pytest.raises(AnalyticsError) as caught:
        p.manager.ensure_awake()
    assert caught.value.code == "database_autowake_disabled"
    p.up[0] = True
    p.clock.sleep(10)
    with p.manager.request():
        assert p.manager._load()["last_used"] == p.clock.now
    p.clock.sleep(2000)
    assert not p.manager.idle_once() and not p.commands


def test_vpn_down_never_attempts_ssh(power):
    p = power
    p.reachable[0] = False
    with pytest.raises(AnalyticsError, match="VPN tunnel is down"):
        p.manager.ensure_awake()
    assert p.commands == []


def test_delayed_bolt_is_polled_every_two_seconds(power):
    p = power
    p.manager.ssh = p.commands.append
    p.manager.tcp = lambda *_: p.clock.now >= 1040
    p.manager.verify = lambda _: True
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        p.clock.sleep(seconds)
    p.manager.sleep = sleep
    p.manager.ensure_awake()
    assert p.clock.now == 1040 and sleeps == [2] * 20
    assert p.commands == [remote.COMMANDS["start"]]


def test_wake_timeout_and_following_request_do_not_repeat_start(power):
    p = power
    p.manager.ssh = p.commands.append
    with pytest.raises(AnalyticsError, match="within 120 seconds") as caught:
        p.manager.ensure_awake()
    assert caught.value.code == "database_wake_timeout" and p.clock.now == 1120
    assert p.manager._load()["started_by_graphmine"]
    with pytest.raises(AnalyticsError) as caught:
        p.manager.ensure_awake()
    assert caught.value.code == "database_wake_backoff"
    assert p.commands == [remote.COMMANDS["start"]]


def test_ssh_failure_backs_off_five_minutes_without_logging_secrets(power, monkeypatch, caplog, capsys):
    p = power
    password, private_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv("GRAPHMINE_IU_SSH_PASSWORD", password)
    calls = []
    def fail(command):
        calls.append(command)
        raise RuntimeError(password + private_key)
    p.manager.ssh = fail
    with pytest.raises(AnalyticsError) as first:
        p.manager.ensure_awake()
    p.clock.sleep(299)
    with pytest.raises(AnalyticsError) as second:
        p.manager.ensure_awake()
    assert second.value.code == "database_wake_backoff" and len(calls) == 1
    p.clock.sleep(1)
    with pytest.raises(AnalyticsError) as third:
        p.manager.ensure_awake()
    assert len(calls) == 2
    captured = capsys.readouterr()
    output = caplog.text + captured.out + captured.err + str(first.value) + str(second.value) + str(third.value) + p.manager.path.read_text()
    assert password not in output and private_key not in output


def test_threads_and_instances_share_one_start(power):
    p = power
    started, release = threading.Event(), threading.Event()
    def ssh(command):
        p.commands.append(command)
        started.set()
        assert release.wait(3)
        p.up[0] = True
    p.manager.ssh = ssh
    second = remote.RemoteNeo4j(p.manager.settings, tcp=lambda *_: p.up[0], verify=lambda _: p.up[0],
                               reachable=lambda: True, ssh=ssh)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit((p.manager if i % 2 else second).ensure_awake) for i in range(8)]
        try:
            assert started.wait(2)
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
    assert p.commands == [remote.COMMANDS["start"]]


def _wake_worker(settings, up, starts, barrier, results):
    def ssh(command):
        assert command == remote.COMMANDS["start"]
        with starts.get_lock():
            starts.value += 1
        time.sleep(.1)
        up.value = 1
    manager = remote.RemoteNeo4j(settings, tcp=lambda *_: bool(up.value),
        verify=lambda _: bool(up.value), reachable=lambda: True, ssh=ssh)
    barrier.wait(timeout=5)
    manager.ensure_awake()
    results.put(manager._load()["started_by_graphmine"])


def test_processes_share_file_lock_for_one_start(power):
    ctx = multiprocessing.get_context("spawn")
    up, starts, barrier, results = ctx.Value("i", 0), ctx.Value("i", 0), ctx.Barrier(2), ctx.Queue()
    workers = [ctx.Process(target=_wake_worker, args=(power.manager.settings, up, starts, barrier, results)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert starts.value == 1
        assert results.get(timeout=2) and results.get(timeout=2)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        results.close()


def test_idle_stops_only_our_server_after_full_idle_interval(power):
    p = power
    p.manager.ensure_awake()
    p.clock.sleep(1799)
    assert not p.manager.idle_once()
    p.clock.sleep(1)
    assert p.manager.idle_once()
    assert p.commands == [remote.COMMANDS["start"], remote.COMMANDS["stop"]]
    assert not p.manager._load()["started_by_graphmine"]
    assert not p.manager.idle_once()


def test_never_stops_server_started_by_someone_else_or_on_release(power):
    p = power
    p.up[0] = True
    p.manager.ensure_awake()
    p.manager.release()
    p.clock.sleep(3600)
    assert not p.manager.idle_once() and not p.commands
    assert not p.manager._load()["started_by_graphmine"]


def test_live_sessions_jobs_disabled_controls_and_vpn_all_prevent_idle_stop(power):
    p = power
    with p.manager.request():
        p.clock.sleep(2000)
        assert not p.manager.idle_once()
    assert not p.manager._load()["leases"]
    p.clock.sleep(2000)
    p.busy[0] = True
    assert not p.manager.idle_once()
    p.busy[0] = False
    p.reachable[0] = False
    assert not p.manager.idle_once()
    p.reachable[0] = True
    p.manager.settings = replace(p.manager.settings, iu_neo4j_autowake=False)
    assert not p.manager.idle_once()
    assert p.commands == [remote.COMMANDS["start"]]


def test_two_environment_roots_share_activity_and_job_safety(power, tmp_path):
    p = power
    p.manager.ensure_awake()
    second_settings = replace(p.manager.settings, data_root=tmp_path / "other-environment")
    second = remote.RemoteNeo4j(second_settings, tcp=lambda *_: True, verify=lambda _: True,
        reachable=lambda: True, clock=p.clock, monotonic=p.clock, sleep=p.clock.sleep, ssh=p.commands.append)
    assert second.path == p.manager.path
    with second.request():
        p.clock.sleep(2000)
        assert not p.manager.idle_once()
    second_settings.data_root.mkdir()
    with sqlite3.connect(second_settings.data_root / "agent.sqlite3") as db:
        db.execute("CREATE TABLE database_jobs(status TEXT)")
        db.execute("INSERT INTO database_jobs VALUES ('running')")
    p.manager.jobs_running = p.manager._jobs_running
    p.clock.sleep(2000)
    assert not p.manager.idle_once()
    assert p.commands == [remote.COMMANDS["start"]]


def test_bad_state_fails_closed_without_revealing_contents(power):
    p = power
    p.manager.ensure_awake()
    state = p.manager._load()
    sensitive = secrets.token_urlsafe(32)
    state["phase"] = sensitive
    remote.atomic_json(p.manager.path, state)
    with pytest.raises(AnalyticsError) as caught:
        p.manager.status()
    assert sensitive not in str(caught.value)
    p.clock.sleep(2000)
    with pytest.raises(AnalyticsError):
        p.manager.idle_once()
    assert p.commands == [remote.COMMANDS["start"]]


@pytest.fixture
def ssh_double(settings, monkeypatch):
    password = secrets.token_urlsafe(32)
    monkeypatch.setenv("GRAPHMINE_IU_SSH_PASSWORD", password)
    key = b"test public host key"
    monkeypatch.setattr(remote, "HOST_KEY", "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("="))
    calls, written = [], []
    channel = SimpleNamespace(done=False, exit_status_ready=lambda: channel.done,
        recv_exit_status=lambda: 0, shutdown_write=lambda: None,
        recv_ready=lambda: True, recv=lambda _: b"[sudo] password for exouser: ", recv_stderr_ready=lambda: False)
    def write(value):
        written.append(value)
        channel.done = True
    class Client:
        def set_missing_host_key_policy(self, policy):
            self.policy = policy
        def connect(self, host, **options):
            assert host == "10.2.147.169" and options["username"] == "exouser"
            assert options["password"] == password
            assert options["allow_agent"] is False and options["look_for_keys"] is False
            self.policy.missing_host_key(self, host, SimpleNamespace(asbytes=lambda: key))
        def exec_command(self, command, **options):
            calls.append(command)
            channel.done = False
            assert options == {"timeout": 15, "get_pty": True}
            return SimpleNamespace(write=write, flush=lambda: None), SimpleNamespace(channel=channel), None
        def close(self):
            pass
    transport = remote.PinnedSSH(replace(settings, iu_neo4j_autowake=True), client_factory=Client)
    return SimpleNamespace(transport=transport, calls=calls, written=written, password=password, channel=channel)


def test_ssh_allows_only_three_exact_commands_and_passes_password_on_stdin(ssh_double):
    p = ssh_double
    assert set(remote.COMMANDS.values()) == {"sudo systemctl start neo4j", "sudo systemctl stop neo4j", "sudo systemctl status neo4j"}
    for command in remote.COMMANDS.values():
        assert p.transport.run(command) == 0
    assert p.calls == list(remote.COMMANDS.values())
    assert p.written == [p.password + "\n"] * 3
    for command in ("id", "sudo -S systemctl start neo4j", "sudo systemctl start neo4j; id", "sudo systemctl restart neo4j"):
        with pytest.raises(ValueError, match="not allowed"):
            p.transport.run(command)
    assert len(p.calls) == 3


def test_ssh_rejects_other_host_key_before_running_command(ssh_double, monkeypatch):
    monkeypatch.setattr(remote, "HOST_KEY", "SHA256:different")
    with pytest.raises(AnalyticsError, match="pinned key"):
        ssh_double.transport.run(remote.COMMANDS["start"])
    assert ssh_double.calls == ssh_double.written == []


def test_transport_itself_blocks_start_and_stop_when_disabled(ssh_double):
    p = ssh_double
    p.transport.settings = replace(p.transport.settings, iu_neo4j_autowake=False)
    for action in ("start", "stop"):
        with pytest.raises(AnalyticsError):
            p.transport.run(remote.COMMANDS[action])
    p.channel.recv_exit_status = lambda: 3
    assert p.transport.run(remote.COMMANDS["status"]) == 3
    assert p.calls == [remote.COMMANDS["status"]]


def test_ssh_does_not_send_password_to_a_command_that_needs_none(ssh_double):
    p = ssh_double
    p.channel.exit_status_ready = lambda: True
    assert p.transport.run(remote.COMMANDS["start"]) == 0
    assert p.written == []


def test_ssh_command_timeout_does_not_expose_output_or_credentials(ssh_double, caplog, capsys):
    p = ssh_double
    clock = Clock()
    p.transport.clock, p.transport.sleep = clock, clock.sleep
    p.channel.exit_status_ready = lambda: False
    p.channel.recv = lambda _: p.password.encode()
    with pytest.raises(AnalyticsError) as caught:
        p.transport.run(remote.COMMANDS["start"])
    output = capsys.readouterr()
    assert p.password not in str(caught.value) + caplog.text + output.out + output.err
    assert clock.now >= 1015 and not p.written
