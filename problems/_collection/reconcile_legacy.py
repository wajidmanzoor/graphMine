#!/usr/bin/env python3
"""Repair artifact inventory drift without altering existing implementation code.

Only reviewed source-to-paper mappings below are restored. Missing licenses
block new source redistribution. Existing implementation modifications and
separate runtime-validation evidence are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from acquire import ROOT, SOURCES, now, paper, sha256, write_json

RECOVER = {
    '2020_accelerating_truss_heterogeneous': ('acc_truss', ['opt-truss-decomp-offload/pkt_cuda_experimental.cu']),
    '2025_ecl_maxflow': ('ecl_maxflow', ['src/maxflow.cu']),
    '2022_g2miner_reuse': ('graphminer', ['src/sgl/gpu_base.cu', 'src/sgl/gpu_kernels/rectangle_nested.cuh']),
    '2021_gpusteiner_kmb': ('gpu_steiner', ['gpuSteiner6-oddAgainWithKtimer2Sh3.cu']),
    '2020_curipples': ('curipples', ['tools/cuda/cuda_hc_engine.cu']),
    '2021_gim': ('gim', ['IM.cu', 'kernels.cu']),
    '2019_hungariangpu': ('hungarian_gpu', ['HungarianCUDA.cu']),
    '2021_graphbplus': ('graphbplus', ['graphBplus_02.cu']),
    '2026_ecl_sgb': ('ecl_sgb', ['src/ECL-SGB.cu']),
    '2024_gdlog': ('gdlog', ['test/tc.cu', 'src/join.cu']),
    '2023_eclscc': ('ecl_scc', ['source/ECL-SCC_10.cu']),
    '2017_gpugraphlayout': ('gpu_layout', ['src/RPGPUForceAtlas2.cu', 'src/RPFA2Kernels.cu']),
}
EXISTING = {
    '2023_parallelizing_mce': ['src/main.cu'],
    '2024_g2_aimd': ['app_BK/main.cu'],
    '2026_rdmce': ['RDMCE/src/mce_gpu.cu'],
    '2019_maximum_clique_cuda': ['motzkin_cuda.cu'],
    '2023_maximum_clique_enumeration_gpu': ['cliqueMerging.cu', 'GPUTestMaxClique.cu'],
    '2024_maximum_clique_many_core_gpu': ['src/main.cu'],
    '2022_parallel_k_clique_counting': ['src/main.cu'],
    '2023_graphset': ['gpu/gpu_clique.cu'],
    '2024_gamma': ['kcl.cu'],
    '2025_cuqc': ['main.cu'],
    '2023_accelerating_k_core_gpu': ['main.cu'],
    '2024_cumbe': ['src/main.cu'],
    '2025_tot_tensor_cores': ['apps/tot.cu'],
    '2025_wetric': ['tc.cu'],
    '2026_edtc': ['tricount.cu'],
    '2022_g2miner': ['src/sgl/gpu_base.cu'],
    '2024_dumato': ['src/main/motifs_DM_WC.cu'],
    '2026_gmatch': ['bitmap/main.cu', 'bitmap/join_bfs_dfs.cu'],
    '2024_everest': ['plugins/GPUWorkerU3B.cu'],
    '2025_mayura': ['GPU-co-mining/workdesk/allOpt_MG34cyc.cu'],
    '2026_gleiden': ['leiden.cu'],
    '2026_multilevel_graph_clustering': ['src/clustering_methods.cpp', 'src/leidenR.cpp', 'README.md'],
    '2021_turbobc': ['TurboBC/bcgpugcooc_sc.cu'],
    '2020_kpar': ['src/main.cu'],
    '2022_gamma_reuse': ['sm.cu'],
    '2025_gpu4gst': ['code/TrimCDP-WB/src/GSTnonHop.cu'],
    '2021_superfuser': ['src/gpu.cu'],
    '2026_fast_ged': ['gpu/gpu_evaluation.cu'],
}
PAPERS = {
    '2026_ecl_sgb': 'https://userweb.cs.txstate.edu/~mb92/papers/gpgpu26.pdf',
    '2026_gleiden': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12987761/pdf/vbaf327.pdf',
}
TITLES = {
    '2024_g2_aimd': 'G2-AIMD: A Memory-Efficient Subgraph-Centric Framework for Efficient Subgraph Finding on GPUs',
    '2023_graphset': 'GraphSet: High Performance Graph Mining through Equivalent Set Transformations',
    '2022_g2miner': 'Efficient and Scalable Graph Pattern Mining on GPUs',
    '2022_g2miner_reuse': 'Efficient and Scalable Graph Pattern Mining on GPUs',
}
RESTRICTIONS = {
    '2021_gpusteiner_kmb': ('restricted_domain', 'Ordinary terminal Steiner tree covers the singleton-group special case, not unrestricted group Steiner tree.'),
    '2022_gpu_vlsi_gst': ('restricted_domain', 'VLSI routing constraints restrict the problem domain; unrestricted group-Steiner semantics have not been established.'),
    '2025_generalized_maxflow_gpu': ('related_variant', 'Generalized flow with gains is a different objective from ordinary conserved maximum flow.'),
    '2024_hyperg': ('related_variant', 'Hypergraph partitioning needs an explicit reduction and objective/balance check before it can implement ordinary graph partitioning.'),
    '2026_fast_ged': ('variant', 'The public FAS-GED artifact is approximate and bounded; no exact GED or optimality guarantee is inferred.'),
    '2021_graphbplus': ('related_variant', 'Recorded runtime screening identifies edge/tree sampling statistics, not the required minimum-frustration partition and certificate.'),
    '2026_ecl_sgb': ('related_variant', 'Recorded runtime screening identifies edge/tree sampling statistics, not the required minimum-frustration partition and certificate.'),
}


def main(download=False):
    baseline = json.loads((ROOT / '_collection/sweep_baseline_2026_10_09.json').read_text())
    review_path = ROOT / '_collection/legacy_review_2026_10_09.json'
    prior_review = json.loads(review_path.read_text())['entries'] if review_path.exists() else []
    original_states = {(r['problem_dir'], r['paper_id']): r['before'] for r in prior_review}
    changes = []
    for problem in baseline['problems']:
        if int(problem['problem_dir'][:2]) > 37:
            continue
        folder = ROOT / problem['problem_dir']
        spec = json.loads((folder / 'problem.json').read_text())
        for id_ in problem['paper_ids']:
            d = folder / 'papers' / id_
            m = json.loads((d / 'metadata.json').read_text())
            artifact_path = d / 'artifact_status.json'
            a = json.loads(artifact_path.read_text()) if artifact_path.exists() else {}
            old = original_states.get((problem['problem_dir'], id_),
                                      dict(paper=a.get('paper', {}).get('status'), code=a.get('code', {}).get('status')))
            a.update(problem_id=spec['problem_id'], paper_id=id_, checked_at=now())
            if id_ in TITLES:
                m['title'] = TITLES[id_]
            a['title'] = m['title']
            if id_ in RESTRICTIONS:
                m['semantic_fit'], note = RESTRICTIONS[id_]
                m['collection_variant_note'] = note
            paths = EXISTING.get(id_, [])
            source_manifest = None
            if id_ in RECOVER:
                key, paths = RECOVER[id_]
                source_manifest = json.loads((SOURCES / (key + '.json')).read_text())
                if not (d / 'code').exists():
                    (d / 'code').symlink_to(os.path.relpath(SOURCES / source_manifest['local_path'], d), target_is_directory=True)
            # This licensed GitLab artifact already exists in the user's older
            # local collection. Recover it without a network clone or .git data.
            if id_ == '2026_fast_ged' and not (d / 'code').exists():
                original = ROOT.parent.parent / 'problems' / problem['problem_dir'] / 'papers' / id_ / 'code'
                if (original / 'LICENSE.MIT').is_file():
                    shutil.copytree(original, d / 'code', ignore=shutil.ignore_patterns('.git', '__pycache__'))
                    a.setdefault('code', {})['local_recovery_source'] = str(original)
                    a['code']['acquisition_kind'] = 'recovered_existing_licensed_workspace_copy'
            code = a.setdefault('code', {})
            code.update(source_url=m.get('code_url'), checked_at=now())
            c = d / 'code'
            if c.is_dir():
                for p in paths:
                    if not (c / p).is_file():
                        raise ValueError('Reviewed entrypoint missing: ' + str(c / p))
                code.update(status='downloaded_archive' if source_manifest else 'present', local_path='code', error=None,
                            entrypoint_sha256={p: sha256(c / p) for p in paths})
                if source_manifest:
                    code.update(commit=source_manifest.get('commit'), source_manifest='../../../_sources/' + key + '.json',
                                build_status='not_tested', runtime_status='not_tested')
                elif (c / '.git').exists():
                    result = subprocess.run(['git', '-C', str(c), 'rev-parse', 'HEAD'], capture_output=True, text=True)
                    if result.returncode == 0:
                        code['commit'] = result.stdout.strip()
                licenses = [p.name for p in c.iterdir() if p.is_file() and p.name.lower().startswith(('license', 'copying', 'licence'))]
                code['license_file'] = 'code/' + licenses[0] if licenses else None
                m['redistribution_status'] = 'upstream_license_present' if licenses else 'blocked_no_detected_license'
            else:
                code.update(status='not_collected', local_path=None,
                            error='No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage.')
                older = ROOT.parent.parent / 'problems' / problem['problem_dir'] / 'papers' / id_ / 'code'
                if older.is_dir():
                    code['existing_workspace_source_reference'] = str(older)
                    code['error'] = 'An older workspace copy exists, but no detected redistribution license was verified; no new source copy was made.'
                m['redistribution_status'] = 'not_reviewed_or_no_local_source'
            url = PAPERS.get(id_, m.get('pdf_url'))
            if (d / 'paper.pdf').is_file() or (download and url and not str(url).endswith('/')):
                try:
                    a['paper'] = paper(url or m.get('publication_url'), d / 'paper.pdf')
                    if url:
                        m['pdf_url'] = url
                except Exception as e:
                    a['paper'] = dict(status='download_failed', source_url=url, local_path=None, error=str(e), checked_at=now())
            elif a.get('paper', {}).get('status') != 'download_failed':
                a['paper'] = dict(status='not_collected', source_url=url, local_path=None,
                                  error='No local verified PDF; an open downloadable paper URL was not established during this sweep.', checked_at=now())
            reference_pair = bool(c.is_dir() and paths and m.get('publication_url') and
                                  m.get('semantic_fit') not in ['building_block', 'restricted_domain', 'related_variant', 'mismatch'])
            qualifies = reference_pair and a['paper']['status'] == 'downloaded'
            m.update(collection_reviewed=True, collection_review_date='2026-10-09',
                     code_entrypoints=paths if c.is_dir() else [],
                     counts_toward_three=qualifies, has_upstream_code_and_verified_paper_reference=reference_pair)
            m.setdefault('paper_role', 'framework' if m.get('semantic_fit') == 'general_framework' else 'algorithm')
            if id_ == '2019_hungariangpu':
                m.update(doi='10.1016/j.jpdc.2019.03.014', publication_url='https://doi.org/10.1016/j.jpdc.2019.03.014')
            write_json(d / 'metadata.json', m)
            write_json(artifact_path, a)
            semantic_line = (f"Semantic fit: {m.get('semantic_fit', 'not established')}. " + m.get('collection_variant_note', '')).rstrip()
            (d / 'ARTIFACT_STATUS.md').write_text(
                f"{m['title']}\n{'=' * len(m['title'])}\n\n"
                f"Paper: {a['paper']['status']}. Source: {code['status']}.\n\n"
                f"Reviewed local GPU source/research-paper pair: {str(qualifies).lower()}.\n\n"
                f"{semantic_line}\n\n"
                f"Redistribution: {m['redistribution_status']}.\n\n"
                'This sweep checks collection evidence only. Existing runtime validation remains in the validation/ tree; '
                'no new GPU build or correctness claim is made here.\n')
            changes.append(dict(problem_dir=problem['problem_dir'], paper_id=id_, before=old,
                                paper=a['paper']['status'], code=code['status'],
                                eligible_local_pair=qualifies, semantic_fit=m.get('semantic_fit')))
    write_json(ROOT / '_collection/legacy_review_2026_10_09.json', dict(checked_at=now(), entries=changes))
    print('Reviewed', len(changes), 'legacy records;', sum(x['eligible_local_pair'] for x in changes), 'eligible local pairs.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    main(parser.parse_args().download)
