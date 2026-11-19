"""Sleep memory checks use the active snapshot, never sum cached revisions."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('vllm_sleep_memory', Path(__file__).parents[1] / 'vllm_sleep_memory.py')
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


def test_active_snapshot_weight_size_and_memavailable_threshold(tmp_path, capsys):
    cache = tmp_path / 'cache/models--example--model'
    (cache / 'refs').mkdir(parents=True)
    (cache / 'refs/main').write_text('active')
    for revision, size in [('active', 8192), ('older', 32768)]:
        directory = cache / 'snapshots' / revision
        directory.mkdir(parents=True)
        (directory / 'model-1.safetensors').write_bytes(b'x' * size)
        (directory / 'model-2.safetensors').write_bytes(b'y' * size)
    env = {'GRAPHMINE_LLM_MODEL': 'example/model', 'HF_HUB_CACHE': str(tmp_path / 'cache')}
    assert memory.weight_bytes(env) == 16384
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text('MemTotal: 1000 kB\nMemAvailable: 20 kB\n')
    assert memory.sleep_is_safe(env, meminfo=meminfo)
    meminfo.write_text('MemAvailable: 19 kB\n')
    assert not memory.sleep_is_safe(env, meminfo=meminfo)
    assert 'MemAvailable' in capsys.readouterr().err
    assert memory.weight_bytes({**env, 'GRAPHMINE_LLM_REVISION': 'older'}) == 65536


def test_weight_override_and_unknown_cache_fail_safe(tmp_path, capsys):
    assert memory.weight_bytes({'GRAPHMINE_LLM_WEIGHT_BYTES': '300'}) == 300
    with pytest.raises(ValueError):
        memory.weight_bytes({'GRAPHMINE_LLM_WEIGHT_BYTES': '-1'})
    assert not memory.sleep_is_safe({'GRAPHMINE_LLM_MODEL': 'missing/model', 'HF_HUB_CACHE': str(tmp_path)})
    assert 'sleep mode disabled' in capsys.readouterr().err
