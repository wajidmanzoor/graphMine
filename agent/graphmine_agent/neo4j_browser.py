"""Serve the existing Neo4j Browser on one LAN-only HTTPS/WebSocket endpoint.

Neo4j stays on loopback. Credentials are supplied by the browser and checked by
Neo4j; this proxy neither stores credentials nor authenticates on a user's behalf.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .database import RecordNotFound
from .errors import AnalyticsError
from .neo4j_backend import local_browser_endpoints
from .neo4j_local import cli_settings

HOST = "10.33.76.25"
PORT = 17473
AUTHORITY = f"{HOST}:{PORT}"
ORIGIN = f"https://{AUTHORITY}"
REPOSITORY = Path(__file__).resolve().parents[2]
WORKSPACE = REPOSITORY.parent
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False,
        timeout=httpx.Timeout(300, connect=5),
        limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
    ) as client:
        app.state.client = client
        app.state.settings = cli_settings(REPOSITORY)
        yield


async def proxy_http(request: Request):
    if request.headers.get("host") != AUTHORITY:
        return Response("Unknown host", status_code=400)
    origin = request.headers.get("origin")
    if origin and origin != ORIGIN:
        return Response("Cross-origin requests are not allowed", status_code=403)
    try:
        http_backend, _ = local_browser_endpoints(request.app.state.settings)
    except (RecordNotFound, AnalyticsError, ValueError):
        return Response("Local Neo4j Browser is unavailable for the active backend", status_code=503)
    excluded = HOP_HEADERS | {"host", "accept-encoding", "forwarded"}
    excluded.update(part.strip().lower() for part in request.headers.get("connection", "").split(","))
    headers = {
        key: value for key, value in request.headers.items()
        if key.lower() not in excluded and not key.lower().startswith("x-forwarded-")
    }
    headers["accept-encoding"] = "identity"
    target = http_backend + request.scope["raw_path"].decode("ascii")
    if request.scope["query_string"]:
        target += "?" + request.scope["query_string"].decode("ascii")
    client = request.app.state.client
    try:
        outgoing = client.build_request(
            request.method, target, headers=headers, content=request.stream()
        )
        upstream = await client.send(outgoing, stream=True)
    except httpx.HTTPError:
        return Response("Local Neo4j is unavailable", status_code=502)
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key.lower() not in HOP_HEADERS
    }
    if "location" in response_headers:
        response_headers["location"] = response_headers["location"].replace(http_backend, ORIGIN)
    if request.url.path == "/" and request.method == "GET" and upstream.status_code == 200:
        try:
            await upstream.aread()
            discovery = upstream.json()
            # Direct Bolt avoids native routing addresses that are local-only.
            discovery["bolt_direct"] = f"bolt+s://{AUTHORITY}"
            discovery["bolt_routing"] = f"bolt+s://{AUTHORITY}"
            for key in ("query", "transaction"):
                if key in discovery:
                    discovery[key] = discovery[key].replace(http_backend, ORIGIN)
            return JSONResponse(discovery)
        finally:
            await upstream.aclose()
    return StreamingResponse(
        upstream.aiter_raw(), status_code=upstream.status_code,
        headers=response_headers, background=BackgroundTask(upstream.aclose),
    )


async def proxy_bolt(socket: WebSocket):
    if socket.headers.get("host") != AUTHORITY or socket.headers.get("origin") != ORIGIN:
        await socket.close(code=1008)
        return
    try:
        _, websocket_backend = local_browser_endpoints(socket.app.state.settings)
    except (RecordNotFound, AnalyticsError, ValueError):
        await socket.close(code=1008)
        return
    protocols = socket.scope.get("subprotocols", [])
    try:
        async with connect(
            websocket_backend, origin=ORIGIN, subprotocols=protocols or None,
            proxy=None, compression=None, max_size=64 * 1024 * 1024,
            ping_interval=30, ping_timeout=30,
        ) as upstream:
            await socket.accept(subprotocol=upstream.subprotocol)

            async def to_neo4j():
                while True:
                    message = await socket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    payload = message.get("bytes")
                    await upstream.send(payload if payload is not None else message["text"])

            async def to_browser():
                async for message in upstream:
                    if isinstance(message, bytes):
                        await socket.send_bytes(message)
                    else:
                        await socket.send_text(message)

            tasks = [asyncio.create_task(to_neo4j()), asyncio.create_task(to_browser())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (ConnectionClosed, WebSocketDisconnect, OSError, TimeoutError):
        pass
    finally:
        with suppress(RuntimeError, WebSocketDisconnect):
            await socket.close()


app = Starlette(
    lifespan=lifespan,
    routes=[
        WebSocketRoute("/", proxy_bolt),
        Route("/{path:path}", proxy_http, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
    ],
)


if __name__ == "__main__":
    uvicorn.run(
        app, host=HOST, port=PORT,
        ssl_certfile=str(WORKSPACE / "graphmine-data/tls/graphmine.crt"),
        ssl_keyfile=str(WORKSPACE / "graphmine-data/tls/graphmine.key"),
        proxy_headers=False, access_log=False, limit_concurrency=64,
        ws_max_size=64 * 1024 * 1024,
    )
