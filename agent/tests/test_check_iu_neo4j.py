"""The operator probe cannot issue SSH implicitly or expose driver errors."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("iu_probe", Path(__file__).resolve().parents[2] / "scripts/check_iu_neo4j.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def remote():
    calls = []
    return SimpleNamespace(reachable=lambda: True, is_up=lambda **_: True,
                           ensure_awake=lambda: calls.append("wake"), calls=calls)


@pytest.fixture
def driver(monkeypatch):
    calls = []
    class Driver:
        def __init__(self, uri, **options):
            assert uri == "bolt://10.2.147.169:7689" and options["auth"] is None
        def __enter__(self): return self
        def __exit__(self, *_): pass
        @contextmanager
        def session(self, **options):
            assert options["default_access_mode"] == "READ"
            yield self
        def execute_read(self, function):
            calls.append("read")
            return function(self)
        def run(self, query):
            assert query == "RETURN 1 AS connected"
            return SimpleNamespace(single=lambda **_: {"connected": 1})
    monkeypatch.setattr("neo4j.GraphDatabase.driver", Driver)
    return calls


def test_default_probe_never_requests_wake(settings, remote, driver):
    report = probe.check(settings, remote=remote)
    assert report["return_1"] == 1 and report["bolt_connectivity"]
    assert remote.calls == [] and driver == ["read"]


def test_wake_is_explicit_and_never_attempted_without_vpn(settings, remote, driver):
    assert probe.check(settings, wake=True, remote=remote)["return_1"] == 1
    assert remote.calls == ["wake"]
    remote.reachable = lambda: False
    assert probe.check(settings, wake=True, remote=remote)["error"] == "VPN tunnel is down"
    assert remote.calls == ["wake"] and driver == ["read"]


def test_probe_does_not_print_exception_or_password(settings, remote, monkeypatch, capsys):
    import secrets
    secret = secrets.token_urlsafe(32)
    monkeypatch.setenv("GRAPHMINE_IU_SSH_PASSWORD", secret)
    def fail(**_): raise RuntimeError(secret)
    remote.is_up = fail
    report = probe.check(settings, remote=remote)
    assert "error" in report and secret not in str(report)
    output = capsys.readouterr()
    assert secret not in output.out + output.err
