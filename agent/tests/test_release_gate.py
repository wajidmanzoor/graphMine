"""The release gate must include database work and state integration scope."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("local_release_gate", ROOT / "tools/check_local_release.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_local_release_includes_database_and_query_contracts():
    plan = gate.suite_plan()
    assert {
        "test_api_contracts",
        "test_studio_exchange",
        "test_database_connections", "test_database_workspace", "test_database_datasets", "test_database_jobs", "test_database_pools", "test_database_independent_sources", "test_database_sync", "test_database_mcp",
        "test_database_query_projection", "test_benchmark_datasets", "test_benchmark_mappings",
        "test_result_views", "test_result_resources", "test_result_context", "test_result_index", "test_result_cache", "test_export_streams", "test_dataset_paging", "test_query_previews", "test_session_search",
        "test_database_schema", "test_database_query_editor", "test_query_tables", "test_exploration", "test_workspace_recent", "test_conversation_timeline",
        "test_domain_ingestion_reports", "test_history_and_terminal", "test_storage_recovery",
    } <= {Path(path).stem for path in plan["backend"]}
    assert {
        "test_connection_setup", "test_database_query_editor", "test_query_previews", "test_database_jobs",
        "test_query_drafts", "test_workspace_navigation", "test_workspace_polling", "test_workspace_history", "test_workspace_incremental",
        "test_query_editor", "test_query_tables", "test_workspace_exploration", "test_workspace_data_layout", "test_workspace_accessibility", "test_workspace_home", "test_workspace_result_context",
        "test_result_exploration", "test_workspace_sources",
        "test_workspace_studio",
    } <= {Path(path).stem for path in plan["browser"]}
    assert not plan["database_backend"] and not plan["database_browser"] and not plan["gpu"]
    assert "agent/browser_tests/test_data_source_workspace.py" not in plan["browser"]
    for path in plan["backend"] + plan["browser"]:
        assert (ROOT / path).is_file()


def test_new_database_regressions_are_discovered(tmp_path):
    (tmp_path / "test_database_new_contract.py").write_text("")
    (tmp_path / "helper.py").write_text("")
    assert gate.discover(tmp_path, ("test_database*.py",)) == {"test_database_new_contract"}


def test_integrations_are_explicit_and_shell_flags_do_not_enable_them(tmp_path):
    original = {
        "GRAPHMINE_TEST_DATABASE_INTEGRATION": "1",
        "GRAPHMINE_TEST_BENCHMARK_INTEGRATION": "1",
        "GRAPHMINE_TEST_SYNC_NEO4J": "1",
        "GRAPHMINE_TEST_SYNC_NEO4J_URI": "bolt://127.0.0.1:1234",
        "GRAPHMINE_TEST_SYNC_NEO4J_PASSWORD": "unused-test-value",
        "GRAPHMINE_ANALYTICS_TEST_GPUS": "GPU-a,GPU-b",
        "GRAPHMINE_TEST_GRAPH_GPU_UUID": "GPU-a",
        "PATH": "/usr/bin",
    }
    env = gate.local_environment(tmp_path, original)
    assert all(key not in env for key in original if key != "PATH")
    assert original["GRAPHMINE_TEST_DATABASE_INTEGRATION"] == "1"
    plan = gate.suite_plan(databases=True, benchmarks=True, gpus=True)
    assert plan["database_backend"] == ["agent/tests/test_database_integration.py", "agent/tests/test_database_pool_integration.py", "agent/tests/test_database_sync_integration.py"]
    assert "agent/browser_tests/test_data_source_workspace.py" in plan["database_browser"]
    assert plan["benchmark_checks"] and len(plan["gpu"]) == 1


def test_prerequisite_failure_writes_an_honest_release_report(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "prerequisites", lambda **_: ["Missing native runtime"])
    output = tmp_path / "report"
    with pytest.raises(RuntimeError, match="Missing native runtime"):
        gate.main(output)
    report = json.loads((output / "summary.json").read_text())
    assert not report["passed"] and not report["steps"]
    assert report["prerequisite_errors"] == ["Missing native runtime"]
    assert set(report["integrations"].values()) == {"not requested"}


def test_skipped_checks_are_not_counted_as_passed(tmp_path):
    path = tmp_path / "checks.xml"
    path.write_text('<testsuites><testsuite><testcase classname="live" name="optional"><skipped/></testcase><testcase classname="local" name="required"/><testcase classname="broken" name="failure"><failure/></testcase></testsuite></testsuites>')
    result = gate.junit_summary(path)
    assert result == {"collected": 3, "passed": 1, "skipped": ["live.optional"]}
