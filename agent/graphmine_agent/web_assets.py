"""Immutable UI snapshots tied to the backend process that serves them."""

import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.responses import Response


class WebAssets:
    def __init__(self, static: Path):
        self.files = {path.relative_to(static).as_posix(): path.read_bytes()
                      for path in static.rglob("*") if path.is_file()}
        digest = hashlib.sha256()
        for name, value in sorted(self.files.items()):
            digest.update(name.encode() + b"\0" + value)
        for path in sorted(static.parent.glob("*.py")):
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
        self.build_id = digest.hexdigest()[:20]
        self.bundles = {}
        self.pages = {}
        for source in ("vendor/cytoscape.min.js", "vendor/graph-layouts.min.js"):
            vendor = self.files.get(source)
            if vendor and "analytics-graph-library.js" in self.files:
                name = f"assets/{hashlib.sha256(vendor).hexdigest()[:24]}.js"
                self.bundles[name] = vendor
                self.files["analytics-graph-library.js"] = self.files["analytics-graph-library.js"].replace(("/" + source).encode(), ("/" + name).encode())
        worker = self.files.get("vendor/layout-worker.min.js")
        if worker and "analytics-visualization.js" in self.files:
            name = f"assets/{hashlib.sha256(worker).hexdigest()[:24]}.js"
            self.bundles[name] = worker
            self.files["analytics-visualization.js"] = self.files["analytics-visualization.js"].replace(b"/vendor/layout-worker.min.js", ("/" + name).encode())
        for page in ("analytics.html", "index.html"):
            html = self.files[page].decode()
            # Preserve the declared order of classic deferred scripts and CSS.
            for pattern, suffix, template in (
                (r'<link rel="stylesheet" href="/([^"]+)"\s*>', "css", '<link rel="stylesheet" href="/{name}">'),
                (r'<script src="/([^"]+)" defer></script>', "js", '<script src="/{name}" defer></script>'),
            ):
                matches = list(re.finditer(pattern, html))
                if not matches:
                    continue
                content = (b"\n;\n" if suffix == "js" else b"\n").join(self.files[m[1]] for m in matches)
                name = f"assets/{hashlib.sha256(content).hexdigest()[:24]}.{suffix}"
                self.bundles[name] = content
                first = True

                def replace(_match):
                    nonlocal first
                    if not first:
                        return ""
                    first = False
                    return template.format(name=name)

                html = re.sub(pattern, replace, html)
            html = html.replace("</head>", f'<meta name="graphmine-build" content="{self.build_id}"></head>')
            self.pages[page] = html

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        path = scope["path"].lstrip("/")
        if scope["method"] not in {"GET", "HEAD"}:
            response = Response(status_code=405, headers={"Allow": "GET, HEAD"})
        elif path in self.pages:
            response = Response(self.pages[path], media_type="text/html", headers={"Cache-Control": "no-cache"})
        else:
            value = self.bundles.get(path, self.files.get(path))
            if value is None:
                response = Response(status_code=404)
            else:
                etag = '"' + hashlib.sha256(value).hexdigest() + '"'
                headers = {"ETag": etag, "Cache-Control": "public, max-age=31536000, immutable" if path in self.bundles else "no-cache"}
                request_headers = dict(scope.get("headers", []))
                if request_headers.get(b"if-none-match", b"").decode() == etag:
                    response = Response(status_code=304, headers=headers)
                else:
                    response = Response(value, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream", headers=headers)
        if scope["method"] == "HEAD":
            response.body = b""
        await response(scope, receive, send)


class WebHeaders:
    """Headers also cover authentication failures and streamed responses."""

    def __init__(self, app, allowed_origins=()):
        self.app = app
        origins = []
        for origin in allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme in {"http", "https"} and parsed.netloc and not re.search(r"[\s;'\"\\]", origin):
                origins.extend([f"{parsed.scheme}://{parsed.netloc}", f"{'wss' if parsed.scheme == 'https' else 'ws'}://{parsed.netloc}"])
        self.connections = " ".join(["'self'", *origins])

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "same-origin"
                script = "'self'"
                if scope["path"] in {"/classic", "/index.html"}:
                    script += " 'unsafe-eval'"  # The legacy Vega interpreter.
                # FastAPI's documentation includes a CDN library and initializer.
                if scope["path"] in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
                    script += " 'unsafe-inline' https://cdn.jsdelivr.net"
                headers["Content-Security-Policy"] = (
                    f"default-src 'self'; script-src {script}; "
                    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "img-src 'self' data: blob: https://fastapi.tiangolo.com; "
                    f"font-src 'self' data:; connect-src {self.connections}; worker-src 'self' blob:; "
                    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
                )
                if scope["path"].startswith("/api/admin/performance/runs/") and scope["path"].endswith("/report"):
                    # The suite produces self-contained HTML with inline Vega.
                    # An opaque sandbox permits its charts, without API/network,
                    # cookie access, forms, popups or same-origin privileges.
                    headers["Content-Security-Policy"] = (
                        "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
                        "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
                        "connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                    )
                if scope["path"].startswith("/api/"):
                    headers["Cache-Control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, with_headers)
