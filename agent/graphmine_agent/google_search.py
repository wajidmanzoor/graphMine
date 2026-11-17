"""Ordinary public Google search. No API key, CAPTCHA solving or proxy rotation.

Only explicitly requested/general-current web replies use this tool. Search
queries never include uploaded graphs, records, history or hidden context.
"""
import asyncio
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs

import httpx

GOOGLE = 'https://www.google.com'
_browser_slot = asyncio.Semaphore(1)


def requested(question):
    return bool(re.search(r'\bgoogle\b|\b(?:search|look\s+up|check)\b.*\b(?:web|internet|online)\b|\b(?:latest|most recent|up.to.date)\b', question, re.I))


def search_url(question):
    return GOOGLE + '/search?' + urlencode({'q': question, 'udm': '14'})


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        if self.tag in {'script', 'style', 'noscript'}:
            return ''
        return ' '.join(part.text() if isinstance(part, Node) else part for part in self.children)

    def nodes(self, tag):
        return ([self] if self.tag == tag else []) + [row for part in self.children if isinstance(part, Node) for row in part.nodes(tag)]


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in {'br', 'img', 'input', 'meta', 'link', 'hr', 'wbr', 'source'}:
            self.current = node

    def handle_endtag(self, tag):
        cursor = self.current
        while cursor.parent:
            if cursor.tag == tag:
                self.current = cursor.parent
                break
            cursor = cursor.parent

    def handle_data(self, value):
        self.current.children.append(value)


def result_url(href):
    parsed = urlsplit(urljoin(GOOGLE, href))
    if parsed.hostname in {'www.google.com', 'google.com'} and parsed.path == '/url':
        parsed = urlsplit((parse_qs(parsed.query).get('q') or parse_qs(parsed.query).get('url') or [''])[0])
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname == 'google.com' or parsed.hostname.endswith('.google.com'):
        return None
    return parsed.geturl()


def parse_results(html):
    document = Document()
    document.feed(html[:2_000_000])
    rows, seen = [], set()
    for heading in document.root.nodes('h3'):
        anchor = heading
        while anchor.parent and anchor.tag != 'a':
            anchor = anchor.parent
        if anchor.tag != 'a':
            continue
        ref = result_url(anchor.attrs.get('href', ''))
        if not ref or ref in seen:
            continue
        title = ' '.join(heading.text().split())
        block = anchor
        for _ in range(6):
            if not block.parent or len(block.parent.nodes('h3')) != 1:
                break
            block = block.parent
        excerpt = ' '.join(block.text().split())
        if excerpt.startswith(title):
            excerpt = excerpt[len(title):].strip()
        excerpt = excerpt or title
        words = excerpt.split()
        excerpt = ' '.join(words[:25]) + ('…' if len(words) > 25 else '')
        if not excerpt or not title:
            continue
        seen.add(ref)
        rows.append({'id': f'web.{len(rows) + 1}', 'kind': 'web', 'ref': ref, 'title': title,
                     'text': excerpt, 'provenance': 'Google result excerpt; destination page not fetched'})
        if len(rows) == 3:
            break
    return rows


def blocked(url, text):
    return '/sorry/' in url or 'unusual traffic' in text.casefold() or 'g-recaptcha' in text.casefold()


def _browser_search(url):
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        root = Path('/snap/firefox/current/usr/lib/firefox')
        binary = str(root / 'firefox') if (root / 'firefox').is_file() else shutil.which('firefox')
        driver_path = str(root / 'geckodriver') if (root / 'geckodriver').is_file() else shutil.which('geckodriver')
        if not binary or not driver_path:
            return 'unavailable', []
        options = Options(); options.add_argument('-headless'); options.binary_location = binary
        driver = webdriver.Firefox(options=options, service=Service(executable_path=driver_path))
        try:
            driver.set_page_load_timeout(15)
            driver.get(url)
            html = driver.page_source
            if blocked(driver.current_url, html):
                return 'blocked', []
            return 'ok', parse_results(html)
        finally:
            driver.quit()
    except Exception:
        return 'unavailable', []


async def search(question, *, enabled=False):
    if not enabled:
        return {'status': 'disabled', 'sources': [], 'search_url': None, 'query': question[:500]}
    url = search_url(question[:500])
    status, sources = 'unavailable', []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), follow_redirects=True) as client:
            async with client.stream('GET', url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError('Search page too large')
                html = raw.decode('utf-8', errors='replace')
                # Google also returns bot checks as 403/429 responses. Read
                # the bounded body before raising so these never trigger a
                # second browser attempt or become a generic service error.
                if response.status_code == 429 or blocked(str(response.url), html):
                    status = 'blocked'
                else:
                    response.raise_for_status()
                    sources = parse_results(html)
                    status = 'ok' if sources else 'unavailable'
        if not sources and status != 'blocked':
            async with _browser_slot:
                status, sources = await asyncio.to_thread(_browser_search, url)
    except Exception:
        status = 'unavailable'
    return {'status': 'ok' if sources else status if status != 'ok' else 'unavailable',
            'sources': sources, 'search_url': url, 'query': question[:500]}
