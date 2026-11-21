"""Unlimited defaults survive configuration, large protocol messages and IO."""

import asyncio
import io
import json

import pytest

from graphmine_agent.calculation_limits import minimum_limit, remaining_seconds, response_lines
from graphmine_agent.config import Settings
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.export_streams import copy_chunks
from graphmine_agent.result_cache import ResultCache


def test_calculations_have_no_automatic_time_or_byte_cap(settings, monkeypatch):
    monkeypatch.delenv('GRAPHMINE_JOB_TIMEOUT_SECONDS', raising=False)
    monkeypatch.delenv('GRAPHMINE_MAX_RESULT_BYTES', raising=False)
    current = Settings.from_env(settings.repository_root)
    assert current.job_timeout_seconds is None and current.max_result_bytes is None
    assert minimum_limit(None, None) is None
    assert minimum_limit(None, 7200) == 7200
    assert remaining_seconds(None, 1e12) is None


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
