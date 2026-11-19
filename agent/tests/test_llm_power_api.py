from dataclasses import replace

from fastapi.testclient import TestClient

from graphmine_agent.api import create_app
from graphmine_agent.llm_power import server_root
from test_accounts import login, PASSWORD
from test_llm_power import Server, manager


def test_admin_only_controls_status_does_not_wake_and_busy_sleep_is_rejected(settings, tmp_path):
    settings = replace(settings, accounts_enabled=True, account_cookie_secure=False)
    server = Server()
    power = manager(tmp_path / 'leases', server)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        runtime.llm_power.managers[server_root(settings.llm_base_url)] = power
        assert runtime.analytics.llm_power is runtime.llm_power
        runtime.accounts.create_user('admin', PASSWORD, admin=True)
        runtime.accounts.create_user('member', PASSWORD)
        assert client.get('/api/admin/llm/power').status_code == 403
        member = login(client, 'member')
        for method, path in [('get', ''), ('post', '/sleep'), ('post', '/wake')]:
            assert getattr(client, method)('/api/admin/llm/power' + path, headers=member).status_code == 403
        assert not server.calls
        admin = login(client, 'admin')
        status = client.get('/api/admin/llm/power', headers=admin)
        assert status.status_code == 200 and status.json()['sleeping']
        assert 'test-key' not in status.text and server.count('/wake_up') == 0
        awake = client.post('/api/admin/llm/power/wake', headers=admin)
        assert awake.status_code == 200 and not awake.json()['sleeping']
        assert server.count('/wake_up') == server.count('/v1/models') == 1
        power.in_flight = 1
        busy = client.post('/api/admin/llm/power/sleep', headers=admin)
        assert busy.status_code == 409 and busy.json()['error']['code'] == 'llm_busy'
        assert server.count('/sleep') == 0
        power.in_flight = 0
        sleeping = client.post('/api/admin/llm/power/sleep', headers=admin)
        assert sleeping.status_code == 200 and sleeping.json()['sleeping']
    assert power._client is None


def test_wake_timeout_is_a_recoverable_http_error(settings, tmp_path):
    settings = replace(settings, accounts_enabled=True, account_cookie_secure=False)
    server = Server()
    server.stuck = True
    power = manager(tmp_path / 'leases', server, wake_timeout=.035)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        runtime.llm_power.managers[server_root(settings.llm_base_url)] = power
        runtime.accounts.create_user('admin', PASSWORD, admin=True)
        response = client.post('/api/admin/llm/power/wake', headers=login(client, 'admin'))
        assert response.status_code == 503
        assert response.json()['error'] == {'code': 'llm_unavailable',
            'message': 'The model is waking up and did not respond in time'}
        assert power.in_flight == 0
