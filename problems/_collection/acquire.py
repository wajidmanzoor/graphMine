#!/usr/bin/env python3
"""Collect public upstream research artifacts without executing upstream code.

Source snapshots are pinned, shared, and never silently replaced. PDFs are
accepted only after pdfinfo succeeds. Network operations require an explicit
command; importing this module has no side effects.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / '_sources'
MAX_DOWNLOAD = 150 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def fetch(url):
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS public artifact URLs are accepted')
    request = Request(url, headers={'User-Agent': 'GraphMine-research-collection/1.0',
                                   'Accept': '*/*'})
    with urlopen(request, timeout=45) as response:
        body = response.read(MAX_DOWNLOAD + 1)
        if len(body) > MAX_DOWNLOAD:
            raise ValueError('Download exceeds the artifact size limit')
        return body, response.geturl()


def source(key, repository, ref=None):
    if not re.fullmatch(r'[a-z0-9_]+', key):
        raise ValueError('Invalid source key')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Expected owner/repository')
    manifest_path = SOURCES / (key + '.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['source_url'].removesuffix('/') != 'https://github.com/' + repository:
            raise ValueError('Existing key belongs to a different repository')
        if ref and re.fullmatch(r'[a-f0-9]{40}', ref) and manifest.get('commit') != ref:
            raise ValueError('Use a new key for a different source commit')
        if not (SOURCES / manifest['local_path']).is_dir():
            raise ValueError('Existing manifest has no source snapshot')
        return manifest
    repo = json.loads(fetch('https://api.github.com/repos/' + repository)[0])
    commit = json.loads(fetch('https://api.github.com/repos/' + repository + '/commits/' +
                             (ref or repo['default_branch']))[0])['sha']
    url = f'https://codeload.github.com/{repository}/tar.gz/{commit}'
    data, resolved = fetch(url)
    local = key + '-' + commit[:12]
    SOURCES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='graphmine-source-', dir=SOURCES) as temporary:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            members = archive.getmembers()
            if sum(m.size for m in members) > 700 * 1024 * 1024:
                raise ValueError('Expanded archive exceeds the size limit')
            archive.extractall(temporary, filter='data')
        roots = list(Path(temporary).iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError('Unexpected source archive layout')
        license_files = [str(p.relative_to(roots[0])) for p in roots[0].iterdir()
                         if p.is_file() and re.match(r'^(LICENSE|COPYING|LICENCE)', p.name, re.I)]
        # Public inspection is permitted; collecting a new unlicensed snapshot
        # for redistribution is not. Existing snapshots are reported separately.
        if not license_files:
            raise ValueError('No top-level license: retain a source reference only')
        destination = SOURCES / local
        if destination.exists():
            raise ValueError('Refusing to overwrite an existing snapshot')
        shutil.move(str(roots[0]), destination)
    manifest = dict(source_url='https://github.com/' + repository, checked_at=now(),
                    status='downloaded', error=None, commit=commit, archive_url=url,
                    archive_sha256=hashlib.sha256(data).hexdigest(), local_path=local,
                    license_files=license_files, license_spdx=(repo.get('license') or {}).get('spdx_id'),
                    archived=repo.get('archived', False),
                    submodules_present=(destination / '.gitmodules').exists(),
                    submodules_materialized=False, build_status='not_tested', runtime_status='not_tested')
    write_json(manifest_path, manifest)
    return manifest


def paper(url, destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT):
        raise ValueError('Paper destination must be inside problems/')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        data = destination.read_bytes()
        resolved = url
    else:
        data, resolved = fetch(url)
    if data[:5] != b'%PDF-':
        raise ValueError('Response is not a PDF')
    with tempfile.NamedTemporaryFile(suffix='.pdf', dir=destination.parent) as temporary:
        temporary.write(data)
        temporary.flush()
        info = subprocess.run(['pdfinfo', temporary.name], capture_output=True, text=True, timeout=30)
        if info.returncode:
            raise ValueError('PDF integrity check failed: ' + info.stderr[:200])
        if not destination.exists():
            shutil.copyfile(temporary.name, destination)
    return dict(status='downloaded', source_url=url, resolved_url=resolved,
                local_path=destination.name, error=None, checked_at=now(),
                sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), pdfinfo_valid=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    src = sub.add_parser('source')
    src.add_argument('key')
    src.add_argument('repository')
    src.add_argument('--ref')
    pdf = sub.add_parser('paper')
    pdf.add_argument('url')
    pdf.add_argument('destination')
    args = parser.parse_args()
    if args.operation == 'source':
        print(json.dumps(source(args.key, args.repository, args.ref), indent=2))
    else:
        print(json.dumps(paper(args.url, args.destination), indent=2))
