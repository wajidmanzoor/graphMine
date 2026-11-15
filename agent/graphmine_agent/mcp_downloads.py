"""Bounded MCP export attachments with authenticated HTTP download fallbacks."""

import base64
import hashlib
import json


def download_result(response, raw, *, complete):
    # Links carry neither the bridge's bearer token nor URL userinfo. Fetching
    # them requires the same GraphMine authentication as the originating call.
    uri = str(response.request.url.copy_with(username="", password=""))
    mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
    name = {"text/csv": "graphmine-export.csv", "application/json": "graphmine-export.json", "application/zip": "graphmine-report.zip"}.get(mime, "graphmine-export")
    value = {"download_uri": uri, "mime_type": mime, "embedded": complete, "requires_authentication": True}
    if complete:
        value.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        resource = {"uri": uri, "mimeType": mime}
        if mime.startswith("text/") or mime == "application/json":
            resource["text"] = raw.decode("utf-8")
        else:
            resource["blob"] = base64.b64encode(raw).decode("ascii")
        content = {"type": "resource", "resource": resource}
    else:
        size = response.headers.get("content-length", "")
        if size.isdigit(): value["bytes"] = int(size)
        value["message"] = "Export exceeds the inline MCP limit. Download the complete artifact with your existing GraphMine authentication; no partial content is embedded."
        content = {"type": "resource_link", "uri": uri, "name": name, "mimeType": mime,
                   "description": "Complete GraphMine export; requires the same API/account authentication. This link is not an access token."}
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}, content], "structuredContent": value, "isError": False}


async def read_download(response, inline_limit, message_limit):
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > inline_limit:
        return download_result(response, b"", complete=False)
    raw = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
        if len(raw) + len(chunk) > inline_limit:
            return download_result(response, b"", complete=False)
        raw.extend(chunk)
    payload = download_result(response, bytes(raw), complete=True)
    # Text escaping can expand substantially; account for the final MCP wrapper.
    if len(json.dumps(payload, ensure_ascii=False).encode()) > message_limit - 1024:
        return download_result(response, b"", complete=False)
    return payload
