"""Phase 1: optional startup, artifact identity, and the live-provider gate."""

import hashlib
import json
from importlib import metadata
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from graphmine_agent import semantic_engine
from graphmine_agent.api import create_app
from graphmine_agent.api_errors import register_error_handlers
from graphmine_agent.errors import AnalyticsError


HEADERS = {"Authorization": "Bearer test-secret"}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def reset_loader():
    semantic_engine.load_engine.cache_clear()
    yield
    semantic_engine.load_engine.cache_clear()


def test_startup_does_not_load_optional_native_engine(settings, monkeypatch):
    imported = []
    original = semantic_engine.importlib.import_module

    def guarded(name, *args, **kwargs):
        if name.startswith("ladybug"):
            imported.append(name)
            raise ImportError("The optional engine is absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(semantic_engine.importlib, "import_module", guarded)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health", headers=HEADERS).status_code == 200
    assert imported == []


def test_missing_engine_is_an_actionable_503(monkeypatch):
    def missing(_):
        raise metadata.PackageNotFoundError("graphmine-tento")

    monkeypatch.setattr(semantic_engine.metadata, "distribution", missing)
    app = FastAPI()
    register_error_handlers(app)

    # Phase 2 will wire real semantic routes to this dependency boundary.
    @app.get("/phase1/semantic-probe")
    def dependency_probe():
        semantic_engine.load_engine()

    with TestClient(app) as client:
        response = client.get("/phase1/semantic-probe", headers=HEADERS)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "semantic_unavailable"
        assert "deploy/tento/build.sh" in response.json()["error"]["message"]


@pytest.mark.parametrize("problem", ["version", "commit", "patches", "native_hash", "missing_native", "shadowed"])
def test_foreign_or_damaged_engine_is_rejected(tmp_path, monkeypatch, problem):
    lock = semantic_engine.engine_lock()
    package = tmp_path / "ladybug"
    package.mkdir()
    native = package / "_lbug.test.so"
    native.write_bytes(b"fixture native artifact")
    manifest = {
        "commit": lock["commit"], "backend": "pybind", "native_file": native.name,
        "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(), "patches": lock.get("patches", []),
    }
    version = lock["version"]
    if problem == "version":
        version = "0.0.1"
    elif problem == "commit":
        manifest["commit"] = "0" * 40
    elif problem == "patches":
        manifest["patches"] = []
    elif problem == "native_hash":
        native.write_bytes(b"replaced binary")
    elif problem == "missing_native":
        native.unlink()
    (package / "_graphmine_tento.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(semantic_engine.metadata, "distribution",
                        lambda _: SimpleNamespace(version=version, locate_file=lambda name: tmp_path / name))

    original = semantic_engine.importlib.import_module

    def foreign_import(name, *args, **kwargs):
        if not name.startswith("ladybug"):
            return original(name, *args, **kwargs)
        assert problem == "shadowed", "Bad provenance must fail before importing native code"
        return SimpleNamespace(__file__=str(tmp_path / "foreign/ladybug/__init__.py"))

    monkeypatch.setattr(semantic_engine.importlib, "import_module", foreign_import)
    with pytest.raises(AnalyticsError) as error:
        semantic_engine.load_engine()
    assert error.value.status == 503
    assert error.value.code == "semantic_incompatible"
    assert str(tmp_path) not in str(error.value)


def test_live_gate_does_not_claim_controls_the_engine_lacks(monkeypatch):
    lock = {**semantic_engine.engine_lock(), "live_blockers": ["strict_json_without_fallback"]}
    monkeypatch.setattr(semantic_engine, "engine_lock", lambda: lock)
    with pytest.raises(AnalyticsError) as error:
        semantic_engine.require_live_controls()
    assert error.value.status == 503
    assert error.value.code == "semantic_controls_unsupported"


def test_installed_engine_smoke_and_live_gate():
    try:
        metadata.version("graphmine-tento")
    except metadata.PackageNotFoundError:
        pytest.skip("Install the locally built semantic wheel for the native smoke")
    for arguments, expected_code, expected_status in (([], 0, "passed"), (["--live"], 2, "blocked")):
        result = subprocess.run(
            [sys.executable, str(ROOT / "deploy/tento/smoke.py"), *arguments],
            capture_output=True, text=True, timeout=55,
        )
        assert result.returncode == expected_code, result.stdout
        report = json.loads(result.stdout)
        assert report["status"] == expected_status
        assert report["mock"]["status"] == "passed"
        assert report["engine"]["commit"] == semantic_engine.engine_lock()["commit"]
        if arguments:
            assert report["live"]["requests_sent"] == 0
            assert report["error"]["code"] == "semantic_live_configuration"
