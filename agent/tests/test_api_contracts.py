"""Generated client types remain tied to real routes without service startup."""

import subprocess
import os
import sys
from pathlib import Path

from graphmine_agent.api import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_generation_does_not_start_services_or_open_application_storage(settings, monkeypatch):
    def forbidden(*_, **__): raise AssertionError("Schema generation started the runtime")
    monkeypatch.setattr("graphmine_agent.api.build_runtime", forbidden)
    app = create_app(settings)
    assert not hasattr(app.state, "runtime")
    schema = app.openapi()
    assert schema["components"]["schemas"]["CypherRequest"]["required"] == ["statement"]
    assert schema["components"]["schemas"]["WorkflowApproval"]["required"] == ["workflow_hash", "expected_revision"]
    assert not hasattr(app.state, "runtime")


def test_generated_contracts_and_type_checks_are_current():
    frontend = ROOT/"agent/frontend"
    for command in (["node", "generate-contracts.mjs", "--check"], ["node", "node_modules/typescript/bin/tsc", "-p", "tsconfig.json"]):
        completed = subprocess.run(command, cwd=frontend, capture_output=True, text=True, timeout=45, env={**os.environ, "GRAPHMINE_CONTRACT_PYTHON": sys.executable})
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_shared_transport_cancellation_and_lossless_request_contracts():
    completed = subprocess.run(["node", "--test", "tests/transport.test.cjs"], cwd=ROOT/"agent/frontend", capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
