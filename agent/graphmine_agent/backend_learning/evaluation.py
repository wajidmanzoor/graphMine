"""Whole-graph held-out comparisons; unobserved shadow outcomes stay unknown."""
from __future__ import annotations

from collections import defaultdict
import numpy as np

from . import shared
from .policy import distribution, size_allows_exploration


def weighted_quantile(values, weights, q):
    order = np.argsort(values)
    ordered, mass = np.asarray(values)[order], np.asarray(weights)[order]
    return float(ordered[min(len(ordered) - 1, np.searchsorted(np.cumsum(mass), q * mass.sum()))])


def summarize(selections):
    if not selections:
        return None
    weights = [r['weight'] for r in selections]
    ratios, times = ([r[key] for r in selections] for key in ('ratio', 'seconds'))
    return dict(mean=float(np.average(ratios, weights=weights)),
        median=weighted_quantile(ratios, weights, .5), p90=weighted_quantile(ratios, weights, .9),
        p99=weighted_quantile(ratios, weights, .99),
        tail_seconds_p90=weighted_quantile(times, weights, .9), tail_seconds_p99=weighted_quantile(times, weights, .99),
        failure_rate=float(np.average([r['outcome'] != 'completed' for r in selections], weights=weights)),
        timeout_rate=float(np.average([r['outcome'] == 'timeout' for r in selections], weights=weights)))


def evaluate(cases, model=None, *, reference=None, temperature=1., floor=.02, exploration_enabled=True):
    observations, by_problem, by_k = [], defaultdict(list), defaultdict(list)
    for case in cases:
        eligible = case['eligible_backends']
        if reference == 'oracle':
            best = min(eligible, key=lambda b: case['seconds'][b])
            probabilities = {b: float(b == best) for b in eligible}
        elif reference == 'native':
            probabilities = {b: float(b == case['native_backend']) for b in eligible}
        else:
            scores = shared.preferences(model, case['context'], eligible)
            best = max(eligible, key=lambda b: scores[b])
            probabilities = distribution(scores, temperature, floor) if exploration_enabled and size_allows_exploration(model, case['context']) else {b: float(b == best) for b in eligible}
        for backend in eligible:
            for index, (seconds, outcome) in enumerate(zip(case['timings'][backend], case['outcomes'][backend])):
                observed = case.get('observed_seconds', case['timings'])[backend][index]
                value = dict(ratio=seconds / case['oracle_seconds'], seconds=observed if shared.finite(observed) and observed >= 0 else seconds, outcome=outcome,
                             weight=probabilities[backend] / len(case['timings'][backend]))
                if value['weight']:
                    observations.append(value)
                    by_problem[case['context']['problem']].append(value)
                    by_k[str(len(eligible))].append(value)
    return dict(metrics=summarize(observations), cases=len(cases),
                by_problem={k: summarize(v) for k, v in by_problem.items()},
                by_k={k: summarize(v) for k, v in by_k.items()})


def better(candidate, reference):
    return bool(candidate and reference and candidate['mean'] < reference['mean'] and
                candidate['failure_rate'] <= reference['failure_rate'] and
                candidate['timeout_rate'] <= reference['timeout_rate'])


def shadow_report(rows, model):
    accepted = [r for r in rows if r.get('source') == 'application' and r.get('is_evaluation') is False
                and r.get('selection_mode') == 'shadow' and r.get('shadow_choice')
                and r.get('model_version') == model.get('model_version')
                and r.get('implementation_sha256') == model['implementation_sha256']]
    # A production choice is not a paired timing. Reporting native runtime as
    # the shadow backend's runtime would make the rollout gate meaningless.
    return dict(rows=len(accepted), agreement_count=sum(r['shadow_choice'] == r.get('chosen_backend') for r in accepted),
        distinct_graphs=len({r['graph_features']['snapshot_fingerprint'] for r in accepted}),
        metrics=None, live_ready=False,
        reason='Paired real-traffic measurements are required to measure counterfactual runtime, failure and timeout rates.')


def compare(models, held_out, *, options=None):
    options = options or {}
    allowed = {k: v for k, v in options.items() if k in {'temperature', 'floor', 'exploration_enabled'}}
    reports = {name: evaluate(held_out, model, **allowed) for name, model in models.items()}
    reports['native'] = evaluate(held_out, reference='native')
    reports['oracle'] = evaluate(held_out, reference='oracle')
    baseline = reports['native']['metrics']
    for value in reports.values():
        metric = value['metrics']
        value['native_to_oracle_gap_closed'] = (baseline['mean'] - metric['mean']) / (baseline['mean'] - 1) if baseline and baseline['mean'] > 1 + 1e-12 else None
    return dict(policies=reports, whole_graph_holdout=True,
        graph_count=len({c['context']['graph_features']['snapshot_fingerprint'] for c in held_out}),
        probability_integration='Exact masked distribution within measured sizes; deterministic greedy outside. Daily budget exhaustion can only remove exploration; no synthetic traffic ledger is assumed.',
        failure_cost='Configured multiple of the slowest completed paired runtime; all measured timings retained.',
        removed_policy='Per-problem regressions were removed at the user request; no current-policy comparison is fabricated.',
        live_ready=False, recommendation='keep_native_until_paired_shadow_evidence')
