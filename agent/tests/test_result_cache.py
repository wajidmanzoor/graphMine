"""Parsed-result retention is bounded by allocations, not just file count."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.result_cache import ResultCache, memory_size
from test_result_index import indexed_service  # noqa: F401


def artifact(tmp_path, name, size=100):
    path = tmp_path / (name + '.json')
    path.write_text(json.dumps({'value': name * size}))
    return path


def test_lru_eviction_accounts_for_bytes_and_hits(tmp_path):
    paths = [artifact(tmp_path, name, 10000) for name in 'abc']
    cache = ResultCache(24000)
    a, b = [cache.read(path, 20000) for path in paths[:2]]
    assert len(cache) == 2
    assert cache.read(paths[0], 20000) is a  # Most recently used.
    cache.read(paths[2], 20000)
    assert len(cache) == 2 and cache.bytes <= 24000
    assert cache.read(paths[0], 20000) is a
    assert cache.read(paths[1], 20000) is not b


def test_oversized_entry_bypasses_retention_without_evicting_other_files(tmp_path):
    cache = ResultCache(4000)
    small, large = artifact(tmp_path, 's', 50), artifact(tmp_path, 'L', 10000)
    saved = cache.read(small, 20000)
    first, second = cache.read(large, 20000), cache.read(large, 20000)
    assert first == second and first is not second
    assert cache.read(small, 20000) is saved and len(cache) == 1 and cache.bytes <= 4000


def test_disabled_cache_and_small_entry_count_bound(tmp_path):
    cache = ResultCache(0)
    path = artifact(tmp_path, 'a')
    first = cache.read(path, 10000)
    assert cache.read(path, 10000) == first and not cache and cache.bytes == 0
    cache = ResultCache(100000, max_entries=2)
    for name in 'abcd':
        cache.read(artifact(tmp_path, name), 10000)
    assert len(cache) == 2
    cache.clear(); assert not cache and cache.bytes == 0


def test_generation_change_same_size_and_mtime_cannot_reuse_stale_parse(tmp_path):
    path = artifact(tmp_path, 'a'); cache = ResultCache(10000)
    before = path.stat(); first = cache.read(path, 10000)
    other = artifact(tmp_path, 'b'); os.utime(other, ns=(before.st_atime_ns, before.st_mtime_ns)); other.replace(path)
    assert cache.read(path, 10000) != first and len(cache) == 1
    path.write_bytes(b'bad json')
    with pytest.raises(AnalyticsError) as error:
        cache.read(path, 10000)
    assert error.value.code == 'data_integrity' and not cache


def test_limits_apply_to_warm_entries_before_reading(tmp_path, monkeypatch):
    cache = ResultCache(10000); path = artifact(tmp_path, 'a')
    cache.read(path, 1000)
    def forbidden(*_, **__):
        raise AssertionError('Oversized source must not be opened')
    monkeypatch.setattr(type(path), 'open', forbidden)
    with pytest.raises(AnalyticsError, match='byte budget'):
        cache.read(path, 2)


def test_memory_estimate_covers_nested_objects_and_unicode(tmp_path):
    value = [{'label': '🐱' * 100, 'vertex': i} for i in range(100)]
    encoded = json.dumps(value, ensure_ascii=False).encode()
    assert memory_size(value, 10**9) > len(encoded)
    path = tmp_path / 'unicode.json'; path.write_bytes(encoded)
    cache = ResultCache(len(encoded))
    assert cache.read(path, 10**6) == value and not cache


def test_concurrent_cold_readers_parse_once(tmp_path, monkeypatch):
    from graphmine_agent import result_cache

    cache = ResultCache(10000); path = artifact(tmp_path, 'a')
    calls, original = [], result_cache.read_json
    def counted(*args):
        calls.append(1); return original(*args)
    monkeypatch.setattr(result_cache, 'read_json', counted)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: cache.read(path, 10000), range(24)))
    assert len(calls) == 1 and all(value is values[0] for value in values)
    assert cache.bytes <= cache.max_bytes


def test_public_result_remains_an_independent_copy(indexed_service):
    service, _, save = indexed_service
    save([{'score': 3}])
    first = service.result('indexed'); first['steps']['rank']['result']['ports']['output']['value'][0]['score'] = -9
    assert service.result('indexed')['steps']['rank']['result']['ports']['output']['value'] == [{'score': 3}]
    assert 0 < service.result_cache.bytes <= service.settings.analytics_result_cache_bytes


@pytest.mark.parametrize('values', [{'analytics_result_cache_bytes': -1}, {'analytics_max_exports': 0}, {'analytics_max_exports': 33}])
def test_cache_and_export_operator_bounds(settings, values):
    with pytest.raises(ValueError):
        replace(settings, **values)


def test_export_settings_are_loaded_and_cache_can_be_disabled(monkeypatch):
    from graphmine_agent.config import Settings

    monkeypatch.setenv('GRAPHMINE_ANALYTICS_RESULT_CACHE_BYTES', '0')
    monkeypatch.setenv('GRAPHMINE_ANALYTICS_MAX_EXPORTS', '3')
    settings = Settings.from_env()
    assert settings.analytics_result_cache_bytes == 0 and settings.analytics_max_exports == 3


@pytest.mark.parametrize('removed', [False, True])
def test_artifact_changed_during_parse_is_not_cached(tmp_path, monkeypatch, removed):
    from graphmine_agent import result_cache

    path = artifact(tmp_path, 'a'); cache = ResultCache(10000)
    original = result_cache.json.loads
    def changed(raw):
        value = original(raw)
        if removed:
            path.unlink()
        else:
            artifact(tmp_path, 'b').replace(path)
        return value
    monkeypatch.setattr(result_cache.json, 'loads', changed)
    with pytest.raises(AnalyticsError) as error:
        cache.read(path, 10000)
    assert error.value.code == 'revision_conflict' and not cache
