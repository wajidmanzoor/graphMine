"""Prepared exports retain exact data, enforce admission and clean up on failure."""

import asyncio
import csv
import io
import json
import re
import threading
import tracemalloc
import zipfile
from types import SimpleNamespace

import pytest
from starlette.requests import ClientDisconnect

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.analytics_exports import export_csv, export_json, report_bundle
from graphmine_agent.export_streams import CHUNK, Download, prepare_download, temporary
from graphmine_agent.table_artifacts import TableArtifacts
from test_exports_and_activity import recipes  # noqa: F401
from test_query_tables import query_table, source, workspace  # noqa: F401
from test_result_index import indexed_service  # noqa: F401

SCOPE = {'type': 'http', 'method': 'GET', 'asgi': {'spec_version': '2.4'}}


async def receive():
    return {'type': 'http.disconnect'}


async def test_download_chunks_close_and_admission_spans_transfer():
    service = SimpleNamespace(export_slots=asyncio.Semaphore(1))
    def build():
        stream = temporary(); stream.write(b'x' * (3 * CHUNK + 7)); return stream
    response = await prepare_download(service, build, filename='test.json', media_type='application/json')
    assert service.export_slots.locked()
    with pytest.raises(AnalyticsError) as error:
        await prepare_download(service, build, filename='second.json', media_type='application/json')
    assert error.value.code == 'busy' and error.value.status == 429
    lengths = []
    async def send(message):
        if message['type'] == 'http.response.body':
            lengths.append(len(message.get('body', b'')))
    await response(SCOPE, receive, send)
    assert sum(lengths) == 3 * CHUNK + 7 and max(lengths) <= CHUNK
    assert response.handle.closed and not service.export_slots.locked()
    assert response.headers['Cache-Control'] == 'private, no-store'
    response.close(); assert service.export_slots._value == 1


@pytest.mark.parametrize('failure', [OSError, asyncio.CancelledError])
async def test_disconnect_and_cancel_close_the_file(failure):
    stream = temporary(); stream.write(b'x' * CHUNK); released = []
    response = Download(stream, filename='test.json', media_type='application/json', release=lambda: released.append(True))
    async def send(message):
        if message['type'] == 'http.response.body':
            raise failure()
    with pytest.raises((ClientDisconnect, asyncio.CancelledError)):
        await response(SCOPE, receive, send)
    assert stream.closed and released == [True]


async def test_asgi_legacy_disconnect_closes_the_file():
    stream = temporary(); stream.write(b'x' * CHUNK)
    response = Download(stream, filename='test.json', media_type='application/json')
    async def send(_):
        await asyncio.sleep(0)
    await response({**SCOPE, 'asgi': {'spec_version': '2.0'}}, receive, send)
    assert stream.closed


async def test_cancelled_preparation_closes_its_late_result_and_retains_slot():
    service = SimpleNamespace(export_slots=asyncio.Semaphore(1))
    started, finish = threading.Event(), threading.Event()
    handles = []
    def build():
        handle = temporary(); handles.append(handle); started.set(); finish.wait(3)
        return handle
    pending = asyncio.create_task(prepare_download(service, build, filename='test', media_type='application/json'))
    assert await asyncio.to_thread(started.wait, 3)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert service.export_slots.locked()
    finish.set()
    async def cleaned():
        while service.export_slots.locked():
            await asyncio.sleep(.01)
    await asyncio.wait_for(cleaned(), 3)
    assert handles[0].closed


async def test_failed_preparation_releases_slot():
    service = SimpleNamespace(export_slots=asyncio.Semaphore(1))
    def failed():
        raise OSError('Disk unavailable')
    with pytest.raises(OSError):
        await prepare_download(service, failed, filename='test', media_type='application/json')
    assert not service.export_slots.locked()


