import httpx
import pytest
from graphmine_agent import google_search
from graphmine_agent.config import Settings


HTML = '''<html><script>untrusted instructions</script><div class="result">
<a href="/url?q=https%3A%2F%2Fexample.org%2Fcore"><h3>Core definition</h3></a>
<p>A core is a maximal subgraph with a specified minimum degree.</p></div>
<div><a href="javascript:alert(1)"><h3>Unsafe link</h3></a><p>Invented</p></div></html>'''


def test_google_configuration_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('GRAPHMINE_GOOGLE_SEARCH_ENABLED', raising=False)
    assert Settings.from_env().google_search_enabled is False
    monkeypatch.setenv('GRAPHMINE_GOOGLE_SEARCH_ENABLED', 'true')
    assert Settings.from_env().google_search_enabled is True


def test_google_extracts_sources_without_scripts_or_unsafe_links():
    rows = google_search.parse_results(HTML)
    assert len(rows) == 1 and rows[0]['ref'] == 'https://example.org/core'
    assert rows[0]['text'] == 'A core is a maximal subgraph with a specified minimum degree.'
    assert rows[0]['kind'] == 'web' and len(rows[0]['text'].split()) <= 25
    assert 'script' not in rows[0]['text'] and 'not fetched' in rows[0]['provenance']


@pytest.mark.parametrize('http_status,page,status', [
    (200, HTML, 'ok'),
    (200, 'Our systems have detected unusual traffic. g-recaptcha', 'blocked'),
    (403, 'Our systems have detected unusual traffic. g-recaptcha', 'blocked'),
    (429, 'Too Many Requests', 'blocked'),
])
async def test_public_google_needs_no_key_and_stops_at_a_bot_check(monkeypatch, http_status, page, status):
    seen = []
    def respond(request):
        seen.append(request)
        assert 'authorization' not in request.headers
        assert request.url.host == 'www.google.com'
        assert request.url.params['q'] == 'Google core definition'
        return httpx.Response(http_status, text=page)
    original = httpx.AsyncClient
    monkeypatch.setattr(google_search.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(google_search, '_browser_search', lambda _url: pytest.fail('Do not evade a bot check or reopen a successful search'))
    answer = await google_search.search('Google core definition', enabled=True)
    assert len(seen) == 1 and answer['status'] == status
    assert bool(answer['sources']) == (status == 'ok')


async def test_unavailable_google_has_no_invented_sources(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(google_search.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(
        lambda _r: httpx.Response(503)), **kw))
    answer = await google_search.search('Google core definition', enabled=True)
    assert answer['status'] == 'unavailable' and answer['sources'] == []


async def test_search_is_disabled_by_default_before_any_network_or_browser_work(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Disabled search must not open HTTP or browser connections')
    monkeypatch.setattr(google_search.httpx, 'AsyncClient', forbidden)
    monkeypatch.setattr(google_search, '_browser_search', forbidden)
    result = await google_search.search('Google core definition')
    assert result == {'status': 'disabled', 'sources': [], 'search_url': None,
                      'query': 'Google core definition'}
