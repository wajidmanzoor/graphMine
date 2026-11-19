#!/usr/bin/env python3
"""Check public artifacts for local-link failures and excluded internal content."""
from html.parser import HTMLParser
from pathlib import Path
import html
import re
import subprocess
from urllib.parse import unquote,urlsplit
ROOT=Path(__file__).resolve().parents[1]/'site'
PREFIX='/graphMine/'
class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.ids=set();self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'):self.ids.add(a['id'])
        for key in ('href','src'):
            if a.get(key):self.links.append(a[key])
        if tag=='a' and a.get('name'):self.ids.add(a['name'])
pages={p:Page(p.read_text(errors='replace')) for p in ROOT.rglob('*.html')}
errors=[];links=0
for path,page in pages.items():
    for link in page.links:
        url=urlsplit(link)
        if url.scheme or url.netloc or link.startswith(('javascript:','data:')):continue
        if not url.path:target=path
        elif url.path.startswith(PREFIX):target=ROOT/unquote(url.path[len(PREFIX):])
        elif url.path.startswith('/'):
            errors.append(f'{path.relative_to(ROOT)}: link escapes project prefix: {url.path}');continue
        else:target=(path.parent/unquote(url.path)).resolve()
        if target.is_dir():target/= 'index.html'
        if not target.exists():
            errors.append(f'{path.relative_to(ROOT)}: missing {link}');continue
        links+=1
        if url.fragment and target in pages:
            fragment=unquote(url.fragment)
            dynamic=(target==ROOT/'problem/explorer/index.html' and re.fullmatch(r'(family|problem)/[a-z0-9_-]+',fragment))
            if not dynamic and fragment not in pages[target].ids:
                errors.append(f'{path.relative_to(ROOT)}: missing anchor {link}')
# Word boundaries distinguish an environment-variable implementation from an
# environment file, and a paper title from account-management instructions.
forbidden=[r'127\.0\.0\.1',r'\blocalhost\b',r':(?:8001|18000|8877)\b',
           r'GPU-[0-9a-fA-F]{8}',r'\.env\b',r'\bsystemd\b',r'\badmin(?:istrator|istration)?\b',
           r'(?:/home/|/Users/)[A-Za-z0-9_.-]+',r'\bdata(?:set)?[ -]studio\b',
           r'\b(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2})\b']
for path in ROOT.rglob('*'):
    if not path.is_file():continue
    if path.suffix=='.pdf':
        value=subprocess.check_output(['pdftotext',str(path),'-'],text=True)
    elif path.suffix in {'.html','.json','.js','.css','.txt','.xml'}:
        value=html.unescape(path.read_text(errors='replace'))
    else:continue
    for pattern in forbidden:
        if path.name == 'wordcut.js' and pattern == r'\.env\b':
            # Bundled search dependency uses the JavaScript process.env property, not a file.
            checked_value = value.replace('process.env', 'process_environment')
        else:
            checked_value = value
        if re.search(pattern,checked_value,re.I):errors.append(f'{path.relative_to(ROOT)}: forbidden pattern {pattern}')
if errors:
    print('\n'.join(errors[:80]))
    raise SystemExit(f'{len(errors)} public-site errors')
print(f'Checked {len(pages)} HTML pages, {links} local links, and public-content exclusions.')
