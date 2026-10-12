#!/usr/bin/env python3
"""Offline integrity checks for the 2026-10-09 upstream artifact collection.

This checks collection integrity, not algorithm correctness or GPU performance.
Run from any directory: python3 problems/_collection/validate.py
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(__file__).with_name('expansion_2026_10_09.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate():
    errors = []
    counts = dict(problems=0, algorithm_records=0, problems_meeting_three_local_pairs=0,
                  eligible_local_pairs=0, local_gpu_source_entries=0,
                  local_main_papers=0, upstream_source_snapshots=0)
    inventory = json.loads(REPORT.read_text())

    def check(condition, message):
        if not condition:
            errors.append(message)

    def pdf_ok(path, sha, label):
        if not path.is_file():
            errors.append(label + ': missing PDF')
            return
        check(path.read_bytes()[:5] == b'%PDF-', label + ': invalid PDF signature')
        check(bool(sha) and digest(path) == sha, label + ': PDF SHA-256 mismatch')

    seen_problems = set()
    for item in inventory['problems']:
        folder = ROOT / item['problem_dir']
        problem = json.loads((folder / 'problem.json').read_text())
        status = json.loads((folder / 'collection_status.json').read_text())
        label = folder.name
        check(status == item, label + ': inventory and collection status differ')
        check(problem['problem_id'] == item['problem_id'], label + ': problem ID mismatch')
        check(problem['problem_id'] not in seen_problems, label + ': duplicate problem ID')
        seen_problems.add(problem['problem_id'])
        for field in ['name', 'problem_statement', 'graph_input', 'problem_inputs',
                      'required_outputs', 'solution_semantics', 'validation_rules']:
            check(bool(problem.get(field)) or field == 'problem_inputs', label + ': missing ' + field)
        schema = (folder / problem['graph_input']['schema_ref']).resolve()
        check(schema.is_file() and schema.is_relative_to(ROOT), label + ': invalid schema reference')
        names = [x['name'] for x in problem['problem_inputs']]
        check(len(names) == len(set(names)), label + ': duplicate input names')
        expected_dirs = {a['paper_id'] for a in item['algorithms']}
        actual_dirs = {p.name for p in (folder / 'papers').iterdir() if p.is_dir()}
        check(expected_dirs == actual_dirs, label + ': unexpected or missing algorithm directory')
        eligible = references = code_count = paper_count = pairs_including_related = 0
        for row in item['algorithms']:
            d = folder / 'papers' / row['paper_id']
            key = label + '/' + row['paper_id']
            metadata = json.loads((d / 'metadata.json').read_text())
            artifacts = json.loads((d / 'artifact_status.json').read_text())
            check((d / 'README.md').is_file(), key + ': missing README')
            check(metadata['paper_id'] == d.name == artifacts['paper_id'], key + ': entry ID mismatch')
            check(metadata['problem_id'] == problem['problem_id'] == artifacts['problem_id'], key + ': parent ID mismatch')
            check(metadata['problem_dir'] == folder.name, key + ': parent directory mismatch')
            check(metadata['collection_only'] and not metadata['canonical_adapter_available'], key + ': unverified runtime claim')
            paper = artifacts['paper']
            code = artifacts['code']
            has_paper = paper['status'] == 'downloaded'
            has_code = code['status'] in ('downloaded_archive', 'downloaded_files')
            check(row['local_paper'] == has_paper, key + ': paper status mismatch')
            check(row['local_gpu_code'] == has_code, key + ': code status mismatch')
            if has_paper:
                check(paper['local_path'] == 'paper.pdf', key + ': unexpected PDF path')
                pdf_ok(d / paper['local_path'], paper.get('sha256'), key)
                check(paper.get('pdfinfo_valid') is True, key + ': PDF parsing was not verified')
            else:
                check(not (d / 'paper.pdf').exists(), key + ': undeclared paper PDF')
                check(bool(paper.get('error')), key + ': missing paper shortfall explanation')
            for extra in metadata.get('supplementary_papers', []):
                if extra['local_path']:
                    pdf_ok(d / extra['local_path'], extra.get('sha256'), key + '/supplementary')
            if has_code:
                link = d / 'code'
                check(link.is_symlink() and link.is_dir(), key + ': missing/broken code symlink')
                target = link.resolve()
                check(target.is_relative_to(ROOT / '_sources'), key + ': source link escapes collection')
                manifest = json.loads((d / code['source_manifest']).read_text())
                check(target == ROOT / '_sources' / manifest['local_path'], key + ': snapshot mismatch')
                check(code['commit'] == manifest.get('commit'), key + ': commit mismatch')
                check(code['source_url'] == manifest['source_url'], key + ': source URL mismatch')
                check(bool(metadata['code_entrypoints']), key + ': no implementation paths')
                check(set(code.get('entrypoint_sha256', {})) == set(metadata['code_entrypoints']), key + ': incomplete entrypoint hashes')
                for rel in metadata['code_entrypoints']:
                    path = link / rel
                    check(path.is_file(), key + ': missing source ' + rel)
                    if path.is_file():
                        check(digest(path) == code['entrypoint_sha256'].get(rel), key + ': source SHA-256 mismatch ' + rel)
                if code['license_file']:
                    check((d / code['license_file']).is_file(), key + ': invalid license path')
            else:
                check(not (d / 'code').exists(), key + ': unrecorded source directory')
                check(bool(code['error']), key + ': unexplained missing GPU code')
            qualifies = bool(metadata['counts_toward_three'])
            ref_pair = bool(metadata['has_upstream_code_and_verified_paper_reference'])
            check(qualifies == (ref_pair and has_paper), key + ': dishonest pair count')
            check(not ref_pair or (has_code and bool(metadata['publication_url']) and metadata['paper_role'] != 'none'), key + ': invalid paper reference pair')
            check(row['counts_toward_three'] == qualifies, key + ': eligibility mismatch')
            check(row['has_upstream_code_and_verified_paper_reference'] == ref_pair, key + ': reference eligibility mismatch')
            check(not qualifies or metadata['semantic_fit'] not in ['building_block', 'restricted_domain', 'related_variant'], key + ': partial implementation counted')
            check(code['build_status'] == code['runtime_status'] == 'not_tested', key + ': unsupported test claim')
            eligible += qualifies
            references += ref_pair
            paper_count += has_paper
            code_count += has_code
            pairs_including_related += has_paper and has_code
            counts['algorithm_records'] += 1
        check(item['entries'] == len(expected_dirs), label + ': entry count mismatch')
        check(item['eligible_local_code_and_paper_pairs'] == eligible, label + ': local pair total mismatch')
        check(item['eligible_code_and_paper_references'] == references, label + ': reference total mismatch')
        check(item['local_gpu_code_entries'] == code_count, label + ': source count mismatch')
        check(item['local_paper_entries'] == paper_count, label + ': PDF count mismatch')
        check(item['local_gpu_code_and_paper_including_related'] == pairs_including_related, label + ': related pair count mismatch')
        check(item['target_met'] == (eligible >= 3), label + ': target status mismatch')
        check(item['shortfall'] == max(0, 3 - eligible), label + ': shortfall count mismatch')
        check(eligible >= 3 or bool(item['shortfall_explanation']), label + ': unexplained shortfall')
        counts['problems'] += 1
        counts['problems_meeting_three_local_pairs'] += eligible >= 3
        counts['eligible_local_pairs'] += eligible
        counts['local_gpu_source_entries'] += code_count
        counts['local_main_papers'] += paper_count
    for path in (ROOT / '_sources').glob('*.json'):
        src = json.loads(path.read_text())
        check(src['status'] == 'downloaded', path.name + ': incomplete snapshot')
        base = ROOT / '_sources' / src['local_path']
        check(base.is_dir(), path.name + ': missing snapshot')
        if src.get('commit'):
            check(bool(re.fullmatch(r'[0-9a-f]{40}', src['commit'])), path.name + ': invalid commit')
            check(bool(re.fullmatch(r'[0-9a-f]{64}', src['archive_sha256'])), path.name + ': invalid archive hash')
        for file in src.get('files', []):
            check((base / file['path']).is_file(), path.name + ': missing downloaded file')
            if (base / file['path']).is_file():
                check(digest(base / file['path']) == file['sha256'], path.name + ': individual file hash mismatch')
        counts['upstream_source_snapshots'] += 1
    check(counts == inventory['totals'], 'Global inventory totals mismatch')
    return dict(ok=not errors, counts=counts, errors=errors,
                scope='Artifact integrity only; no builds, GPU execution, or benchmark validation.')


if __name__ == '__main__':
    result = validate()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
