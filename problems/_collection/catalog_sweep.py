#!/usr/bin/env python3
"""Materialize reviewed sweep entries and regenerate the research inventory.

The input is reviewed JSON, not discovered code. This script never runs source
artifacts and never makes a runtime-backend claim. Use --download to retrieve
papers; otherwise only already-local artifacts are used.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil

from acquire import ROOT, SOURCES, now, paper, sha256, write_json

HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'sweep_additions_2026_10_09.json'


def add_entry(row, publications, download=False):
    folder = ROOT / row['problem_dir']
    spec = json.loads((folder / 'problem.json').read_text())
    destination = folder / 'papers' / row['paper_id']
    destination.mkdir(parents=True, exist_ok=True)
    existing = destination / 'metadata.json'
    if existing.exists() and not json.loads(existing.read_text()).get('sweep_managed'):
        raise ValueError('Refusing to overwrite a pre-existing research record: ' + str(existing))
    publication = publications.get(row.get('publication'), {})
    source_key = row.get('source')
    source_manifest = json.loads((SOURCES / (source_key + '.json')).read_text()) if source_key else None
    local_source = SOURCES / source_manifest['local_path'] if source_manifest else None
    entrypoints = row.get('entrypoints', [])
    if local_source:
        for entrypoint in entrypoints:
            target = (local_source / entrypoint).resolve()
            if not target.is_relative_to(local_source.resolve()) or not target.is_file():
                raise ValueError('Missing/invalid implementation path: ' + str(target))
        if not entrypoints:
            raise ValueError('Code records require inspected implementation entrypoints')
        link = destination / 'code'
        if link.is_symlink():
            if link.resolve() != local_source.resolve():
                raise ValueError('Existing source link differs')
        elif link.exists():
            raise ValueError('Refusing to overwrite source directory')
        else:
            link.symlink_to(os.path.relpath(local_source, destination), target_is_directory=True)
    pdf_url = publication.get('pdf_url')
    artifact_path = destination / 'artifact_status.json'
    previous = json.loads(artifact_path.read_text()) if artifact_path.exists() else {}
    paper_status = previous.get('paper', dict(status='not_collected', source_url=pdf_url,
                                             local_path=None, error='No verified associated research PDF.'
                                             if not pdf_url else 'Not yet downloaded.'))
    if pdf_url and not (destination / 'paper.pdf').exists():
        # Reuse an existing copy only when the declared PDF URL is identical.
        for metadata_path in ROOT.glob('[0-9][0-9]_*/papers/*/metadata.json'):
            metadata = json.loads(metadata_path.read_text())
            candidate = metadata_path.with_name('paper.pdf')
            if metadata.get('pdf_url') == pdf_url and candidate.is_file():
                shutil.copyfile(candidate, destination / 'paper.pdf')
                break
    if pdf_url and ((destination / 'paper.pdf').exists() or download):
        try:
            paper_status = paper(pdf_url, destination / 'paper.pdf')
        except Exception as error:
            paper_status = dict(status='download_failed', source_url=pdf_url, local_path=None,
                                error=str(error), checked_at=now())
    semantic_fit = row.get('semantic_fit', 'variant')
    fit = semantic_fit not in ['building_block', 'restricted_domain', 'related_variant', 'mismatch']
    reference_pair = bool(local_source and publication.get('publication_url') and fit)
    eligible = reference_pair and paper_status['status'] == 'downloaded'
    licenses = source_manifest.get('license_files', []) if source_manifest else []
    metadata = dict(
        title=publication.get('title', row['algorithm_name'] + ' — upstream implementation documentation'),
        authors=publication.get('authors', []), year=publication.get('year', 2026),
        venue=publication.get('venue', 'Official upstream implementation and API documentation'),
        doi=publication.get('doi'), publication_url=publication.get('publication_url'),
        pdf_url=pdf_url, paper_id=row['paper_id'], problem_id=spec['problem_id'], problem_dir=folder.name,
        research_cutoff='2026-10-09', algorithm_name=row['algorithm_name'],
        code_url=source_manifest['source_url'] if source_manifest else row.get('code_url'),
        semantic_fit=semantic_fit, gpu_scope=row['gpu_scope'], notes=row['notes'],
        paper_role=publication.get('role', 'none'), code_entrypoints=entrypoints,
        documentation_urls=row.get('documentation_urls', []),
        counts_toward_three=eligible, has_upstream_code_and_verified_paper_reference=reference_pair,
        collection_only=True, canonical_adapter_available=False, supplementary_papers=[],
        sweep_managed=True, implementation_family=row.get('implementation_family', source_key),
        variant_constraints=row.get('variant_constraints', []),
        redistribution_status='upstream_license_present' if licenses else 'license_review_required',
        paper_version_commit_verified=False,
    )
    code_status = dict(status='downloaded_archive' if local_source else 'not_collected',
                       source_url=metadata['code_url'], local_path='code' if local_source else None,
                       commit=source_manifest.get('commit') if source_manifest else None,
                       license_file='code/' + licenses[0] if licenses else None,
                       license_note='Inspect upstream license and dependency notices before redistribution.',
                       error=None if local_source else row.get('code_shortfall', 'No verified public GPU artifact located.'),
                       build_status='not_tested', runtime_status='not_tested',
                       source_manifest='../../../_sources/' + source_key + '.json' if source_key else None,
                       submodules_materialized=False,
                       entrypoint_sha256={p: sha256(local_source / p) for p in entrypoints})
    write_json(existing, metadata)
    write_json(artifact_path, dict(problem_id=spec['problem_id'], paper_id=row['paper_id'],
                                  title=metadata['title'], checked_at=now(), paper=paper_status, code=code_status))
    lines = [metadata['algorithm_name'], '=' * len(metadata['algorithm_name']), '',
             'Problem: [' + spec['name'] + '](../../problem.json).', '', metadata['notes'], '',
             'GPU execution: ' + metadata['gpu_scope'], '',
             'Paper relationship: ' + metadata['paper_role'] + '.',
             'Paper: ' + (publication.get('publication_url') or 'No associated research paper verified.')]
    if metadata['code_url']:
        lines += ['Source: ' + metadata['code_url']]
    if local_source:
        lines += ['Pinned commit: `' + source_manifest['commit'] + '`.', '',
                  'Implementation paths:', '', *['- `code/' + p + '`' for p in entrypoints]]
    lines += ['', 'Artifact state: paper=' + paper_status['status'] + '; code=' + code_status['status'] + '.',
              'Counts toward three local pairs: ' + str(eligible).lower() + '.', '',
              'Build, GPU execution, benchmark reproduction, and canonical adapter: not tested / not supplied.',
              'Source availability is separate from license compatibility and runtime validation.', '']
    (destination / 'README.md').write_text('\n'.join(lines))
    (destination / 'ARTIFACT_STATUS.md').write_text(
        f"Artifact status\n===============\n\nPaper: {paper_status['status']}. Code: {code_status['status']}.\n\n"
        f"Eligible local source/paper pair: {str(eligible).lower()}.\n\n"
        f"Semantic fit: {semantic_fit}. {row['notes']}\n\n"
        'The source revision is pinned for this collection. Its exact correspondence to the paper experimental '
        'revision has not been established. Build, runtime correctness, performance and canonical integration were not tested.\n')
    return eligible


def summarize_problem(folder, coverage):
    spec = json.loads((folder / 'problem.json').read_text())
    rows = []
    for metadata_path in sorted((folder / 'papers').glob('*/metadata.json')):
        m = json.loads(metadata_path.read_text())
        artifact_path = metadata_path.with_name('artifact_status.json')
        a = json.loads(artifact_path.read_text()) if artifact_path.exists() else {}
        code = a.get('code', {})
        pdf = metadata_path.with_name('paper.pdf')
        source = metadata_path.with_name('code')
        legacy = not m.get('collection_only', False)
        rows.append(dict(paper_id=m['paper_id'], algorithm_name=m.get('algorithm_name', m['title']),
                         paper_role=m.get('paper_role', 'legacy_research_record'),
                         semantic_fit=m.get('semantic_fit'), local_gpu_code=source.is_dir(),
                         local_paper=pdf.is_file(),
                         counts_toward_three=bool(m.get('counts_toward_three', False)),
                         has_upstream_code_and_verified_paper_reference=bool(m.get('has_upstream_code_and_verified_paper_reference', False)),
                         legacy_record=legacy,
                         legacy_eligibility_not_reclassified=legacy and not m.get('collection_reviewed', False),
                         runtime_status=code.get('runtime_status', a.get('validation_status', 'see_existing_validation')),
                         notes=m.get('notes', ''), metadata_path=str(metadata_path.relative_to(ROOT))))
    eligible = sum(r['counts_toward_three'] for r in rows)
    legacy_count = sum(r['legacy_record'] for r in rows)
    unreviewed = sum(r['legacy_eligibility_not_reclassified'] for r in rows)
    status = dict(problem_id=spec['problem_id'], problem_dir=folder.name, name=spec['name'],
                  checked_at=now(), target_algorithms=3, entries=len(rows),
                  local_gpu_code_entries=sum(r['local_gpu_code'] for r in rows),
                  local_paper_entries=sum(r['local_paper'] for r in rows),
                  local_gpu_code_and_paper_including_related=sum(r['local_gpu_code'] and r['local_paper'] for r in rows),
                  eligible_code_and_paper_references=sum(r['has_upstream_code_and_verified_paper_reference'] for r in rows),
                  eligible_local_code_and_paper_pairs=eligible, target_met=eligible >= 3,
                  shortfall=max(0, 3 - eligible),
                  shortfall_explanation=None if eligible >= 3 else coverage.get('shortfall',
                      'Fewer than three eligible local GPU code-and-paper pairs. See individual artifact records.'),
                  limitation_notes=coverage.get('notes'),
                  build_status='not_tested' if not legacy_count else 'see_existing_validation',
                  runtime_status='not_tested' if not legacy_count else 'see_existing_validation',
                  canonical_adapters=0 if not legacy_count else None,
                  legacy_records_not_reclassified=unreviewed, legacy_records_reviewed=legacy_count - unreviewed,
                  research_coverage=coverage, algorithms=rows)
    # Collection review is separate from the existing runtime validation ledger.
    write_json(folder / 'collection_status.json', status)
    write_json(folder / 'gpu_papers.json', dict(problem_id=spec['problem_id'], checked_at=status['checked_at'],
                                               papers=[dict(paper_id=r['paper_id'], algorithm_name=r['algorithm_name'],
                                                            metadata=r['metadata_path'], counts_toward_three=r['counts_toward_three'],
                                                            collected_code=r['local_gpu_code'], collected_pdf=r['local_paper'])
                                                       for r in rows]))
    readme = folder / 'README.md'
    if int(folder.name[:2]) >= 38:
        lines = [spec['name'], '=' * len(spec['name']), '', spec['problem_statement'], '',
                 '[Input/output contract](problem.json) · [Artifact inventory](collection_status.json) · '
                 '[Full sweep](../_collection/README.md)', '',
                 f"Collected {len(rows)} records; {eligible} eligible local GPU implementation/research-paper pairs (target: 3).", '',
                 '| Algorithm / record | Paper | GPU source | Eligible pair |', '|---|---|---|---|']
        for row in rows:
            lines.append(f"| [{row['paper_id']}](papers/{row['paper_id']}/README.md) | "
                         f"{'local' if row['local_paper'] else 'missing'} | {'local' if row['local_gpu_code'] else 'missing'} | "
                         f"{'yes' if row['counts_toward_three'] else 'no'} |")
        lines += ['', status['shortfall_explanation'] or 'The collection target is met for the documented variants.', '',
                  'Framework papers and distinct implementation variants may share a publication. '
                  'These are collection counts, not validation of builds, GPU correctness or runtime backends. '
                  'See each record for input restrictions, hybrid CPU/GPU stages and missing adapters.', '']
        readme.write_text('\n'.join(lines))
    return status


def refresh(config):
    results = [summarize_problem(folder, config['coverage'].get(folder.name, {}))
               for folder in sorted(ROOT.glob('[0-9][0-9]_*')) if (folder / 'problem.json').is_file()]
    all_totals = dict(problems=len(results), algorithm_records=sum(r['entries'] for r in results),
                      local_gpu_source_entries=sum(r['local_gpu_code_entries'] for r in results),
                      local_main_papers=sum(r['local_paper_entries'] for r in results),
                      eligible_local_pairs=sum(r['eligible_local_code_and_paper_pairs'] for r in results),
                      problems_meeting_three_local_pairs=sum(r['target_met'] for r in results),
                      upstream_source_snapshots=len(list(SOURCES.glob('*.json'))))
    inventory = dict(checked_at=now(), scope='All problem statements and artifact metadata; no new executable backends.',
                      search_exhaustive=False, count_definition='Eligible reviewed local GPU implementation plus local research paper; '
                      'framework papers and distinct implementation variants count. Existing records have an explicit collection review; runtime validation is separate.',
                      totals=all_totals, libraries=config['libraries'], problems=results)
    write_json(HERE / 'research_inventory_2026_10_09.json', inventory)
    expansion = [r for r in results if int(r['problem_dir'][:2]) >= 38]
    totals = dict(problems=len(expansion), algorithm_records=sum(r['entries'] for r in expansion),
                  problems_meeting_three_local_pairs=sum(r['target_met'] for r in expansion),
                  eligible_local_pairs=sum(r['eligible_local_code_and_paper_pairs'] for r in expansion),
                  local_gpu_source_entries=sum(r['local_gpu_code_entries'] for r in expansion),
                  local_main_papers=sum(r['local_paper_entries'] for r in expansion),
                  upstream_source_snapshots=all_totals['upstream_source_snapshots'])
    write_json(HERE / 'expansion_2026_10_09.json', dict(checked_at=now(), scope='Problem folders 38 onward.',
               policy='Upstream source only; missing artifacts and semantic mismatches remain explicit.',
               count_definition=inventory['count_definition'], totals=totals, problems=expansion))
    baseline = json.loads((HERE / 'sweep_baseline_2026_10_09.json').read_text())
    old_entries = sum(len(p['paper_ids']) for p in baseline['problems'])
    changes = dict(checked_at=now(), before=dict(problems=len(baseline['problems']), algorithm_records=old_entries,
                                                expansion=baseline['previous_expansion']),
                   after=all_totals, added_problems=len(results) - len(baseline['problems']),
                   added_algorithm_records=all_totals['algorithm_records'] - old_entries,
                   additions_config=CONFIG.name, runtime_validation_performed=False)
    write_json(HERE / 'sweep_result_2026_10_09.json', changes)
    lines = ['GPU graph research collection — internet and library sweep', '=' * 61, '',
             f"Current inventory: {all_totals['problems']} problems and {all_totals['algorithm_records']} research/implementation records. "
             f"This sweep added {changes['added_problems']} problems and {changes['added_algorithm_records']} records.", '',
             'This is a research collection. A local source snapshot or paper does not establish buildability, correctness, '
             'performance, or library/agent integration. Existing validated backends retain their separate evidence.', '',
             'The target is three eligible local GPU implementations with research papers. Distinct implementations may share '
             'a framework paper; this is not a count of independent publications. Documentation-only code is retained but does '
             'not satisfy the paper target. Building blocks and mismatched objectives do not count. Legacy records are '
             'reconciled against actual files and reviewed implementation paths; this does not replace their runtime validation history.', '',
             '| Problem | Records | Local code | Local PDFs | Reviewed pairs / 3 | Legacy records |',
             '|---|---:|---:|---:|---:|---:|']
    for r in results:
        lines.append(f"| [{r['problem_dir']}](../{r['problem_dir']}/problem.json) | {r['entries']} | "
                     f"{r['local_gpu_code_entries']} | {r['local_paper_entries']} | "
                     f"{r['eligible_local_code_and_paper_pairs']}/3 | {r['legacy_records_reviewed']} |")
    lines += ['', 'Libraries and upstream projects with new records', '------------------------------------------------', '',
              '| Source project | Newly added records | Pinned revision |', '|---|---:|---|']
    library_counts = Counter(e['source'] for e in config['entries'] if e.get('source'))
    for library in config['libraries']:
        if library['key'] in library_counts:
            revision = library.get('commit') or 'individual source files'
            lines.append(f"| [{library['key']}]({library['source_url']}) | {library_counts[library['key']]} | `{revision[:12]}` |")
    lines += ['', 'Search coverage and limitations', '-------------------------------', '',
              'The sweep combined official library APIs, pinned implementation files, author repositories, publication pages, '
              'and targeted searches for missing problems. It does not claim exhaustive coverage of the entire internet.', '',
              '[Library coverage and research decisions](sweep_additions_2026_10_09.json) · '
              '[Repository searches](repository_search_2026_10_09.json) · '
              '[Full inventory](research_inventory_2026_10_09.json) · '
              '[Change totals](sweep_result_2026_10_09.json)', '',
              'Incomplete targets', '------------------', '']
    for r in results:
        if not r['target_met']:
            lines.append('- **' + r['problem_dir'] + '**: ' + r['shortfall_explanation'])
    lines += ['', 'Verification', '------------', '',
              'Run `python3 problems/_collection/validate.py` for the expansion and '
              '`python3 problems/_collection/validate_sweep.py` for all problems, source hashes, publication references, '
              'new schemas, and generated inventory consistency.', '',
              'No third-party code is compiled or executed by either collection validator. '
              'See [collection checks](validation_sweep_2026_10_09.json) and '
              '[catalog regression checks](catalog_checks_2026_10_09.json) for the actual scope and results.', '']
    (HERE / 'README.md').write_text('\n'.join(lines))
    manifest = []
    for item in results:
        for row in item['algorithms']:
            path = ROOT / row['metadata_path']
            metadata = json.loads(path.read_text())
            artifacts = json.loads(path.with_name('artifact_status.json').read_text())
            manifest.append(dict(problem_id=item['problem_id'], problem_dir=item['problem_dir'],
                                 paper_id=row['paper_id'], metadata=row['metadata_path'],
                                 title=metadata['title'], publication_url=metadata.get('publication_url'),
                                 pdf_url=metadata.get('pdf_url'), code_url=metadata.get('code_url'),
                                 paper_sha256=artifacts.get('paper', {}).get('sha256'),
                                 code_commit=artifacts.get('code', {}).get('commit'),
                                 counts_toward_three=row['counts_toward_three']))
    write_json(HERE / 'paper_manifest_2026_10_09.json', dict(checked_at=now(), papers=manifest))
    registry_path = ROOT.parent / 'catalog/artifact_sources.json'
    registry = json.loads(registry_path.read_text())
    indexed = {(r['problem_id'], r['paper_id']): r for r in registry['artifacts']}
    for record in manifest:
        key = (record['problem_id'], record['paper_id'])
        path = ROOT / record['metadata']
        metadata = json.loads(path.read_text())
        code = json.loads(path.with_name('artifact_status.json').read_text())['code']
        if key not in indexed:
            indexed[key] = dict(problem_id=record['problem_id'], paper_id=record['paper_id'],
                                year=metadata.get('year'), venue=metadata.get('venue'),
                                publication_url=metadata.get('publication_url'), code_url=metadata.get('code_url'),
                                code_commit=code.get('commit'), license_file=code.get('license_file'),
                                license_note=code.get('license_note'), research_collection_only=True)
        # Existing runtime provenance may refer to a separately patched/pinned
        # artifact. Preserve that commit; link the current research record.
        indexed[key]['title'] = metadata['title']
        indexed[key]['collection_metadata'] = 'problems/' + record['metadata']
        indexed[key]['collection_code_commit'] = code.get('commit')
    registry['artifacts'] = sorted(indexed.values(), key=lambda r: (r['problem_id'], r['paper_id']))
    registry['research_inventory'] = 'problems/_collection/research_inventory_2026_10_09.json'
    write_json(registry_path, registry)
    (ROOT / 'README.md').write_text(
        'Graph mining problem and algorithm collection\n=============================================\n\n'
        f"{all_totals['problems']} problem statements and {all_totals['algorithm_records']} research/implementation records.\n\n"
        '[Browse all problems and collection gaps](_collection/README.md) · '
        '[Machine-readable inventory](_collection/research_inventory_2026_10_09.json) · '
        '[Paper manifest](_collection/paper_manifest_2026_10_09.json)\n\n'
        'Source/paper collection and executable GPU validation are separate. See the repository validation/ tree '
        'and graphmine_manifest.json for the actually supported runtime profiles.\n')
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--refresh-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    if not args.refresh_only:
        for entry in config['entries']:
            eligible = add_entry(entry, config['publications'], args.download)
            print(entry['problem_dir'], entry['paper_id'], 'pair' if eligible else 'documented', flush=True)
    print(json.dumps(refresh(config), indent=2))
