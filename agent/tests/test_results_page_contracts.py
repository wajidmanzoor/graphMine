"""User-facing result summaries, context metadata and named report contracts."""
import base64
import io
import json
import struct
import zipfile
import zlib

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.analytics_answers import result_sentence
from graphmine_agent.analytics_exports import report_png
from graphmine_agent.result_tables import named_rows
from graphmine_agent.result_views import result_view
from graphmine_agent.view_actions import ExpandRequest, expand
from graphmine_agent.view_rules import type_shape
from test_view_overhaul import GOLDENS, Service
from test_workflow_templates import recipes


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b'')


def test_saved_biclique_summary_reports_actual_collection_not_selected_item(tmp_path):
    fixture = json.loads(next(p for p in GOLDENS if p.name.startswith('06-')).read_text())
    service = Service(tmp_path, fixture['result']); service.g = fixture['input']
    first = result_view(service, 'w', 'analysis', 'bicliques', expected_revision=1)
    other = result_view(service, 'w', 'analysis', 'bicliques', index=16, expected_revision=1)
    assert first['answer'] == other['answer']
    cards = {c['label']: c['value'] for c in first['answer']['metrics']}
    assert cards == {'Count': 33, 'Largest': '8 × 4', 'Typical size': 10.0, 'Coverage': '20 / 20'}
    assert first['answer']['sentence'] == result_sentence(fixture['result'], first['bipartite_names'])
    assert len(other['selected_vertices']) == 10
    assert not first['view_spec']['nodes']['shape']['field']
    assert {c['label'] for c in first['view_spec']['nodes']['color']['categories']} == set(first['bipartite_names'])


def test_expanded_context_keeps_input_degree_names_and_immutable_snapshot(tmp_path):
    service = Service(tmp_path)
    before = json.dumps(service.g)
    response = expand(service, 'w', 'analysis', 'out', ExpandRequest(expected_revision=1, vertices=[0], visible=[0]))
    text_zero = next(v for v in response['vertices'] if v['id'] == '0')
    assert text_zero['view']['degree'] == 3  # Two parallel incoming edges and one outgoing.
    assert text_zero['view']['display_name'] == 'Text zero'
    assert text_zero['view']['role'] == 'context' and not text_zero['view']['result']
    assert json.dumps(service.g) == before
    assert type_shape('User') == type_shape('user') == 'ellipse'
    assert type_shape('Business') == 'rectangle'


def test_named_csv_projection_preserves_typed_identity_and_plain_lists(tmp_path):
    service = Service(tmp_path)
    port = {'type': 'bipartite_groups', 'value': [{'left': [0, 9007199254740993], 'right': ['0']}]}
    assert list(named_rows(port, service.g)) == [{
        'index': 1, 'left_names': 'Number zero; Large ID', 'right_names': 'Text zero',
        'left_size': 2, 'right_size': 1, 'left_ids': '0; 9007199254740993', 'right_ids': '0',
    }]


def test_report_png_and_primary_output_are_revision_scoped(recipes):
    client, runtime, alice, bob, _, file, record, saved = recipes
    graph = runtime.graph_store.read_graph(file['id'], record['session_id'])
    runtime.analytics._write(runtime.analytics._directory(record) / 'inputs.json', {'main': {'kind': 'graph', 'data': graph}})
    image = png()
    body = {'expected_revision': record['revision'], 'step': 'core', 'port': 'count', 'default_image': base64.b64encode(image).decode()}
    url = '/api/workflows/original/report'
    response = client.post(url, headers=alice, json=body)
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read('default-view.png') == image
        assert json.loads(archive.read('manifest.json'))['primary_output'] == {'step': 'core', 'port': 'count'}
        assert 'inputs' not in json.loads(archive.read('request.json'))
    assert client.post(url, headers=bob, json=body).status_code == 404
    assert client.post(url, headers=alice, json={**body, 'expected_revision': record['revision'] + 1}).status_code == 409
    assert client.post(url, headers=alice, json={**body, 'port': 'missing'}).status_code == 422


def test_report_image_rejects_bad_encoding_and_excessive_dimensions():
    for encoded in ('not-base64', base64.b64encode(b'<svg/>').decode()):
        with pytest.raises(AnalyticsError, match='PNG'):
            report_png(encoded)
    image = bytearray(png()); image[16:24] = struct.pack('>II', 10000, 10000)
    with pytest.raises(AnalyticsError, match='dimensions'):
        report_png(base64.b64encode(image).decode())
