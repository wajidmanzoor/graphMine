"""Legacy workflow reads produce only the runnable-problem contract."""
from copy import deepcopy
import pytest
from graphmine.workflows import validate_workflow
from graphmine.exceptions import GraphMineError
from graphmine.native import NativeLibrary


def inputs():
    return {'main': {'kind': 'graph', 'data': {
        'graph': {'id': 'migration', 'directed': False, 'allows_self_loops': False, 'allows_parallel_edges': False},
        'vertices': [{'id': i} for i in range(3)],
        'edges': [{'id': i, 'source': u, 'target': v} for i, (u, v) in enumerate([(0, 1), (1, 2), (0, 2)])]}}}


def plan():
    return {'version': 1, 'device': 'cpu', 'steps': [{'id': 'count', 'operation': 'triangle-counting',
        'input': {'input': 'main'}, 'parameters': {'mode': 'count'}}]}


def test_old_step_key_reads_and_canonical_writes():
    old = plan()
    copy = deepcopy(old)
    new = validate_workflow(old, inputs())
    assert old == copy
    assert new['plan']['steps'][0]['problem'] == 'triangle-counting'
    assert 'operation' not in new['plan']['steps'][0]
    canonical = plan()
    canonical['steps'][0]['problem'] = canonical['steps'][0].pop('operation')
    assert validate_workflow(canonical, inputs())['workflow_hash'] == new['workflow_hash']


def test_conflicting_step_identifiers_rejected():
    old = plan()
    old['steps'][0]['problem'] = 'pagerank'
    with pytest.raises(GraphMineError, match='Conflicting'):
        validate_workflow(old, inputs())


def test_native_legacy_key_has_only_new_result_identity():
    result = NativeLibrary().request({'command': 'run', 'operation': 'triangle-counting',
        'graph': inputs()['main']['data'], 'device': 'cpu', 'parameters': {'mode': 'count'}})
    assert result['problem'] == 'triangle-counting' and 'operation' not in result
    assert result['result']['count'] == 1
