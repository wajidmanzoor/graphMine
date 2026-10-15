"""Launchers must not replace a service's production settings with checkout defaults."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import venv
from pathlib import Path

import pytest
from graphmine_agent.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_configured_worker_interpreter_keeps_its_virtual_environment(
    tmp_path, monkeypatch
):
    worker = tmp_path / "worker"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(worker)
    monkeypatch.setenv("GRAPHMINE_ANALYTICS_PYTHON", str(worker / "bin/python"))
    settings = Settings.from_env(ROOT)
    result = subprocess.run(
        [str(settings.analytics_python), "-c", "import sys; print(sys.prefix)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(result.stdout.strip()) == worker


@pytest.mark.parametrize("component", ["agent", "vllm"])
def test_service_environment_is_explicit_and_missing_file_fails(tmp_path, component):
    repository = tmp_path / "checkout with spaces"
    (repository / "deploy").mkdir(parents=True)
    (repository / "agent").mkdir()
    launcher = repository / "deploy" / f"start-{component}.sh"
    shutil.copy2(ROOT / "deploy" / launcher.name, launcher)
    binary = repository / ".venv/bin/graphmine-agent"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'data': os.environ.get('GRAPHMINE_AGENT_DATA_ROOT'), "
        "'pythonpath': os.environ.get('PYTHONPATH'), 'args': sys.argv[1:]}))\n"
    )
    binary.chmod(0o700)
    (repository / "agent/.env").write_text("GRAPHMINE_AGENT_DATA_ROOT=wrong-store\n")
    configuration = tmp_path / "production settings.env"
    configuration.write_text(
        "GRAPHMINE_AGENT_DATA_ROOT=production-store\nGRAPHMINE_LLM_MAX_NUM_SEQS=2\n"
    )
    environment = {
        "PATH": os.environ["PATH"],
        "GRAPHMINE_ENV_FILE": str(configuration),
        "GRAPHMINE_LLM_GPU_UUID": "test-gpu",
        "GRAPHMINE_VLLM_EXECUTABLE": str(binary),
    }
    completed = subprocess.run(
        ["bash", str(launcher)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(completed.stdout)
    assert report["data"] == "production-store"
    if component == "agent":
        assert report["pythonpath"] == str(repository / "agent")
        assert report["args"] == ["serve"]
    else:
        assert report["args"][report["args"].index("--max-num-seqs") + 1] == "2"
    configuration.unlink()
    missing = subprocess.run(
        ["bash", str(launcher)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "GRAPHMINE_ENV_FILE does not exist" in missing.stderr
    assert not missing.stdout
