"""Actual libcudf file projections on each physical GPU."""

import csv
import hashlib
import json
from pathlib import Path

import pytest
from test_native_binding import GPU, ROOT, WRAPPER, library
from test_native_table_projection import fixture


@pytest.fixture(scope="session", autouse=True)
def projection_evidence(request):
    files = [
        Path(__file__),
        Path(__file__).with_name("test_native_table_projection.py"),
        WRAPPER,
        ROOT / "library/runtime/io/table_projection.cpp",
        GPU / "libgraphmine_runtime.so",
        GPU / "native-source-hashes.txt",
    ]

    def snapshot():
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
        }

    before = snapshot()
    yield
    unchanged = before == snapshot()
    if report := getattr(request.config.option, "xmlpath", None):
        Path(str(report) + ".metadata.json").write_text(
            json.dumps(
                {
                    "scope": "Native cuDF file joins, typed projection and aggregation on both physical GPUs",
                    "source_files": before,
                    "sources_unchanged_during_run": unchanged,
                    "collected_test_count": len(request.session.items),
                },
                indent=2,
            )
            + "\n"
        )
    assert unchanged


@pytest.mark.parametrize("gpu", [0, 1])
@pytest.mark.parametrize("policy", ["preserve", "sum", "min", "max", "count"])
def test_actual_cudf_tables_equal_the_sql_checked_inline_profile(tmp_path, gpu, policy):
    tables, projection = fixture()
    projection["duplicates"] = policy
    if policy == "count":
        projection.pop("weight")
        projection["task"] = "ranking"
    paths = {}
    for alias, source in tables.items():
        path = tmp_path / f"{alias}.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=source["data"]["columns"])
            writer.writeheader()
            writer.writerows(source["data"]["rows"])
        paths[alias] = {"path": str(path)}
    lib = library(GPU)
    expected = lib.project_graph(tables, projection)
    actual = lib.project_graph(paths, projection, gpu_device=gpu)
    assert actual["graph"]["vertices"] == expected["graph"]["vertices"]
    assert actual["graph"]["edges"] == expected["graph"]["edges"]
    assert actual["provenance"]["reader"] == "libcudf"
    for alias, source in actual["provenance"]["sources"].items():
        assert source["reader"] == "libcudf" and source["gpu_device"] == gpu
        assert source["python_runtime_required"] is False
        assert (
            source["input_sha256"]
            == hashlib.sha256(Path(paths[alias]["path"]).read_bytes()).hexdigest()
        )
