"""Blocked workloads must remain visible, including the runner's opt-in W22–W24."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tento_acceptance", ROOT / "deploy/tento/acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.fixture
def source():
    path = ROOT / "third_party/tento"
    if not (path / "ladybug/scripts/paper/workload.py").is_file():
        pytest.skip("initialize the pinned Tentō submodule for workload inventory checks")
    return path


def test_every_workload_is_recorded_without_claiming_execution(source, tmp_path):
    report = acceptance.inventory(source, tmp_path, "local-fixture-model")
    assert report["status"] == "blocked" and not report["runner"]["invoked"]
    assert report["completed_workloads"] == report["failed_workloads"] == report["provider_requests_sent"] == 0
    assert [row["query"] for row in report["workloads"]] == [f"W{i}" for i in range(1, 25)]
    for row in report["workloads"]:
        assert not row["execution_started"] and not row["database_present"]
        assert "workload_database_missing" in row["blockers"]
        assert row["usage"] is row["duration_seconds"] is row["effective_settings"] is row["quality"]["score"] is None
    assert all(row["requires_explicit_query_selection"] for row in report["workloads"][-3:])
    assert "answers enabled" in report["workloads"][-1]["requested_cache_policy"]
    assert report["workloads"][-1]["quality"]["optional_metric"]


def test_present_database_does_not_hide_missing_contracts_or_quality_inputs(source, tmp_path):
    data = tmp_path / "demo/semantic_movies.lbdb"
    data.parent.mkdir()
    data.write_bytes(b"fixture-presence-only")
    report = acceptance.inventory(source, tmp_path, "local-fixture-model")
    first = report["workloads"][0]
    assert first["database_present"] and "workload_database_missing" not in first["blockers"]
    assert "live_measurement_required" in first["blockers"]
    assert "quality_reference_missing" in first["blockers"]
    assert first["status"] == "blocked" and first["quality"]["score"] is None


def test_local_runner_records_missing_inputs_without_inference(source, tmp_path):
    import json
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(ROOT / 'deploy/tento/run_local.py'),
        '--data-root', str(tmp_path/'absent'), '--output', str(tmp_path/'report'),
        '--base-url', 'http://127.0.0.1:1/v1', '--model', 'unavailable-fixture', '--queries', 'W9'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stderr
    report = json.loads((tmp_path/'report/report.json').read_text())
    assert report['blocked_workloads'] == 24 and report['provider_requests_sent'] == 0
    assert not report['model']['verified_live']
    assert all(not row['execution_started'] for row in report['workloads'])


def test_original_route_scorer_accepts_prepared_export_columns(source, tmp_path):
    def load(name):
        spec = importlib.util.spec_from_file_location('tento_'+name, ROOT/'deploy/tento'/f'{name}.py')
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value
    prepare, local = load('prepare_data'), load('run_local')
    export = tmp_path/'paper_eval/export'
    export.mkdir(parents=True)
    incoming = tmp_path/'flight.csv'
    incoming.write_text('from,to\nJFK,LHR\n')
    prepare.export_flights(incoming, export/'flight.csv')
    for name, contents in {
        'review.csv':'id,text,sentiment_gt,critic,movie_id\n',
        'movie.csv':'id,title,genre_gt\n', 'person.csv':'id,name\n',
        'worked_on.csv':'person_id,movie_id,role\n',
        'airport.csv':'code,gt_country\nJFK,United States\nLHR,United Kingdom\n',
    }.items():
        (export/name).write_text(contents)
    quality = local.scorer(tmp_path)
    assert quality('W14', [[['JFK','LHR']]]) == 1.0
    assert quality('W14', [[['JFK','LHR']], [['JFK','MIA']]]) < 1.0
