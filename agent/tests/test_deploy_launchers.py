"""Launchers must not replace a service's production settings with checkout defaults."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import hashlib
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
    shutil.copy2(ROOT / "deploy/admin-model-settings.py", repository / "deploy/admin-model-settings.py")
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
        "GRAPHMINE_LLM_SLEEP_MODE": "0",
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


@pytest.fixture
def model_launcher(tmp_path):
    repository = tmp_path / "model checkout"
    (repository / 'deploy').mkdir(parents=True)
    (repository / 'agent').mkdir()
    for name in ('start-vllm.sh', 'vllm_sleep_memory.py', 'vllm-power.sh', 'admin-model-settings.py'):
        shutil.copy2(ROOT / 'deploy' / name, repository / 'deploy' / name)
    executable = repository / 'fake-vllm'
    executable.write_text('#!/usr/bin/env python3\nimport json,os,sys\nprint(json.dumps({"args":sys.argv[1:],"dev":os.getenv("VLLM_SERVER_DEV_MODE")}))\n')
    executable.chmod(0o700)
    (repository / '.venv/bin').mkdir(parents=True)
    (repository / '.venv/bin/python').symlink_to(sys.executable)
    env = {'PATH': os.environ['PATH'], 'GRAPHMINE_LLM_GPU_UUID': 'GPU-test',
           'GRAPHMINE_VLLM_EXECUTABLE': str(executable), 'GRAPHMINE_LLM_WEIGHT_BYTES': '1'}
    return repository, env


def launch_model(fixture, **settings):
    repository, env = fixture
    return subprocess.run(['bash', str(repository / 'deploy/start-vllm.sh')],
                          env={**env, **settings}, capture_output=True, text=True)


def test_admin_model_overrides_reach_real_launcher_arguments(model_launcher):
    import sqlite3
    repository, _ = model_launcher
    store = repository / ".graphmine-agent"
    store.mkdir()
    with sqlite3.connect(store / "agent.sqlite3") as db:
        db.execute("CREATE TABLE settings_overrides(key TEXT,value TEXT)")
        db.executemany("INSERT INTO settings_overrides VALUES (?,?)", [("GRAPHMINE_LLM_SLEEP_MODE", "false"), ("GRAPHMINE_LLM_MAX_NUM_SEQS", "8")])
    result = launch_model(model_launcher, GRAPHMINE_LLM_SLEEP_MODE="1", GRAPHMINE_LLM_MAX_NUM_SEQS="2")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "--enable-sleep-mode" not in data["args"]
    assert data["args"][data["args"].index("--max-num-seqs") + 1] == "8"
    with sqlite3.connect(store / "agent.sqlite3") as db:
        db.execute("UPDATE settings_overrides SET value=? WHERE key='GRAPHMINE_LLM_MAX_NUM_SEQS'", (json.dumps("$(touch bad)"),))
    result = launch_model(model_launcher)
    assert result.returncode != 0 and not result.stdout


def test_vllm_sleep_flag_environment_and_unchanged_disabled_command(model_launcher):
    sleeping = launch_model(model_launcher)
    assert sleeping.returncode == 0, sleeping.stderr
    enabled = json.loads(sleeping.stdout)
    assert enabled['dev'] == '1' and '--enable-sleep-mode' in enabled['args']
    disabled = launch_model(model_launcher, GRAPHMINE_LLM_SLEEP_MODE='0', VLLM_SERVER_DEV_MODE='1')
    assert disabled.returncode == 0, disabled.stderr
    old = json.loads(disabled.stdout)
    assert old['dev'] is None
    assert old['args'] == ['serve', 'Qwen/Qwen3.8-27B-FP8', '--host', '127.0.0.1', '--port', '8001',
        '--api-key', 'local-graphmine', '--tensor-parallel-size', '1', '--max-model-len', '32768',
        '--max-num-seqs', '2', '--gpu-memory-utilization', '0.88', '--reasoning-parser', 'qwen3',
        '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_xml', '--language-model-only', '--enable-prefix-caching']
    assert [arg for arg in enabled['args'] if arg != '--enable-sleep-mode'] == old['args']


@pytest.mark.parametrize('host', ['0.0.0.0', 'localhost', '::1', '192.0.2.1'])
def test_vllm_sleep_refuses_every_non_literal_ipv4_loopback(model_launcher, host):
    result = launch_model(model_launcher, GRAPHMINE_LLM_HOST=host)
    assert result.returncode != 0 and '127.0.0.1' in result.stderr
    assert not result.stdout


def test_vllm_low_available_memory_disables_sleep_with_warning(model_launcher):
    result = launch_model(model_launcher, GRAPHMINE_LLM_WEIGHT_BYTES=str(2**63))
    assert result.returncode == 0, result.stderr
    assert 'Warning' in result.stderr and 'MemAvailable' in result.stderr
    report = json.loads(result.stdout)
    assert '--enable-sleep-mode' not in report['args'] and report['dev'] is None


def test_vllm_only_supports_level_one(model_launcher):
    result = launch_model(model_launcher, GRAPHMINE_LLM_SLEEP_LEVEL='2')
    assert result.returncode != 0 and 'only level 1' in result.stderr


def test_sleep_keeps_both_lora_adapters_and_revision_flags(model_launcher):
    repository, _env = model_launcher
    settings = {'GRAPHMINE_LLM_MODEL': 'test-model', 'GRAPHMINE_LLM_REVISION': 'a' * 40}
    for stage in ('PLANNER', 'ANALYST'):
        directory = repository / stage
        directory.mkdir()
        (directory / 'adapter_config.json').write_text(json.dumps({'peft_type': 'LORA', 'r': 16}))
        weights = directory / 'adapter_model.safetensors'
        weights.write_bytes(b'authored-adapter-fixture')
        settings.update({f'GRAPHMINE_LLM_{stage}_MODEL': stage.lower(),
                         f'GRAPHMINE_LLM_{stage}_ADAPTER_PATH': str(directory),
                         f'GRAPHMINE_LLM_{stage}_ADAPTER_SHA256': hashlib.sha256(weights.read_bytes()).hexdigest()})
    result = launch_model(model_launcher, **settings)
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)['args']
    assert '--enable-sleep-mode' in args and '--enable-lora' in args
    assert args[args.index('--revision') + 1] == args[args.index('--tokenizer-revision') + 1] == 'a' * 40
    assert args[args.index('--lora-modules') + 1:args.index('--max-loras')] == [
        f'planner={repository / "PLANNER"}', f'analyst={repository / "ANALYST"}']
    assert args[-8:] == ['--max-loras', '2', '--max-cpu-loras', '2', '--max-lora-rank', '16', '--lora-dtype', 'bfloat16']
