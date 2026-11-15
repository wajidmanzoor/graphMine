"""Isolation and deployment recovery checks; never touch real services or data."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import time

import pytest


SPEC = importlib.util.spec_from_file_location("environment_controller", Path(__file__).parents[1] / "environments.py")
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


@pytest.fixture
def config(tmp_path):
    roles = {}
    for i, name in enumerate(controller.ROLES):
        root = tmp_path / name
        root.mkdir()
        roles[name] = {
            "branch": name, "code": str(root / "code"), "python": str(root / "venv/bin/python"),
            "services": [f"{name}-agent", f"{name}-studio"],
            "studio_workspace": str(root / "studio/workspace"), "studio_data_root": str(root / "studio/datasets"),
            "studio_host": "127.0.0.1", "studio_port": 8877 + i,
            "env": {"GRAPHMINE_AGENT_DATA_ROOT": str(root / "store"),
                    "GRAPHMINE_BACKUP_DIR": str(root / "backups"),
                    "GRAPHMINE_DATABASE_SOURCES_FILE": str(root / "sources.json"),
                    "GRAPHMINE_API_HOST": "127.0.0.1", "GRAPHMINE_API_PORT": str(18000 + i),
                    "GRAPHMINE_LLM_ENABLED": "false" if name == "devlopment" else "true",
                    "CUDA_VISIBLE_DEVICES": "-1" if name == "devlopment" else "0,1"},
        }
    return {"version": 1, "environments": roles, "state_directory": str(tmp_path / "state"),
            "validation_commands": [["{python}", "-m", "pytest"]]}


def test_independent_configuration_is_valid(config):
    controller.validate_config(config)


@pytest.mark.parametrize("field", ["GRAPHMINE_AGENT_DATA_ROOT", "GRAPHMINE_BACKUP_DIR", "GRAPHMINE_CAPTURE_ROOT"])
def test_testing_cannot_write_any_production_store(config, field):
    roles = config["environments"]
    roles["testing"]["env"][field] = roles["production"]["env"]["GRAPHMINE_AGENT_DATA_ROOT"] + "/nested"
    with pytest.raises(ValueError, match="overlaps"):
        controller.validate_config(config)


def test_symlink_does_not_bypass_storage_isolation(config, tmp_path):
    roles = config["environments"]
    root = Path(roles["production"]["env"]["GRAPHMINE_AGENT_DATA_ROOT"])
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    roles["testing"]["studio_workspace"] = str(alias)
    with pytest.raises(ValueError, match="overlaps"):
        controller.validate_config(config)


def test_testing_cannot_inherit_production_database_connections(config):
    roles = config["environments"]
    roles["testing"]["env"]["GRAPHMINE_DATABASE_SOURCES_FILE"] = roles["production"]["env"]["GRAPHMINE_DATABASE_SOURCES_FILE"]
    with pytest.raises(ValueError, match="connections"):
        controller.validate_config(config)


def test_development_cannot_accidentally_enable_live_model(config):
    config["environments"]["devlopment"]["env"]["GRAPHMINE_LLM_ENABLED"] = "true"
    with pytest.raises(ValueError, match="live LLM"):
        controller.validate_config(config)


def test_duplicate_ports_are_rejected(config):
    roles = config["environments"]
    roles["testing"]["studio_port"] = roles["production"]["studio_port"]
    with pytest.raises(ValueError, match="ports"):
        controller.validate_config(config)


def test_developer_shell_does_not_leak_data_paths(config, monkeypatch):
    monkeypatch.setenv("GRAPHMINE_CAPTURE_ROOT", "/production/captures")
    monkeypatch.setenv("PYTHONPATH", "/production/code")
    role = config["environments"]["testing"]
    env = controller.environment(role)
    assert "GRAPHMINE_CAPTURE_ROOT" not in env
    assert env["PYTHONPATH"].startswith(role["code"])


def test_pending_work_includes_database_jobs_and_only_live_leases(config):
    role = config["environments"]["production"]
    root = Path(role["env"]["GRAPHMINE_AGENT_DATA_ROOT"])
    root.mkdir()
    with sqlite3.connect(root / "agent.sqlite3") as db:
        db.executescript("CREATE TABLE database_jobs(status TEXT); CREATE TABLE account_leases(expires_at REAL);")
        db.executemany("INSERT INTO database_jobs VALUES (?)", [("running",), ("completed",)])
        db.executemany("INSERT INTO account_leases VALUES (?)", [(time.time() - 60,), (time.time() + 60,)])
    assert controller.pending(role) == 2


def mock_git(role, *args):
    if args == ("rev-parse", "HEAD"):
        return "old" if role["branch"] == "production" else "candidate"
    if args[0] == "rev-parse":
        return "candidate"
    return ""


def test_testing_start_failure_restores_production_and_keeps_llm_running(config, monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "git", mock_git)
    monkeypatch.setattr(controller, "clean", lambda role: None)
    monkeypatch.setattr(controller, "wait_idle", lambda role: None)
    monkeypatch.setattr(controller, "systemctl", lambda action, services: calls.append((action, services)))

    def health(role):
        if role["branch"] == "testing":
            raise RuntimeError("test startup failed")

    monkeypatch.setattr(controller, "health", health)
    with pytest.raises(RuntimeError, match="startup"):
        controller.begin_testing(config, "devlopment")
    assert calls[-1] == ("start", config["environments"]["production"]["services"])
    assert not (Path(config["state_directory"]) / "testing-session.json").exists()
    assert not any("vllm" in service for _, services in calls for service in services)


def test_failed_checks_do_not_approve_a_candidate(config, monkeypatch):
    path = Path(config["state_directory"]) / "testing-session.json"
    controller.write_json(path, {"commit": "candidate", "previous_production": "old", "verified_at": "previous run"})
    monkeypatch.setattr(controller, "git", mock_git)
    monkeypatch.setattr(controller, "clean", lambda role: None)
    monkeypatch.setattr(controller, "health", lambda role: None)

    def fail(*args, **kwargs):
        raise RuntimeError("regression failed")

    monkeypatch.setattr(controller, "command", fail)
    with pytest.raises(RuntimeError, match="regression"):
        controller.verify_testing(config)
    assert "verified_at" not in json.loads(path.read_text())


@pytest.mark.parametrize("state", [
    {"commit": "candidate", "previous_production": "old"},
    {"commit": "different", "previous_production": "old", "verified_at": "yesterday"},
])
def test_promotion_requires_verification_of_the_exact_commit(config, monkeypatch, state):
    controller.write_json(Path(config["state_directory"]) / "testing-session.json", state)
    monkeypatch.setattr(controller, "git", mock_git)
    monkeypatch.setattr(controller, "clean", lambda role: None)
    with pytest.raises(RuntimeError, match="exact candidate"):
        controller.promote(config)


def test_cancel_refuses_to_undo_an_already_changed_production(config, monkeypatch):
    controller.write_json(Path(config["state_directory"]) / "testing-session.json",
                          {"commit": "candidate", "previous_production": "other"})
    monkeypatch.setattr(controller, "git", mock_git)
    with pytest.raises(RuntimeError, match="already changed"):
        controller.cancel_testing(config)


def test_snapshot_creates_parent_and_preserves_both_studio_roots(config, monkeypatch):
    role = config["environments"]["production"]
    for field in ("studio_workspace", "studio_data_root"):
        p = Path(role[field])
        p.mkdir(parents=True)
        (p / "example.json").write_text('{"saved": true}')

    def backup(args, **kwargs):
        target = Path(args[-1])
        assert target.parent.is_dir()
        target.mkdir()

    monkeypatch.setattr(controller, "command", backup)
    target = Path(controller.snapshot(role))
    assert (target / "graphmine").is_dir()
    assert (target / "studio-workspace/example.json").read_text() == '{"saved": true}'
    assert (target / "studio-datasets/example.json").read_text() == '{"saved": true}'
