#!/usr/bin/env python3
"""Collect option decisions on the frozen Phase 1 labels, then calibrate High.

The fit is a development-set precision measurement, never a held-out accuracy
claim. No labels or expected problems are included in model requests.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile

from evaluate_lane_baseline import ROOT, SUITE, digest, evaluate, load_suite, source_files, write_json
from graphmine_agent.analytics_options import SCORE_VERSION, SAMPLES, TEMPERATURE, catalog_signature
from graphmine_agent.config import Settings


def fit(report, suite):
    expected = {case['id']: case['expected'].get('problems', []) for case in suite['cases']}
    references = {case['id']: case.get('reference', {}) for case in suite['cases']}
    rows = []
    for case in report['cases']:
        for option in case['response'].get('options', []):
            evidence = option['match_evidence']
            rows.append({'case': case['id'], 'option': option['id'], 'score': option['score'],
                         'eligible_for_high': evidence['votes'] > 0 and len(evidence['problem_logprobs']) == evidence['votes'] and not evidence['missing_parameters'],
                         'correct': sorted(option['problems']) in [sorted(ops) for ops in expected[case['id']]] and
                                    all(option['parameters'].get(name) == value for name, value in references[case['id']].get('parameters', {}).items())})
    thresholds = sorted({row['score'] for row in rows if row['eligible_for_high']})
    high = {'threshold': 1.01, 'count': 0, 'correct': 0, 'precision': 0}
    for threshold in thresholds:
        selected = [row for row in rows if row['eligible_for_high'] and row['score'] >= threshold]
        correct = sum(row['correct'] for row in selected)
        if len(selected) >= 5 and correct / len(selected) >= .85:
            high = {'threshold': threshold, 'count': len(selected), 'correct': correct, 'precision': correct / len(selected)}
            break
    return {'score_version': SCORE_VERSION, 'samples': SAMPLES, 'temperature': TEMPERATURE,
            'model': report['model'], 'server': report['server'], 'catalog_sha256': report['catalog_sha256'],
            'suite_sha256': digest(suite), 'source_report_sha256': digest(report),
            'scope': 'Frozen Phase 1 development labels; calibration-set precision, not held-out accuracy.',
            'high': high, 'rows': rows}


async def collect(settings, suite, graphs, report, output):
    from graphmine_agent.analytics import AnalyticsService
    from graphmine_agent.database import Database
    from graphmine_agent.graph_store import GraphStore
    from graphmine_agent.jobs import EventBus
    database = Database(settings.database_path)
    service = AnalyticsService(settings, database, GraphStore(settings, database), EventBus(database))
    try:
        caps = await service.capabilities()
        report['catalog_sha256'] = catalog_signature([card for card in caps['problems'] if card['execution']['cpu']])
    finally:
        await service.close()
    await evaluate(settings, suite, graphs, report, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', type=Path)
    parser.add_argument('--fit', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', help='One diagnostic case; not sufficient for calibration')
    args = parser.parse_args()
    suite, graphs = load_suite(SUITE)
    if args.fit:
        if not args.output:
            parser.error('--fit requires --output')
        result = fit(json.loads(args.fit.read_text()), suite)
        write_json(args.output, result)
        print(json.dumps(result['high']))
        return
    if not args.collect or args.collect.exists():
        parser.error('Provide a new --collect path')
    settings = Settings.from_env(ROOT)
    subset = {**suite, 'cases': [case for case in suite['cases'] if case['expected']['lane'] == 'options' and (not args.case or case['id'] == args.case)]}
    if not subset['cases']:
        parser.error('No matching option cases')
    before = source_files(SUITE)
    report = {'phase': 4, 'scope': 'Phase 1 option cases; five independent samples per proposal.',
              'created_at': datetime.now(UTC).isoformat(), 'model': settings.analytics_router_model or settings.llm_model,
              'server': settings.analytics_router_base_url or settings.llm_base_url, 'cases': [], 'source_files': before}
    with tempfile.TemporaryDirectory(prefix='graphmine-option-calibration-') as directory:
        settings = replace(settings, data_root=Path(directory), history_directory=None, backup_directory=None,
                           capture_enabled=False, accounts_enabled=False, llm_enabled=True, analytics_gpu_uuids=())
        asyncio.run(collect(settings, subset, graphs, report, args.collect))
    report['sources_unchanged_during_run'] = before == source_files(SUITE)
    write_json(args.collect, report)
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
