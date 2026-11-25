"""Studio uses runnable IDs while leaving historical training targets intact."""
from copy import deepcopy
import json
from pathlib import Path

import studio

ROOT = Path(__file__).resolve().parents[2]


def test_catalog_covers_native_problems_and_preserves_classic_cli_ids():
    catalog = studio.Catalog(ROOT)
    native = json.loads((ROOT / 'catalog/problems.json').read_text())
    identifiers = {key for problems in native.values() for key in problems}
    assert len(identifiers) == 82 and identifiers <= catalog.problems.keys()
    assert len(catalog.families) == 14
    assert {'graph-motifs', 'linear-assignment', 'temporal-motif-mining'} <= catalog.problems.keys()
    assert catalog.problems['k-core']['family'] == 'dense'
    assert catalog.topic_of_problem('k-core') == 'k_core_decomposition'
    assert 'rdmce' in catalog.backend_ids('maximal-cliques')
    public = catalog.public()
    assert 'operations' not in public
    assert all('parameters' not in topic and 'backends' not in topic for topic in public['topics'])


def test_legacy_tags_are_normalized_without_changing_source_annotations():
    catalog = studio.Catalog(ROOT)
    original = {'problem_id': 'k_core_decomposition', 'operation_id': 'k-core', 'backend': 'cpp'}
    before = deepcopy(original)
    assert studio.current_tags(original, catalog) == {
        'topic_id': 'k_core_decomposition', 'problem_id': 'k-core', 'backend': 'cpp'}
    assert original == before
    assert studio.current_tags({'problem_id': 'k_core_decomposition'}, catalog) == {'topic_id': 'k_core_decomposition'}
    assert studio.current_tags({'problem_id': 'k-core'}, catalog) == {'problem_id': 'k-core'}


def test_index_keeps_historical_training_messages_and_follows_current_problem_tags():
    original = {'messages': [
        {'role': 'system', 'content': 'Original contract'},
        {'role': 'user', 'content': json.dumps({'message': 'Find the core', 'selected_operation': {
            'operation_id': 'k-core', 'problem_id': 'k_core_decomposition'}})},
        {'role': 'assistant', 'content': json.dumps({'supported': True,
            'operation_id': 'k-core', 'problem_id': 'k_core_decomposition'})}]}
    before = deepcopy(original)
    record = studio._base_record(rid='old', adapter='planner', split='train', file='train.jsonl',
                                 row=0, offset=0, row_obj=original)
    tags = studio._auto_tags(record, None, None, [])
    assert tags['problem_id'] == 'k-core' and tags['topic_id'] == 'k_core_decomposition'
    assert record['row_sha256'] == studio.digest(original)
    assert record['output']['operation_id'] == 'k-core' and original == before
    record['output'] = {'status': 'ready', 'plan': {'steps': [{'problem': 'pagerank'}]}}
    record['payload_hints'] = {}
    assert studio._auto_tags(record, None, None, [])['problem_id'] == 'pagerank'
