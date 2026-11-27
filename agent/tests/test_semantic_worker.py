"""Cancellation cannot depend on a native call returning or stdout making progress."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from graphmine_agent.database_job_context import current_database_job
from graphmine_agent.database_jobs import WorkStopped
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.semantic_worker import run_worker


BODY = {"statement": "RETURN 1", "model": "mock", "call_limit": 1, "projection": "elements"}
GRAPH = {"graph": {"id": "empty", "directed": True}, "vertices": [], "edges": []}


def test_worker_receives_no_provider_credentials_and_cleans_request_files(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("GRAPHMINE_LLM_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-do-not-forward")
    script = """
import json, os, pathlib, stat, sys
request = pathlib.Path(sys.argv[-1])
assert request.stat().st_mode & 0o777 == 0o600
assert request.parent.stat().st_mode & 0o777 == 0o700
assert not any('KEY' in key or key.startswith('GRAPHMINE_') for key in os.environ)
assert 'PYTHONPATH' not in os.environ
assert json.loads(request.read_text())['request']['statement'] == 'RETURN 1'
(request.parent / 'result.json').write_text(json.dumps({'clean': True}))
print(json.dumps({'type': 'result'}), flush=True)
"""
    assert run_worker(GRAPH, BODY, command=[sys.executable, "-c", script], temporary_root=tmp_path) == {"clean": True}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("partial", [False, True])
def test_timeout_kills_and_reaps_worker_even_with_incomplete_stdout(tmp_path, partial):
    pid_path = tmp_path / "pid"
    script = f"""
import json, os, pathlib, sys, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
print(json.dumps({{'type':'progress','stage':'asking_model','usage':{{'calls':2}}}}), flush=True)
if {partial!r}:
    sys.stdout.write('{{'); sys.stdout.flush()
time.sleep(30)
"""
    started = time.monotonic()
    with pytest.raises(AnalyticsError) as error:
        run_worker(GRAPH, BODY, command=[sys.executable, "-c", script], timeout=0.4, temporary_root=tmp_path)
    assert error.value.code == "semantic_timeout"
    assert error.value.details == {"usage": {"calls": 2}}
    assert time.monotonic() - started < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)
    assert list(tmp_path.iterdir()) == [pid_path]


def test_cancellation_interrupts_blocked_child_and_retains_observed_usage(tmp_path):
    pid_path = tmp_path / "pid"
    script = f"""
import json, os, pathlib, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
print(json.dumps({{'type':'progress','stage':'asking_model','usage':{{'calls':3}}}}), flush=True)
time.sleep(30)
"""
    class Control:
        cancel = False
        def checkpoint(self, *args, **kwargs):
            if self.cancel:
                raise WorkStopped()
    control = Control()
    token = current_database_job.set(control)
    def progress(event):
        control.cancel = True
    try:
        with pytest.raises(WorkStopped) as error:
            run_worker(GRAPH, BODY, command=[sys.executable, "-c", script], progress=progress, temporary_root=tmp_path)
        assert error.value.details == {"usage": {"calls": 3}}
    finally:
        current_database_job.reset(token)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)
    assert list(tmp_path.iterdir()) == [pid_path]


@pytest.mark.parametrize("output", ['[]\\n', '{\\n', '{"type":"result"}\\n', '{"type":"unknown"}\\n', '{}'])
def test_incomplete_or_invalid_worker_protocol_never_publishes(tmp_path, output):
    script = "import sys; sys.stdout.write(" + repr(output.replace("\\n", "\n")) + "); sys.stdout.flush()"
    with pytest.raises(AnalyticsError) as error:
        run_worker(GRAPH, BODY, command=[sys.executable, "-c", script], temporary_root=tmp_path)
    assert error.value.code == "semantic_worker_failed"
    assert list(tmp_path.iterdir()) == []


def test_live_request_is_rejected_before_spawning(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A live request must not start a process")
    monkeypatch.setattr("graphmine_agent.semantic_worker.subprocess.Popen", forbidden)
    with pytest.raises(AnalyticsError) as error:
        run_worker(GRAPH, {**BODY, "statement": "RETURN llm('qwen','{answer STRING}')"})
    assert error.value.code == "semantic_controls_unsupported"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux parent-death supervision")
def test_worker_stops_when_its_supervisor_is_killed(tmp_path):
    pid_path = tmp_path / "worker-pid"
    child_script = f"""
import os, time, sys
from pathlib import Path
from graphmine_agent import semantic_engine, semantic_worker
def blocked_engine():
    marker = Path({str(pid_path)!r})
    marker.with_suffix('.tmp').write_text(str(os.getpid()))
    marker.with_suffix('.tmp').replace(marker)
    time.sleep(30)
    raise RuntimeError('fixture should have been killed')
semantic_engine.load_engine = blocked_engine
sys.exit(semantic_worker.child(Path(sys.argv[-1])))
"""
    supervisor_script = f"""
from pathlib import Path
from graphmine_agent.semantic_worker import run_worker
run_worker({GRAPH!r}, {BODY!r}, command={[sys.executable, '-c', child_script]!r}, temporary_root=Path({str(tmp_path)!r}))
"""
    def running(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False
    supervisor = subprocess.Popen([sys.executable, "-c", supervisor_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = None
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and supervisor.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid_path.exists(), "worker did not reach its supervised execution boundary"
        pid = int(pid_path.read_text())
        assert running(pid)
        supervisor.kill(); supervisor.wait(timeout=5)
        deadline = time.monotonic() + 3
        while running(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not running(pid)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        supervisor.wait(timeout=5)
        if pid is not None and running(pid):
            os.kill(pid, signal.SIGKILL)
