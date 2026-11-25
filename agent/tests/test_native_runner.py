from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.catalog import Catalog
from graphmine_agent.database import Database
from graphmine_agent.execution import ExecutionError, GraphMineRunner
from graphmine_agent.graph_store import GraphStore
from graphmine_agent.models import ExecutionPlan, FileRole, SessionRecord
from graphmine_agent.planning import PlanValidationError, PlanValidator


def test_incompatible_native_version_is_rejected(
    settings, fake_binary: Path, tmp_path: Path
) -> None:
    incompatible = tmp_path / "graphmine-old"
    incompatible.write_text(
        fake_binary.read_text(encoding="utf-8").replace(
            '"library_version": "1.0.0"', '"library_version": "0.9.0"'
        ),
        encoding="utf-8",
    )
    incompatible.chmod(fake_binary.stat().st_mode)
    configured = replace(settings, graphmine_binary=incompatible)
    database = Database(configured.database_path)
    catalog = Catalog(configured)
    runner = GraphMineRunner(
        configured,
        catalog,
        GraphStore(configured, database),
        PlanValidator(catalog),
    )
    report = runner.probe()
    assert report.binary_available
    assert report.library_version == "0.9.0"
    assert report.error == (
        "GraphMine binary version 0.9.0 does not match agent version 1.0.0"
    )
    with pytest.raises(ExecutionError, match="does not match") as captured:
        runner.require_ready()
    assert captured.value.code == "binary_incompatible"