def test_warm_large_csv_and_json_exports_do_not_load_full_results(indexed_service, monkeypatch):
    service, record, save = indexed_service
    save([{'vertex': i, 'text': 'x' * 256} for i in range(12000)])
    service.port_page('indexed', 'rank', 'output', 0, 1)
    service.result_summary('indexed', 1)
    def forbidden(*_, **__):
        raise AssertionError('Warm exports must use indexed rows or source byte chunks')
    monkeypatch.setattr(service, '_saved', forbidden)
    tracemalloc.start()
    try:
        with export_csv(service, 'indexed', 'rank', 'output') as stream:
            assert stream.tell() > 3_000_000
        with export_json(service, 'indexed') as stream:
            assert stream.tell() == (service._directory(record) / 'result.json').stat().st_size
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024
    assert not service.result_cache


def test_native_map_csv_preserves_original_shape(indexed_service):
    service, _, save = indexed_service
    value = {'a': [[1, 9007199254740993]], 'b': [['1', 2]]}
    save(value, 'motif_instances')
    with export_csv(service, 'indexed', 'rank', 'output') as stream:
        stream.seek(0); rows = list(csv.DictReader(io.StringIO(stream.read().decode('utf-8-sig'))))
    assert rows == [{'a': '[[1,9007199254740993]]', 'b': '[["1",2]]'}]


def test_warm_query_table_exports_avoid_full_blob_and_row_copies(workspace, monkeypatch):
    snapshot = query_table(workspace, monkeypatch)['table']; service = TableArtifacts(workspace.runtime)
    service.page(snapshot['id'])
    def forbidden(*_, **__):
        raise AssertionError('Warm export must not load the complete table')
    monkeypatch.setattr(TableArtifacts, 'load', forbidden)
    with service.export(snapshot['id'], 'json') as stream:
        stream.seek(0); exact = json.load(stream)
    assert exact['rows'][0]['source'] == 9007199254740993 and len(exact['rows']) == 125
    with service.export(snapshot['id'], 'csv', sort='amount', direction='desc') as stream:
        stream.seek(0); rows = list(csv.DictReader(io.StringIO(stream.read().decode('utf-8-sig'))))
    assert rows[0]['source'] == '9007199254741117' and len(rows) == 125


def test_report_over_budget_closes_partial_file(recipes, monkeypatch):
    from graphmine_agent import analytics_exports

    _, runtime, _, _, _, _, record, _ = recipes
    runtime.analytics._write(runtime.analytics._directory(record) / 'inputs.json', {})
    files, original, budget = [], analytics_exports.temporary, analytics_exports.Budget
    def tracked():
        value = original(); files.append(value); return value
    monkeypatch.setattr(analytics_exports, 'temporary', tracked)
    monkeypatch.setattr(analytics_exports, 'Budget', lambda _: budget(50))
    with pytest.raises(AnalyticsError, match='byte budget'):
        report_bundle(runtime.analytics, record['id'])
    assert files and all(file.closed for file in files)


def test_partial_download_keeps_completed_artifacts_and_enforces_revision(recipes):
    client, runtime, alice, bob, _, _, record, saved = recipes
    record.update(status='interrupted')
    record['validation']['order'] = ['core']
    runtime.analytics._save(record)
    runtime.analytics._write(runtime.analytics._directory(record) / 'step-core.json', saved['steps']['core'])
    path = '/api/workflows/original/result?partial=true&expected_revision=1'
    response = client.get(path, headers=alice)
    assert response.status_code == 200, response.text
    assert response.json()['partial_workflow'] and response.json()['steps'] == saved['steps']
    assert client.get(path, headers=bob).status_code == 404
    assert client.get(path.replace('revision=1', 'revision=2'), headers=alice).status_code == 409


def test_changed_source_during_json_copy_closes_unpublished_download(indexed_service, monkeypatch):
    from graphmine_agent import analytics_exports

    service, record, save = indexed_service; save([{'score': 1}])
    service.result_summary('indexed')
    handles, original_copy, original_temp = [], analytics_exports.copy_chunks, analytics_exports.temporary
    def tracked():
        handle = original_temp(); handles.append(handle); return handle
    def changed(*args):
        count = original_copy(*args)
        save([{'score': 2}])
        return count
    monkeypatch.setattr(analytics_exports, 'temporary', tracked)
    monkeypatch.setattr(analytics_exports, 'copy_chunks', changed)
    with pytest.raises(AnalyticsError) as error:
        export_json(service, record['id'])
    assert error.value.code == 'revision_conflict' and all(handle.closed for handle in handles)


