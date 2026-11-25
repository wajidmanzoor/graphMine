#!/usr/bin/env python3
"""Validate a running release using a temporary account, disabled afterwards.

Requires explicit operator invocation. Requests run real calculations and leave
evaluation-tagged history for inspection; they never train the backend policy.
Run with the selected environment's Python and its private controller config.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--environment', required=True, choices=['testing', 'production'])
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--routing', action='store_true', help='Also check one live family/route question')
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    role = json.loads(args.config.read_text())['environments'][args.environment]
    os.environ.update({k: str(v) for k, v in role['env'].items()})
    sys.path[:0] = [role['code'] + '/agent', role['code'] + '/python/graphmine']
    import httpx
    from graphmine_agent.accounts import Accounts
    from graphmine_agent.backend_learning import models
    from graphmine_agent.backend_learning.storage import read_rows
    from graphmine_agent.config import Settings
    from graphmine_agent.database import Database
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait

    settings = Settings.from_env(Path(role['code']))
    accounts = Accounts(settings, Database(settings.database_path))
    username, password = 'release-check-' + secrets.token_hex(5), secrets.token_urlsafe(32)
    accounts.create_user(username, password)
    scheme = 'https' if role['env'].get('GRAPHMINE_TLS_CERTFILE') else 'http'
    base = f"{scheme}://127.0.0.1:{role['env']['GRAPHMINE_API_PORT']}"
    proof = dict(environment=args.environment, passed=False,
                 commit=subprocess.check_output(['git', '-C', role['code'], 'rev-parse', 'HEAD'], text=True).strip(),
                 started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    workflows = []
    try:
        assert settings.job_timeout_seconds == settings.account_job_seconds == settings.backend_default_timeout_seconds == 21600
        assert settings.max_upload_bytes is None and settings.analytics_max_input_bytes is None
        model, metadata = models.load(settings.backend_model_dir)
        assert model['architecture'] == 'shared_nn'
        assert all(item['kind'] in {'aggregate', 'missing', 'problem'} and
                   'parameter' not in item['name'] for item in model['feature_schema'])
        proof['model_version'] = model['model_version']
        proof['execution_timeout_seconds'] = 21600
        proof['input_byte_limits'] = None
        with httpx.Client(base_url=base, verify=False, timeout=120, headers={'X-GraphMine-Request': '1'}) as client:
            response = client.post('/api/auth/login', json={'username': username, 'password': password})
            assert response.status_code == 200, 'Release account login failed'
            caps = client.get('/api/analytics/capabilities?refresh=true').raise_for_status().json()
            assert not caps['verification_issues'], caps['verification_issues']
            assert caps['implementation_sha256'] == model['implementation_sha256']
            cpu = sum(bool(c['execution']['cpu']) for c in caps['problems'])
            gpu = sum(bool(c['execution']['gpu']) for c in caps['problems'])
            profiles = sum(b['device'] == 'gpu' and b.get('verified', False) for c in caps['problems'] for b in c['backends'])
            assert (cpu, gpu, profiles) == (82, 35, 58), (cpu, gpu, profiles)
            bicliques = next(c for c in caps['problems'] if c['id'] == 'maximal-bicliques')
            assert bicliques['verified_backends'] == ['cpp'], 'cuMBE must remain quarantined'
            proof['capabilities'] = dict(cpu_problems=cpu, gpu_problems=gpu, gpu_profiles=profiles,
                                         implementation_sha256=caps['implementation_sha256'])
            graph = dict(graph=dict(id='release-triangle', directed=False, allows_self_loops=False, allows_parallel_edges=False),
                         vertices=[dict(id=i) for i in range(3)],
                         edges=[dict(id=str(i), source=u, target=v) for i, (u, v) in enumerate([(0, 1), (1, 2), (0, 2)])])
            session = client.post('/api/sessions', json={'domain_id': 'general', 'title': 'Release validation'}).raise_for_status().json()
            uploaded = client.post(f"/api/sessions/{session['id']}/files",
                files={'file': ('triangle.json', json.dumps(graph).encode(), 'application/json')},
                data={'role': 'graph', 'directed': 'false'}).raise_for_status().json()
            cases = [('triangle-counting', 'cpp', 'cpu', {}, True),
                     ('triangle-counting', 'wetric', 'gpu', {}, False),
                     ('k-core', 'kcore-gpu', 'gpu', {'requested_k': 2}, False),
                     ('community-detection', 'gleiden', 'gpu', {}, False),
                     ('triangle-counting', 'auto', 'auto', {}, False)]
            proof['calculations'] = []
            for problem, backend, device, parameters, legacy in cases:
                step = {'id': 'analysis', 'operation' if legacy else 'problem': problem,
                        'input': {'input': 'main'}, 'parameters': parameters, 'backend': backend}
                payload = {'mode': 'expert', 'evaluation_id': 'full-gpu-release-20261125',
                           'inputs': {'main': {'kind': 'graph', 'file_id': uploaded['id']}},
                           'plan': {'version': 1, 'device': device, 'steps': [step]}}
                record = client.post(f"/api/sessions/{session['id']}/workflows", json=payload).raise_for_status().json()
                identifier = record['id']; workflows.append(identifier)
                canonical = record['validation']['plan']['steps'][0]
                assert canonical['problem'] == problem and 'operation' not in canonical
                client.post(f'/api/workflows/{identifier}/run', json={
                    'workflow_hash': record['validation']['workflow_hash'], 'expected_revision': record['revision']}).raise_for_status()
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    record = client.get(f'/api/workflows/{identifier}').raise_for_status().json()
                    if record['status'] not in {'queued', 'running'}:
                        break
                    time.sleep(.3)
                assert record['status'] == 'completed', (problem, backend, record.get('error'), record['status'])
                result = client.get(f'/api/workflows/{identifier}/result').raise_for_status().json()['steps']['analysis']['result']
                assert result['problem'] == problem and 'operation' not in result
                if backend != 'auto':
                    assert result['backend']['id'] == backend and result['backend']['device'] == device
                if result['backend']['device'] == 'gpu':
                    assert result['backend']['hardware']['uuid'] == role['env']['GRAPHMINE_GRAPH_GPU_UUID']
                if problem == 'triangle-counting':
                    assert result['ports']['count']['value'] == 1
                proof['calculations'].append(dict(problem=problem, requested_backend=backend,
                    actual_backend=result['backend']['id'], device=result['backend']['device'], legacy_key=legacy, passed=True))

            for _ in range(40):
                rows = [r for r in read_rows(settings.backend_data_dir, include_benchmarks=False) if r.get('workflow_id') in workflows]
                if len(rows) >= len(cases):
                    break
                time.sleep(.25)
            assert len(rows) == len(cases), 'Missing decision telemetry'
            assert all(r['is_evaluation'] and r['outcome'] == 'completed' for r in rows)
            automatic = next(r for r in rows if r['workflow_id'] == workflows[-1])
            assert automatic['selection_mode'] == 'bandit' and automatic['model_version'] == model['model_version']
            assert automatic['selection_probability'] == automatic['probabilities'][automatic['chosen_backend']]
            assert abs(sum(automatic['probabilities'].values()) - 1) < 1e-9
            assert len(automatic['context_features']) == len(model['feature_schema'])
            proof['automatic_decision'] = {k: automatic[k] for k in ['selection_mode', 'chosen_backend', 'selection_probability', 'eligible_backends', 'model_version']}

            if args.routing:
                planned = client.post(f"/api/sessions/{session['id']}/analytics/plan", timeout=300, json={
                    'message': 'Count the triangles in this graph.', 'mode': 'normal', 'device': 'auto',
                    'evaluation_id': 'full-gpu-release-20261125',
                    'inputs': {'main': {'kind': 'graph', 'file_id': uploaded['id']}}}).raise_for_status().json()
                assert planned['status'] == 'options' and 1 <= len(planned['options']) <= 3, planned['status']
                assert planned['options'][0]['problems'] == ['triangle-counting']
                assert planned['options'][0]['parameters'].get('mode', 'count') == 'count'
                events = Database(settings.database_path).events(session['id'], types=('workflow.model_call',))
                stages = [e.payload['stage'] for e in events if e.payload.get('turn_id') == planned['turn_id']]
                assert stages == ['family', 'route'], stages
                proof['routing_smoke'] = dict(correct_calculation=True, correct_mode=True,
                    model_calls=len(stages), stages=stages, cards=len(planned['options']))

            firefox = Path('/snap/firefox/current/usr/lib/firefox')
            options = Options(); options.add_argument('-headless'); options.binary_location = str(firefox / 'firefox')
            options.accept_insecure_certs = True
            browser = webdriver.Firefox(options=options, service=Service(executable_path=str(firefox / 'geckodriver')))
            try:
                browser.set_window_size(1440, 1050); browser.get(base)
                for cookie in client.cookies.jar:
                    browser.add_cookie(dict(name=cookie.name, value=cookie.value, path=cookie.path, secure=cookie.secure, httpOnly=True))
                # Hash navigation alone does not rerun the authentication bootstrap.
                browser.refresh()
                browser.get(base + f"/#workspace/{session['id']}/results/{workflows[-1]}")
                WebDriverWait(browser, 90).until(lambda d: d.execute_script('return GraphMineWorkspace.state.result && GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy'))
                assert browser.execute_script('return GraphMineWorkspace.state.caps.problems.length') == 82
                browser.save_screenshot(str(args.report.with_suffix('.png')))
                proof['browser_saved_result'] = 'passed'
            finally:
                browser.quit()
            studio = client.get(f"{scheme}://127.0.0.1:{role['studio_port']}/", follow_redirects=True)
            assert studio.status_code == 200
            proof['studio_health'] = 'passed'
        proof['passed'] = True
    finally:
        accounts.disable(username)
        proof.update(test_account_disabled=True, finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(proof, indent=2) + '\n'); args.report.chmod(0o600)
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
