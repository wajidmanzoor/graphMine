"""Six-hour execution and optional byte limits survive configuration and IO."""

import asyncio
import io
import json
import os
import subprocess
import sys

import pytest

from graphmine_agent.calculation_limits import minimum_limit, remaining_seconds, response_lines
from graphmine_agent.config import Settings
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.export_streams import copy_chunks
from graphmine_agent.result_cache import ResultCache


def test_calculations_default_to_six_hours_and_no_input_byte_cap(settings, monkeypatch):
    for key in ('JOB_TIMEOUT_SECONDS', 'ACCOUNT_JOB_SECONDS', 'BACKEND_DEFAULT_TIMEOUT_SECONDS',
                'MAX_RESULT_BYTES', 'MAX_UPLOAD_BYTES', 'ACCOUNT_UPLOAD_BYTES', 'ANALYTICS_MAX_INPUT_BYTES'):
        monkeypatch.delenv('GRAPHMINE_' + key, raising=False)
    current = Settings.from_env(settings.repository_root)
    assert current.job_timeout_seconds == current.account_job_seconds == current.backend_default_timeout_seconds == 21600
    assert current.analytics_max_input_bytes is current.max_upload_bytes is current.account_upload_bytes is None
    assert current.max_result_bytes is None
    assert minimum_limit(None, None) is None
    assert minimum_limit(None, 7200) == 7200
    assert remaining_seconds(None, 1e12) is None


@pytest.mark.parametrize('value,expected', [('none', None), ('', None), ('1024', 1024)])
def test_explicit_input_limits_and_unlimited_values(settings, monkeypatch, value, expected):
    for key in ('MAX_UPLOAD_BYTES', 'ACCOUNT_UPLOAD_BYTES', 'ANALYTICS_MAX_INPUT_BYTES'):
        monkeypatch.setenv('GRAPHMINE_' + key, value)
    current = Settings.from_env(settings.repository_root)
    assert (current.max_upload_bytes, current.account_upload_bytes, current.analytics_max_input_bytes) == (expected,) * 3


def test_workflow_worker_accepts_more_than_64_mib_without_an_input_budget():
    environment = dict(os.environ)
    environment.pop('GRAPHMINE_WORKER_INPUT_BYTES', None)
    script = 'from graphmine import worker; worker.handle = lambda request, emit: request; raise SystemExit(worker.main())'
    raw = b' ' * (64 * 1024 * 1024) + b'{"probe":"complete"}'
    process = subprocess.run([sys.executable, '-c', script], input=raw, capture_output=True,
                             env=environment, timeout=30, check=True)
    assert json.loads(process.stdout) == {'event': 'complete', 'result': {'probe': 'complete'}}


@pytest.mark.asyncio
async def test_protocol_output_can_exceed_the_stream_reader_buffer_limit():
    reader = asyncio.StreamReader(limit=32)
    payload = json.dumps({'result': 'x' * 300_000}).encode() + b'\n'
    reader.feed_data(payload + b'final')
    reader.feed_eof()
    assert [line async for line in response_lines(reader)] == [payload, b'final']


@pytest.mark.asyncio
async def test_explicit_protocol_budget_still_reports_a_resource_error():
    reader = asyncio.StreamReader()
    reader.feed_data(b'x' * 101)
    reader.feed_eof()
    with pytest.raises(AnalyticsError, match='byte budget'):
        _ = [line async for line in response_lines(reader, 100)]


def test_full_results_can_be_read_and_exported_without_a_byte_cap(tmp_path):
    payload = {'rows': list(range(100_001))}
    path = tmp_path / 'result.json'
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    cache = ResultCache(0)
    assert cache.read(path, None) == payload
    output = io.BytesIO()
    assert copy_chunks(io.BytesIO(raw), output, None) == len(raw)
    assert output.getvalue() == raw
