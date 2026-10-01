from __future__ import annotations

import json
import stat
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.catalog import Catalog
from graphmine_agent.config import Settings
from graphmine_agent.database import Database
from graphmine_agent.graph_store import GraphStore
from graphmine_agent.models import SessionRecord

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_binary(tmp_path: Path) -> Path:
    path = tmp_path / "graphmine"
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            from pathlib import Path
            import sys

            if len(sys.argv) > 1 and sys.argv[1] == "list":
                print(json.dumps({
                    "operation_count": 13,
                    "validated_backend_count": 26,
                    "compiled_backend_count": 1,
                    "operations": [{
                        "id": "maximal-cliques",
                        "backends": [{"id": "rdmce", "compiled": True, "validated": True}],
                    }],
                }))
                raise SystemExit(0)
            if len(sys.argv) > 2 and sys.argv[1] == "run":
                output = Path(sys.argv[sys.argv.index("--output") + 1])
                payload = {
                    "ok": True,
                    "provenance": {"backend": "rdmce", "test_double": True},
                    "warnings": [],
                    "output": {
                        "cliques": [[0, 1, 2]],
                        "returned_count": 1,
                        "complete": True,
                    },
                }
                output.write_text(json.dumps(payload), encoding="utf-8")
                print(json.dumps(payload))
                raise SystemExit(0)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def settings(tmp_path: Path, fake_binary: Path) -> Settings:
    base = Settings.from_env(REPOSITORY_ROOT)
    return replace(
        base,
        data_root=tmp_path / "data",
        graphmine_binary=fake_binary,
        api_token="test-secret",
        graph_gpu_uuid="GPU-test-graph",
        llm_gpu_uuid="GPU-test-llm",
        llm_enabled=False,
        max_upload_bytes=1_000_000,
        job_timeout_seconds=10,
    )


@pytest.fixture
def catalog(settings: Settings) -> Catalog:
    return Catalog(settings)


@pytest.fixture
def database(settings: Settings) -> Database:
    return Database(settings.database_path)


@pytest.fixture
def graph_store(settings: Settings, database: Database) -> GraphStore:
    return GraphStore(settings, database)


@pytest.fixture
def session(database: Database) -> SessionRecord:
    return database.create_session(SessionRecord(domain_id="fraud_detection"))


@pytest.fixture
def triangle_graph() -> bytes:
    return json.dumps(
        {
            "graph": {
                "id": "triangle",
                "directed": False,
                "allows_self_loops": False,
                "allows_parallel_edges": False,
            },
            "vertices": [{"id": 0}, {"id": 1}, {"id": 2}],
            "edges": [
                {"id": "01", "source": 0, "target": 1},
                {"id": "12", "source": 1, "target": 2},
                {"id": "02", "source": 0, "target": 2},
            ],
        }
    ).encode()
