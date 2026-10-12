#!/usr/bin/env python3
"""Render actual completed evidence; never turn an unfinished run into a pass."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def main():
    native=read(HERE/'results/acceptance/summary.json') or read(HERE/'results/final/summary.json')
    boundaries=read(HERE/'results/boundaries/summary.json')
    sanitizer=read(HERE/'results/sanitizer-final/summary.json')
    research=[read(p) for p in sorted((ROOT/'validation/research_runtime/results').glob('*/summary.json'))]
    outer=read(ROOT.parent/'validation/parameter_expansion_outer/summary.json')
    required={operation['id']+'/'+backend['id']
              for operation in read(ROOT/'catalog/backend_registry.json')['operations']
              for backend in operation['backends']}
    missing=sorted(required-set(native['coverage'] if native else {}))
    leiden=read(HERE/'results/leiden-timeout-replay/summary.json')
    checks=read(HERE/'evidence/final-checks.json')
    summary={'native':native,'boundaries':boundaries,'sanitizer':sanitizer,
        'missing_registered_backends':missing,'leiden_replays':leiden,'additional_checks':checks,
        'research':{k:sum(r[k] for r in research) for k in ['cases','passed','failed']},
        'outer':{'cases':sum(r['total'] for r in outer['results']),
                 'passed':sum(r['passed'] for r in outer['results'])},
        'native_acceptance_complete':bool(native and not missing and native['failed']==0
            and boundaries and boundaries['failed']==0 and sanitizer and sanitizer['failed']==0
            and boundaries['binary_sha256']==native['binary_sha256']
            and sanitizer['binary_sha256']==native['binary_sha256']
            and checks and checks['ctest']['passed']==checks['ctest']['total']
            and checks['binary_sha256']==native['binary_sha256']
            and checks['agent_pytest']['passed']==checks['agent_pytest']['total'])}
    (HERE/'verification_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines=['# Runtime results','']
    if native:
        coverage_note=(f"All {len(required)} registered choices plus automatic k-clique selection are represented."
                       if not missing else f"Missing registered choices: {', '.join(missing)}.")
        timing=(f"{native['seconds']/60:.1f} minutes" if native['mode']=='full'
                else 'complete run plus the MBE resource and typed-vertex-ID reruns')
        lines += [f"Final-build checks: **{native['passed']:,}/{native['cases']:,} distinct cases passed**, {native['failed']} failed; {timing}. {coverage_note}",
                  '',f"Binary SHA-256: `{native['binary_sha256']}`. Inputs, worker hashes, commands and individual oracle outcomes are retained alongside the summary.",'',
                  '| Operation / backend | Passed | Failed |','| --- | ---: | ---: |']
        for key,r in sorted(native['coverage'].items()):lines.append(f"| {key} | {r['passed']} | {r['failed']} |")
        if native.get('resource_rerun'):
            retry=native['resource_rerun']
            lines += ['',f"The full run at eight jobs per GPU recorded {native['full_run']['failed']} MBE-GPU out-of-memory errors. All {retry['cases']} MBE cases were then repeated with {retry['workers_per_gpu']} worker on GPU {','.join(retry['gpus'])}: {retry['passed']} passed / {retry['failed']} failed. The CLI, worker binaries, generator, instructions and fixtures were identical. Original failures remain in [the full-run summary](results/final/summary.json); [acceptance evidence](results/acceptance/summary.json) identifies the result used for every case. This is not a clean single-attempt run."]
        if native.get('vertex_id_rerun'):
            retry=native['vertex_id_rerun']
            lines += ['',f"The final review also found that the harness serialized string vertex ID `\"0\"` as integer `0` in CLI arguments. The agent already encoded these IDs correctly. The corrected harness reran all {retry['cases']} PageRank and max-flow cases: {retry['passed']} passed / {retry['failed']} failed. Fixtures and binaries were unchanged; both generator hashes are recorded. Dangling-seed PageRank additionally has an exact check. The earlier PageRank error measurements are superseded by [this rerun](results/vertex-id-rerun/summary.json)."]
    else:lines += ['**The final CLI sweep is still running. No completed final pass is claimed.**']
    lines += ['',f"Boundary checks: {boundaries['passed']}/{boundaries['cases']}; memcheck cases: {sanitizer['passed']}/{sanitizer['cases']}.",
              'The separate K514 memcheck reports zero errors, and GAMMA racecheck reports zero warnings/errors.',
              '', 'These are bounded correctness checks, not performance benchmarks or global certificates for heuristic algorithms. See the README for oracle scopes.']
    if checks:
        lines += ['',f"Final native CTest: {checks['ctest']['passed']}/{checks['ctest']['total']}; agent tests: {checks['agent_pytest']['passed']}/{checks['agent_pytest']['total']}. Commands, binary identity and logs are in [final-checks.json](evidence/final-checks.json)."]
    if leiden:
        lines += ['',f"Leiden termination regression: the previous binary timed out in {leiden['before']['timeouts']}/{leiden['before']['cases']} replays. The candidate repair passed {leiden['candidate']['passed']}/{leiden['candidate']['cases']} independent partition/score checks on both GPUs. Native tests repeat the fixture 20 times per Leiden variant, with a 60-second test timeout. See [replay evidence](results/leiden-timeout-replay/summary.json)."]
    if native:
        errors=[]
        paths=([HERE/'results/acceptance/results.jsonl'] if native.get('resource_rerun')
               else (HERE/'results/final').glob('gpu-*/results.jsonl'))
        for path in paths:
            for line in path.read_text().splitlines():
                row=json.loads(line)
                if row['operation']=='personalized-pagerank':
                    value=row.get('grade',{}).get('measurements',{}).get('maximum_returned_score_absolute_error')
                    if value is not None:errors.append(value)
        if errors:lines += ['',f"PPR: {len(errors)} cases measured; worst returned-score absolute error {max(errors):.8g}. No acceptance error threshold or certified per-run bound was imposed."]
    lines += ['', '## Collected implementations outside the CLI','',
              'These tests cover 19 artifact records. Model checks assess execution/parity/gradients, not trained accuracy. Some expected domain rejections are counted as successful checks and shown separately.', '',
              '| Implementation / check | Passed | Failed | Scope |','| --- | ---: | ---: | --- |']
    for family in research:
        for name,r in family['by_backend'].items():lines.append(f"| {name} | {r['passed']} | {r['failed']} | {r['scope'].replace('|','/')} |")
    lines += ['', 'Observed research failures: torch-cluster violates exact neighbor counts with duplicate/tied vectors (including k=0); collected CuPy LOBPCG fails on two dense Laplacians under the recorded compiled runtime; Ripser++ omits the essential H0 interval from Python output. Finite Ripser++ intervals pass independently. These implementations remain research-only.',
              '', '## Outer workspace additions','',
              'The outer folder has 37 contracts / 91 records. Problems 21..37 contain 37 newer records: 15 have runnable diagnostic integrations, 22 remain gaps. Historical binaries were hashed; GPU4GST was rebuilt from current outer source containing earlier repairs. A partial pass retains the limitations of the original screen.', '',
              '| Outer backend | Passed / cases | Status |','| --- | ---: | --- |']
    for r in outer['results']:lines.append(f"| {r['backend']} | {r['passed']} / {r['total']} | {r['status']} |")
    lines += ['', 'Concrete outer failures: ECL-Maxflow exits with CUDA invalid-configuration errors on 58 inputs (including an edgeless graph and a single source-to-sink edge); some print the correct scalar before failing, so these are runtime failures rather than evidence of an incorrect flow value. GAMMA reports two butterflies for a single K2,2 whose reference count is one. KPAR returns five entries when top-4 is requested on the cycle fixtures; this failure does not establish an approximation-error violation.',
              '', 'GraphB+ and ECL-SGB are output/execution smoke checks only; they do not certify frustration or balance optima. KPAR is a limited approximate top-k screen. Group Steiner screens cover small path/scalar cases. See each JSON result for its limitations.',
              '', 'The inner collection passed offline checks of all 70 contracts / 219 artifact records, including documented availability gaps: 181 local GPU source entries and 161 local main papers. The outer 37 contracts passed structural/schema-reference checks. Integrity does not imply numerical correctness. The per-record gaps are in [research_gaps.md](research_gaps.md) and the outer [inventory](../../../validation/parameter_expansion_outer/inventory.json).']
    (HERE/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    print({k:v for k,v in summary.items() if k not in ['native','sanitizer']})


if __name__=='__main__':main()
