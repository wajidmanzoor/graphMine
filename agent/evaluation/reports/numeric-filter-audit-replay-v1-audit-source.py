"""Diagnose saved filter-representation failures without replacing any grade."""

import argparse
import json
from pathlib import Path

from graphmine_agent.history import HistoryStore
from graphmine_agent.models import utc_now
from graphmine_agent.learning import business_workflows
from graphmine_agent.learning.adapter_eval import read_suite
from graphmine_agent.learning.adapter_workflow_review import complete_rows, stage_evidence


def audit(root, suite, arm, output):
    if output.exists():
        raise ValueError('Preserve previous audit reports')
    root, suite = root.resolve(), suite.resolve()
    plan, _, _ = read_suite(suite)
    status = json.loads((root / 'status.json').read_text())
    protocol = json.loads((root / 'protocol.json').read_text())
    report_path = root / f'{arm}.json'
    report = json.loads(report_path.read_text())
    if (status['phase'] != 'completed' or status['completed_arms'] != protocol['arms']
            or arm not in protocol['arms']):
        raise ValueError('Require the complete recorded application run')
    if (protocol['suite_plan_sha256'] != HistoryStore.digest(suite / 'plan.json')
            or protocol['adapter_sha256'] != plan['adapter_sha256']):
        raise ValueError('The suite and application candidate binding differ')
    rows = complete_rows(report)
    cases = {case['id']: case for case in report['cases']}
    findings = []
    for identity, row in rows.items():
        if row['passed']:
            continue
        step = cases[identity[0]]['steps'][identity[2] - 1]
        task = step.get('task', step)
        expected = task.get('filters', [])
        intent = ((row['observed'].get('job') or {}).get('plan') or {}).get('application_intent')
        actual = intent.get('filters', []) if isinstance(intent, dict) else None
        flagged = 'Requested attribute scope changed' in row['issues']
        equivalent = (flagged and actual is not None
                      and business_workflows.normalized_filters(expected)
                      == business_workflows.normalized_filters(actual))
        findings.append({
            'identity': list(identity), 'query': row['query'],
            'original_issues': row['issues'], 'expected_filters': expected,
            'actual_filters': actual, 'scope_issue_reported': flagged,
            'numeric_filters_equivalent': equivalent,
            'no_other_reported_issues': row['issues'] == ['Requested attribute scope changed'],
            'stages': stage_evidence(root, arm, row),
        })
    paths = [report_path, root / 'status.json', root / 'protocol.json',
             suite / 'plan.json', Path(__file__), Path(business_workflows.__file__)]
    result = {
        'created_at': utc_now().isoformat(),
        'source_report': str(report_path), 'arm': arm,
        'original_score': {'passed': report['passed'], 'total': report['total']},
        'complete_source_coverage_verified': len(rows), 'findings': findings,
        'original_grades_changed': False, 'replacement_aggregate_created': False,
        'model_calls': 0, 'source_evaluation_was_final_holdout': protocol['final_holdout'],
        'deployment_changed': False,
        'interpretation': 'Diagnosis only. Uses the existing tested numeric-filter rule: equal numeric values retain field/operator distinctions and remain distinct from strings and booleans. Other reported issues remain visible. No replacement pass total or new model call is created. Stage participation does not establish failure causality.',
        'evidence_sha256': {str(path.resolve()): HistoryStore.digest(path) for path in paths},
    }
    snapshot = output.with_name(output.stem + '-audit-source.py')
    if snapshot.exists():
        raise ValueError('Preserve earlier audit source snapshots')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(Path(__file__).read_bytes())
    result['audit_source_snapshot'] = str(snapshot.resolve())
    HistoryStore.write(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--arm', choices=['base_nf4', 'adapter_nf4', 'serving_fp8'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.results, args.suite, args.arm, args.output)
    print(json.dumps({'original_score': result['original_score'],
                      'failed_turns': len(result['findings']),
                      'numeric_equivalence_findings': [row['identity'] for row in result['findings']
                                                      if row['numeric_filters_equivalent']],
                      'original_grades_changed': False, 'model_calls': 0}))


if __name__ == '__main__':
    main()
