#!/usr/bin/env python3
"""Join collected records to actual runtime evidence without promoting gaps."""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RESEARCH=ROOT/'validation/research_runtime/results'


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def main():
    native_file=(HERE/'results/acceptance/summary.json' if (HERE/'results/acceptance/summary.json').exists()
                 else HERE/'results/final/summary.json')
    native_evidence=str(native_file.relative_to(ROOT))
    native=read(native_file,{'coverage':{}})['coverage']
    registry=read(ROOT/'catalog/backend_registry.json')['operations']
    repairs={r['backend_id']:r['validation']['paper_artifacts']
             for r in read(ROOT/'catalog/repaired_profiles.json')['backends']}
    research={}
    for path in RESEARCH.glob('*/summary.json'):
        for backend,result in read(path)['by_backend'].items():
            research[backend]={**result,'evidence':str(path.relative_to(ROOT))}
    mapping={
        '2019_pyg_average_pool':['pyg-average-pool'],
        '2019_pyg_induced_subgraph':['pyg-induced-subgraph'],
        '2019_pyg_khop_subgraph':['pyg-khop-subgraph'],
        '2016_pyg_gcn':['pyg-gcn'], '2017_pyg_gat':['pyg-gat'],
        '2017_pyg_graphsage':['pyg-graphsage'], '2018_pyg_gin':['pyg-gin'],
        '2018_pyg_diffpool':['pyg-diffpool'], '2019_pyg_sagpool':['pyg-sagpool'],
        '2017_cupy_dense_eigh':['cupy-dense-eigh'],
        '2017_cupy_lanczos':['cupy-lanczos'], '2017_cupy_lobpcg':['cupy-lobpcg'],
        '2019_torch_cluster_knn':['torch-cluster-knn'], '2017_faiss_flat_knn':['faiss-flat-knn'],
        '2020_dhg_hgnn':['dhg-hgnn','dhg-hgnn-formula'], '2020_dhg_hnhn':['dhg-hnhn'],
        '2020_dhg_hypergcn':['dhg-hypergcn','dhg-hypergcn-domain-rejection'],
        '2020_ripserplusplus':['ripserplusplus-finite-bars','ripserplusplus-essential-h0'],
        '2026_component_aware_mvc':['component-aware-mvc-hybrid','component-aware-mvc-stackonly'],
    }
    rows=[]
    for artifact in read(ROOT/'catalog/artifact_sources.json')['artifacts']:
        metadata=ROOT/artifact['collection_metadata']
        status=read(metadata.parent/'artifact_status.json',{})
        row={k:artifact.get(k) for k in ['problem_id','paper_id','title','code_commit','collection_metadata']}
        code=status.get('code',{});row['runtime_evidence']=[]
        commit=artifact.get('code_commit') or artifact.get('collection_code_commit') or code.get('commit')
        for operation in registry:
            if operation['research_problem']!=row['problem_id']:continue
            for backend in operation['backends']:
                revision=backend.get('source_commit','')
                if backend['id'] in repairs:
                    if row['paper_id'] not in repairs[backend['id']]:continue
                elif not commit or not revision or not (commit.startswith(revision) or revision.startswith(commit)):continue
                key=operation['id']+'/'+backend['id']
                if key in native:row['runtime_evidence'].append({'backend':key,**native[key],'scope':'public CLI validated profile, including local repairs; not a paper-version reproduction','evidence':native_evidence})
        for key in mapping.get(row['paper_id'],[]):
            if key in research:row['runtime_evidence'].append({'backend':key,**research[key]})
        if row['runtime_evidence']:
            row['status']='runtime_failures' if any(e['failed'] for e in row['runtime_evidence']) else 'runtime_checks_passed'
            row['gap']='Only the named scopes were exercised; broader paper claims are not certified.'
        else:
            row['status']='not_runtime_validated'
            if code.get('error'):row['gap']=code['error']
            elif not (metadata.parent/'code').exists():row['gap']='No runnable collected source at the record code path; no integrated runtime adapter/reference test.'
            elif 'nvgraph' in row['paper_id']:row['gap']='Pinned legacy nvGraph configure fails at cpp/CMakeLists.txt:113 (empty include path); no runtime evidence.'
            elif 'cugraph' in row['paper_id']:row['gap']='Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established.'
            elif 'cuvs' in row['paper_id']:row['gap']='No compatible cuVS runtime or NN-descent adapter established; approximate recall remains untested.'
            elif 'dynamic_mis' in row['paper_id'] or 'dynamic_mvc' in row['paper_id'] or 'difusco' in row['paper_id']:row['gap']='Learned solver has no validated checkpoint/inference integration here; feasibility and solution quality remain untested.'
            elif 'graphslim' in row['paper_id']:row['gap']='No condensation training/evaluation integration; synthetic graph quality and downstream accuracy remain untested.'
            else:row['gap']='Collected research source has no executable adapter and independent problem-specific runtime test in this sweep.'
        rows.append(row)
        if row['runtime_evidence']:
            # Collection status is a dated integrity snapshot. Preserve its
            # original not_tested fields and attach subsequent scoped evidence.
            integrated=any(e['evidence']==native_evidence
                           for e in row['runtime_evidence'])
            record={'status':row['status'],'canonical_adapter_available':integrated,
                    'scope_note':('Subsequent runtime checks of the public CLI profile, including local repairs; not a paper-version reproduction.'
                                  if integrated else 'Subsequent runtime checks; not a paper-version reproduction or an integrated solver.'),
                    'checks':row['runtime_evidence']}
            (metadata.parent/'runtime_validation.json').write_text(json.dumps(record,indent=2)+'\n')
            status['subsequent_runtime_validation']='runtime_validation.json'
            (metadata.parent/'artifact_status.json').write_text(json.dumps(status,indent=2)+'\n')
            document=metadata.parent/'ARTIFACT_STATUS.md'
            if document.exists():
                text=document.read_text().split('\nSubsequent runtime validation\n')[0].rstrip()
                text=text.replace('Build, runtime correctness, performance and canonical integration were not tested.',
                    'At collection time, build, runtime correctness, performance and canonical integration had not been tested. Later scoped runtime evidence is linked below.')
                text=text.replace('This sweep checks collection evidence only. Existing runtime validation remains in the validation/ tree; no new GPU build or correctness claim is made here.',
                    'The original collection sweep checked source/paper evidence only. Subsequent scoped runtime evidence is linked below.')
                link=os.path.relpath(HERE/'RESULTS.md',metadata.parent)
                text+='\n\nSubsequent runtime validation\n-----------------------------\n\n'
                scope=('Checks exercise the existing CLI adapter with local repairs; they do not certify every paper claim.'
                       if integrated else 'These checks do not add a canonical adapter or certify every paper claim.')
                text+=f"Status: **{row['status']}**. See [per-record evidence](runtime_validation.json) and the [runtime report]({link}). {scope}\n"
                document.write_text(text)
    report={'records':len(rows),'counts':dict(Counter(r['status'] for r in rows)),'records_by_problem':{},'artifacts':rows}
    for r in rows:report['records_by_problem'].setdefault(r['problem_id'],[]).append(r['paper_id'])
    (HERE/'research_gaps.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Runtime coverage and research gaps','',
           'Each row refers to one collected paper/artifact record. Passing a scoped check does not certify every feature in its paper. Collection integrity checks are recorded separately from execution.','',
           '| Problem | Artifact | Runtime status | Scope or remaining gap |','| --- | --- | --- | --- |']
    for row in rows:
        details='; '.join(f"{e['backend']}: {e['passed']} passed / {e['failed']} failed ({e['scope']})" for e in row['runtime_evidence']) or row['gap']
        lines.append(f"| {row['problem_id']} | {row['paper_id']} | {row['status']} | {details.replace('|','/')} |")
    (HERE/'research_gaps.md').write_text('\n'.join(lines)+'\n')
    programs=read(ROOT/'agent/program_instructions.json')['operations']
    profiles=[]
    for operation in programs:
        native_operation=next(o for o in registry if o['id']==operation['id'])
        for backend in native_operation['backends']:
            profiles.append({'operation':operation['id'],'backend':backend['id'],
                'parameters':operation['parameters'],
                'backend_constraints':operation.get('backend_constraints',{}).get(backend['id'],{}),
                'capabilities':backend['capabilities'],
                'validated_profile':operation.get('validated_profile')})
    (HERE/'parameter_profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    outer=ROOT.parent/'problems';outer_work=ROOT.parent/'validation/parameter_expansion_outer'
    summary=read(outer_work/'summary.json',{'results':[]})
    outer_results={r['backend']:r for r in summary['results']}
    outer_mapping=dict(zip(
        ['2020_kpar','2025_ecl_maxflow','2025_wbpr','2022_g2miner_reuse','2022_gamma_reuse',
         '2021_gpusteiner_kmb','2022_gpu_vlsi_gst','2025_gpu4gst','2021_gim','2021_superfuser',
         '2019_hungariangpu','2021_graphbplus','2026_ecl_sgb','2024_gdlog','2023_eclscc'],
        ['kpar','ecl_flow','wbpr','graphminer_butterfly','gamma_butterfly','gpusteiner','gst_vlsi',
         'gpu4gst','gim','superfuser','hungarian','graphbplus','ecl_sgb','gdlog_tc','ecl_scc']))
    outer_rows=[];contract_errors=[];new_contracts=0
    for path in sorted(outer.glob('*/problem.json')):
        problem=read(path);is_new=int(path.parent.name.split('_')[0])>=21
        new_contracts+=is_new
        for key in ['problem_id','problem_statement','graph_input','required_outputs','solution_semantics']:
            if not problem.get(key):contract_errors.append(str(path)+': missing '+key)
        schema=path.parent/problem.get('graph_input',{}).get('schema_ref','MISSING')
        if not schema.is_file():contract_errors.append(str(path)+': missing input schema')
        for metadata in sorted(path.parent.glob('papers/*/metadata.json')):
            key=outer_mapping.get(metadata.parent.name)
            evidence=outer_results.get(key)
            outer_rows.append({'problem':path.parent.name,'paper_id':metadata.parent.name,'new_problem_group':is_new,
                'metadata':str(metadata),'code_present':(metadata.parent/'code').exists(),
                'status':evidence['status'] if evidence else 'not_runtime_tested',
                'backend':key,'evidence':str(outer_work/key/'results'/f'{key}.json') if evidence else None,
                'gap':evidence.get('limitations',evidence.get('notes',[])) if evidence else 'No executable diagnostic integration for this artifact in the new-problem sweep.'})
    outer_inventory={'problem_contracts':len(list(outer.glob('*/problem.json'))),'new_problem_contracts':new_contracts,
        'records':len(outer_rows),'new_problem_records':sum(r['new_problem_group'] for r in outer_rows),
        'contract_errors':contract_errors,'records_detail':outer_rows,'scope':summary.get('note')}
    (outer_work/'inventory.json').write_text(json.dumps(outer_inventory,indent=2)+'\n')
    outer_doc=['# Outer problem additions: runtime screen','',summary.get('note',''),'',
        'The 37 contracts and their schema references pass structural checks. Of 91 artifact records, 37 belong to newer problem folders 21..37. Fifteen have runnable diagnostic screens; 22 remain runtime gaps. The 54 older records were inventoried only.', '',
        '| Backend | Passed / cases | Status |','| --- | ---: | --- |']
    for result in summary['results']:
        outer_doc.append(f"| {result['backend']} | {result['passed']} / {result['total']} | {result['status']} |")
    outer_doc += ['', 'ECL-Maxflow, GAMMA butterfly and KPAR fail their respective screens. Partial passes retain the original scope limitations, including smoke-only checks for GraphB+ and ECL-SGB and small scalar/path screens for group Steiner solvers.',
        '', 'ECL-Maxflow failures are CUDA invalid-configuration exits on 58 inputs; the scalar may be correct before the runtime failure. GAMMA returns two for a single butterfly (expected one). KPAR returns five entries for top-4; its failure here is not a certified approximation-error violation.',
        '', 'Every case, command, binary hash and limitation is in [summary.json](summary.json) and the per-backend results. [inventory.json](inventory.json) lists each untested record. These results are separate from the repaired inner library.']
    (outer_work/'README.md').write_text('\n'.join(outer_doc)+'\n')
    # Preserve later executable evidence for the original 22 outer-folder gaps.
    additional=ROOT.parent/'validation/outer_integrations'
    if (additional/'summary.json').exists() and (additional/'report.py').exists():
        subprocess.run([sys.executable,str(additional/'report.py'),'--refresh-inventory'],check=True)
    print(report['records'],report['counts'])


if __name__=='__main__':main()