def test_warm_report_does_not_retain_encoded_tables_or_archive(indexed_service):
    service, record, save = indexed_service
    rows = [{'vertex': i, 'text': 'x' * 256} for i in range(12000)]
    save(rows)
    record['validation']['workflow_hash'] = 'a' * 64; service._save(record)
    service._write(service._directory(record) / 'inputs.json', {})
    service._saved('indexed')  # Only export allocations are measured below.
    tracemalloc.start()
    try:
        stream = report_bundle(service, 'indexed')
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    with stream, zipfile.ZipFile(stream) as bundle:
        assert json.loads(bundle.read('result.json'))['steps']['rank']['result']['ports']['output']['value'] == rows
        assert len(bundle.read('tables/1-rank-output.csv')) > 3_000_000
    assert peak < 2 * 1024 * 1024


def test_offline_report_stream_preserves_exact_data_and_escapes_script_text():
    from graphmine_agent.models import ResultRecord
    from graphmine_agent.reporting import iter_report

    value = {'rows': [{'vertex': 9007199254740993, 'label': '</script><script>window.injected=true</script>\u2028🐱'}]}
    result = ResultRecord(job_id='job', session_id='session', operation_id='test', payload=value, summary={}, answer={})
    chunks = list(iter_report(result)); html = ''.join(chunks)
    data = re.search(r'<script id="graphmine-report" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data) == result.model_dump(mode='json')
    assert '<script>window.injected=true</script>' not in html and '\\u003c/script>' in data and '\\u2028' in data
    assert 'src="/vendor/' not in html and 'src="/app.js"' not in html and 'src="/account.js"' not in html
    assert max(map(len, chunks)) <= CHUNK * 6


def test_offline_report_large_rows_do_not_require_a_second_result_copy():
    from graphmine_agent.models import ResultRecord
    from graphmine_agent.reporting import iter_report

    result = ResultRecord(job_id='job', session_id='session', operation_id='test',
                          payload={'rows': [{'vertex': i, 'text': 'x' * 256} for i in range(20000)]}, summary={})
    tracemalloc.start()
    try:
        with temporary() as stream:
            for chunk in iter_report(result):
                stream.write(chunk.encode())
            assert stream.tell() > 5_000_000
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024


def test_feedback_download_uses_cursor_and_enforces_ownership(recipes, monkeypatch):
    client, runtime, alice, bob, _, _, record, _ = recipes
    path = f"/api/sessions/{record['session_id']}/feedback"
    response = client.post(path, headers=alice, json={'what_went_wrong': 'Exact IDs need context'})
    assert response.status_code == 201
    def forbidden(*_):
        raise AssertionError('Do not materialize all feedback annotations for a download')
    monkeypatch.setattr(runtime.database, 'feedback', forbidden)
    response = client.get(path + '/export', headers=alice)
    assert response.status_code == 200
    row = json.loads(response.content)
    assert row['review_status'] == 'unreviewed' and row['automatically_used_for_training'] is False
    assert row['annotation']['what_went_wrong'] == 'Exact IDs need context'
    assert client.get(path + '/export', headers=bob).status_code == 404


@pytest.mark.parametrize('suffix', ['/feedback/export', '/history/archive'])
def test_legacy_downloads_share_export_admission(recipes, suffix):
    client, runtime, alice, _, _, _, record, _ = recipes
    runtime.analytics.export_slots._value = 0
    try:
        response = client.get(f"/api/sessions/{record['session_id']}{suffix}", headers=alice)
        assert response.status_code == 429 and response.json()['error']['code'] == 'busy'
    finally:
        runtime.analytics.export_slots._value = runtime.settings.analytics_max_exports
