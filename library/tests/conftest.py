"""Reproducible evidence for the independent native completion suites."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPLETION_MODULES = {
    "test_native_extended.py",
    "test_native_learning.py",
    "test_native_record_queries.py",
    "test_native_application_contracts.py",
    "test_native_table_projection.py",
}


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@pytest.fixture(scope="session", autouse=True)
def native_completion_evidence(request):
    if not any(item.path.name in COMPLETION_MODULES for item in request.session.items):
        yield
        return
    build = Path(os.environ["GRAPHMINE_NATIVE_CPU_BUILD"])
    library = build / "libgraphmine_runtime.so"
    catalog = json.loads(
        subprocess.check_output([build / "graphmine-native", "catalog"])
    )
    files = list((ROOT / "library/runtime").rglob("*.cpp")) + list(
        (ROOT / "library/runtime").rglob("*.hpp")
    )
    files += list((ROOT / "library/runtime").rglob("*.in"))
    files += [
        ROOT / "library/runtime/CMakeLists.txt",
        Path(__file__),
        ROOT / "library/include/graphmine/graph.hpp",
    ]
    files += list((ROOT / "python/graphmine/graphmine").rglob("*.py"))
    files += [
        ROOT / "library/manifests" / name
        for name in (
            "graphlet_atlas.json",
            "native_parameter_schemas.json",
            "problem_families.json",
        )
    ]
    files += [Path(item.path) for item in request.session.items]

    def snapshot():
        return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(files))}

    before, binary = snapshot(), sha(library)
    request.session.native_observed_operations = {}
    yield
    unchanged, same_binary = before == snapshot(), binary == sha(library)
    report = getattr(request.config.option, "xmlpath", None)
    if report:
        Path(str(report) + ".native.metadata.json").write_text(
            json.dumps(
                {
                    "implementation_sha256": catalog["implementation_sha256"],
                    "native_library_sha256": binary,
                    "source_files": before,
                    "sources_unchanged_during_run": unchanged,
                    "build_unchanged_during_run": same_binary,
                    "device": "cpu",
                    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                    "collected_test_count": len(request.session.items),
                    "observed_operations": request.session.native_observed_operations,
                    "scope": "Native C ABI calls with independent mathematical, learning, record and transport checks",
                },
                indent=2,
            )
            + "\n"
        )
    assert unchanged and same_binary, (
        "Native completion sources/build changed during verification"
    )
