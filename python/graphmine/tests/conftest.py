import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def record_execution_evidence(request):
    root = Path(__file__).resolve().parents[1]

    def snapshot():
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.py"))
        }

    before = snapshot()
    metadata = {
        "python": sys.version,
        "device": os.environ.get("GRAPHMINE_TEST_DEVICE", "cpu"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "case_shard": os.environ.get("GRAPHMINE_CASE_SHARD"),
        "source_files": before,
        "packages": {},
    }
    for name in (
        "networkx",
        "numpy",
        "scipy",
        "cugraph-cu12",
        "nx-cugraph-cu12",
        "cupy-cuda12x",
    ):
        try:
            metadata["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            metadata["packages"][name] = None
    yield
    metadata["sources_unchanged_during_run"] = before == snapshot()
    xmlpath = getattr(request.config.option, "xmlpath", None)
    if xmlpath:
        path = Path(str(xmlpath) + ".metadata.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, indent=2) + "\n")
    assert metadata["sources_unchanged_during_run"], (
        "Source files changed during the test run; evidence must be regenerated"
    )
