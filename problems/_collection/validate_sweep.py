#!/usr/bin/env python3
"""Offline checks of the complete research collection, not GPU correctness."""
import argparse
from collections import Counter
import json
import math
import re
import subprocess

from acquire import ROOT, SOURCES, now, sha256, write_json
from validate import validate as validate_expansion

HERE = ROOT / '_collection'


def feature_input_errors(data):
    """Semantic constraints that JSON Schema cannot express across array rows."""
    errors, seen = [], set()
    for vector in data['vectors']:
        identity = (type(vector['id']).__name__, vector['id'])
        if identity in seen:
            errors.append('duplicate vector ID')
        seen.add(identity)
        if len(vector['values']) != data['dimension']:
            errors.append('vector dimension mismatch')
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) or
               not math.isfinite(x) for x in vector['values']):
            errors.append('non-finite or nonnumeric vector value')
    return errors


def validate():
    errors, notes, seen = [], [], set()
    counts = Counter()

    def check(condition, message):
        if not condition:
            errors.append(message)

    inventory = json.loads((HERE / 'research_inventory_2026_10_09.json').read_text())
    config = json.loads((HERE / 'sweep_additions_2026_10_09.json').read_text())
    expected = {p.name for p in ROOT.glob('[0-9][0-9]_*') if (p / 'problem.json').is_file()}
    check(expected == {x['problem_dir'] for x in inventory['problems']}, 'Inventory does not enumerate every problem folder')
    publication_pdfs = {}
    for item in inventory['problems']:
        folder = ROOT / item['problem_dir']
        label = folder.name
        spec = json.loads((folder / 'problem.json').read_text())
        check(spec['problem_id'] not in seen, label + ': duplicate problem ID')
        seen.add(spec['problem_id'])
        check(spec['problem_id'] == item['problem_id'], label + ': parent ID mismatch')
        check(json.loads((folder / 'collection_status.json').read_text()) == item, label + ': stale collection status')
        schema_path = (folder / spec['graph_input']['schema_ref']).resolve()
        check(schema_path.is_relative_to(ROOT) and schema_path.is_file(), label + ': invalid input schema')
        for field in ['problem_statement', 'required_outputs', 'solution_semantics', 'validation_rules', 'edge_cases']:
            check(bool(spec.get(field)), label + ': missing contract field ' + field)
        for field in ['problem_inputs', 'required_outputs']:
            names = [x['name'] for x in spec[field]]
            check(len(names) == len(set(names)), label + ': duplicate ' + field + ' names')
        if int(label[:2]) >= 61:
            check(spec.get('research_only') is True, label + ': missing research-only marker')
            for p in spec['problem_inputs']:
                if 'default' in p:
                    check(not p['required'], label + ': required input has a default')
                    if p['default'] is None:
                        check('null' in p['type'], label + ': null default has nonnullable type')
                    elif p['type'] == 'integer':
                        check(type(p['default']) is int, label + ': noninteger default')
                    elif p['type'] == 'number':
                        check(type(p['default']) in [int, float], label + ': nonnumeric default')
                    elif p['type'] == 'enum':
                        check(p['default'] in p['allowed_values'], label + ': enum default is not permitted')
        actual_ids = {p.parent.name for p in folder.glob('papers/*/metadata.json')}
        listed_ids = {x['paper_id'] for x in item['algorithms']}
        check(actual_ids == listed_ids, label + ': omitted or extra algorithm records')
        paper_index = json.loads((folder / 'gpu_papers.json').read_text())
        check({x['paper_id'] for x in paper_index['papers']} == actual_ids, label + ': stale paper index')
        local = Counter()
        for row in item['algorithms']:
            d = folder / 'papers' / row['paper_id']
            key = label + '/' + row['paper_id']
            m = json.loads((d / 'metadata.json').read_text())
            a = json.loads((d / 'artifact_status.json').read_text())
            check(m['paper_id'] == a['paper_id'] == row['paper_id'], key + ': inconsistent record ID')
            check(m['problem_id'] == a['problem_id'] == spec['problem_id'], key + ': inconsistent problem ID')
            check(row['counts_toward_three'] == bool(m.get('counts_toward_three')), key + ': stale eligibility')
            source_present = (d / 'code').is_dir()
            pdf_present = (d / 'paper.pdf').is_file()
            check(row['local_gpu_code'] == source_present, key + ': stale source presence')
            check(row['local_paper'] == pdf_present, key + ': stale PDF presence')
            check((a['paper']['status'] == 'downloaded') == pdf_present, key + ': paper status disagrees with disk')
            if pdf_present:
                pdf = d / 'paper.pdf'
                check(pdf.read_bytes().startswith(b'%PDF-'), key + ': invalid PDF signature')
                check(a['paper'].get('sha256') == sha256(pdf), key + ': PDF hash mismatch')
                check(a['paper'].get('pdfinfo_valid') is True, key + ': PDF has not passed parsing')
                publication_pdfs.setdefault(m.get('pdf_url'), pdf)
            else:
                check(bool(a['paper'].get('error')), key + ': unexplained missing paper')
            code = a['code']
            if source_present:
                check(code['status'] not in ['not_collected', 'download_failed'], key + ': source status disagrees with disk')
                paths = m.get('code_entrypoints', [])
                check(bool(paths), key + ': no inspected implementation paths')
                check(set(paths) == set(code.get('entrypoint_sha256', {})), key + ': incomplete source hashes')
                for rel in paths:
                    path = d / 'code' / rel
                    check(path.resolve().is_relative_to((d / 'code').resolve()), key + ': entrypoint escapes source tree')
                    check(path.is_file(), key + ': missing implementation file ' + rel)
                    if path.is_file():
                        check(sha256(path) == code['entrypoint_sha256'][rel], key + ': modified implementation file ' + rel)
                if code.get('license_file'):
                    check((d / code['license_file']).is_file(), key + ': missing recorded license')
                if code.get('source_manifest'):
                    manifest = json.loads((d / code['source_manifest']).read_text())
                    check((d / 'code').resolve() == (SOURCES / manifest['local_path']).resolve(), key + ': wrong pinned snapshot')
                    check(code.get('commit') == manifest.get('commit'), key + ': source commit mismatch')
            else:
                check(code['status'] == 'not_collected' or bool(code.get('error')), key + ': missing source has no explanation')
            qualifies = bool(m.get('counts_toward_three'))
            references = bool(m.get('has_upstream_code_and_verified_paper_reference'))
            check(qualifies == (references and pdf_present), key + ': invalid local pair classification')
            check(not references or (source_present and m.get('publication_url') and m.get('paper_role') != 'none'), key + ': invalid associated paper reference')
            check(not qualifies or m.get('semantic_fit') not in ['building_block', 'restricted_domain', 'related_variant', 'mismatch'], key + ': incompatible artifact counted')
            if m.get('sweep_managed'):
                check(m.get('collection_only') is True and m.get('canonical_adapter_available') is False, key + ': unsupported integration claim')
                check(code['build_status'] == code['runtime_status'] == 'not_tested', key + ': unsupported validation claim')
                check((d / 'ARTIFACT_STATUS.md').is_file(), key + ': missing artifact status document')
            else:
                check(m.get('collection_only') or m.get('collection_reviewed'), key + ': unreviewed legacy record')
            local.update(algorithm_records=1, local_gpu_source_entries=source_present, local_main_papers=pdf_present,
                         eligible_local_pairs=qualifies)
        check(item['entries'] == local['algorithm_records'], label + ': incorrect record count')
        check(item['eligible_local_code_and_paper_pairs'] == local['eligible_local_pairs'], label + ': incorrect pair count')
        check(item['target_met'] == (local['eligible_local_pairs'] >= 3), label + ': incorrect completion claim')
        check(item['shortfall'] == max(0, 3 - local['eligible_local_pairs']), label + ': incorrect shortfall')
        check(item['target_met'] or item.get('shortfall_explanation'), label + ': missing shortfall explanation')
        counts.update(local)
        counts.update(problems=1, problems_meeting_three_local_pairs=item['target_met'])
    counts['upstream_source_snapshots'] = len(list(SOURCES.glob('*.json')))
    check(dict(counts) == inventory['totals'], 'Global research totals are stale')
    expansion = validate_expansion()
    errors.extend('Expansion: ' + e for e in expansion['errors'])

    # Validate metadata/PDF identity once per new publication. Remove all
    # whitespace to allow headings that use letter-spacing or line wrapping.
    title_checks = []
    compact = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    for key, publication in config['publications'].items():
        pdf = publication_pdfs.get(publication.get('pdf_url'))
        if pdf is None:
            continue
        result = subprocess.run(['pdftotext', '-f', '1', '-l', '2', '-layout', str(pdf), '-'], capture_output=True, text=True, timeout=30)
        check(result.returncode == 0, key + ': PDF text extraction failed')
        match = compact(publication['title']) in compact(result.stdout)
        check(match, key + ': declared title not found on first two PDF pages')
        title_checks.append(dict(publication=key, title_matches_pdf=match, sha256=sha256(pdf)))

    try:
        from jsonschema import Draft202012Validator
        for name in ['feature_vectors_input', 'hypergraph_input', 'graph_input']:
            schema = json.loads((ROOT / (name + '.schema.json')).read_text())
            Draft202012Validator.check_schema(schema)
        schema = json.loads((ROOT / 'feature_vectors_input.schema.json').read_text())
        validator = Draft202012Validator(schema)
        good = dict(dataset_id='example', dimension=2, vectors=[dict(id='a', values=[0, 1]), dict(id=1, values=[1, 0])])
        check(not list(validator.iter_errors(good)) and not feature_input_errors(good), 'Feature-vector valid example rejected')
        check(bool(list(validator.iter_errors({**good, 'dimension': 0}))), 'Feature-vector schema accepts zero dimensions')
        bad = {**good, 'vectors': [dict(id='a', values=[0, 1]), dict(id='a', values=[1])]}
        check(set(feature_input_errors(bad)) == {'duplicate vector ID', 'vector dimension mismatch'}, 'Feature semantic constraints not enforced')
    except ImportError:
        errors.append('jsonschema is required to validate input schemas')
    manifest = json.loads((HERE / 'paper_manifest_2026_10_09.json').read_text())
    check(len(manifest['papers']) == counts['algorithm_records'], 'Global paper manifest is stale')
    return dict(ok=not errors, checked_at=now(), counts=dict(counts), publication_identity_checks=title_checks,
                errors=errors, notes=notes, scope='Offline collection integrity, reviewed source entrypoints, PDF identity and schemas. No GPU code execution or runtime integration validation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-report', action='store_true')
    args = parser.parse_args()
    result = validate()
    if args.write_report:
        write_json(HERE / 'validation_sweep_2026_10_09.json', result)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
