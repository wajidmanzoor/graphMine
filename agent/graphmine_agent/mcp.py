"""MCP 2025-11-25 stdio bridge to the authenticated workflow HTTP API.

Run ``python -m graphmine_agent.mcp`` with GRAPHMINE_API_URL and
GRAPHMINE_API_TOKEN. The bridge neither loads a library nor runs user code.
"""

from __future__ import annotations

import asyncio
import json
import os
import string
import sys
from copy import deepcopy
from urllib.parse import quote

import httpx
import jsonschema

from .analytics import WorkflowApproval, WorkflowRequest, WorkflowRevision
from .analytics_planning import PlanningRequest
from .analytics_projection import ProjectionRequest
from .models import SessionCreate
from .mcp_database import database_tools
from .mcp_downloads import read_download

PROTOCOL = "2025-11-25"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_EXPORT_INLINE_BYTES = 4 * 1024 * 1024


def tools():
    definitions = [
        (
            "table_schema",
            "GET",
            "/api/sessions/{session_id}/tables/{file_id}/schema",
            None,
            "Inspect an uploaded CSV table through native cuDF, including its columns and a bounded sample.",
        ),
        (
            "project_graph",
            "POST",
            "/api/sessions/{session_id}/projections",
            ProjectionRequest,
            "Build and save a graph from uploaded table IDs using explicit native joins, weight meanings, time windows and duplicate rules.",
        ),
        (
            "capabilities",
            "GET",
            "/api/analytics/capabilities",
            None,
            "List the native operations currently admitted by verification evidence.",
        ),
        (
            "create_workspace",
            "POST",
            "/api/sessions",
            SessionCreate,
            "Create a workspace for uploaded data and analyses.",
        ),
        (
            "list_files",
            "GET",
            "/api/sessions/{session_id}/files",
            None,
            "List uploaded input files in a workspace.",
        ),
        (
            "plan_question",
            "POST",
            "/api/sessions/{session_id}/analytics/plan",
            PlanningRequest,
            "Route a question to operations, a display change of a saved result, or an answer from its facts, and validate a proposed workflow. Does not execute it.",
        ),
        (
            "create_workflow",
            "POST",
            "/api/sessions/{session_id}/workflows",
            WorkflowRequest,
            "Validate and save a workflow. Interactive mode requires a separate approval; Normal mode starts execution.",
        ),
        (
            "list_workflows",
            "GET",
            "/api/sessions/{session_id}/workflows",
            None,
            "List saved workflows and their status.",
        ),
        (
            "get_workflow",
            "GET",
            "/api/workflows/{workflow_id}",
            None,
            "Inspect the validated plan, revision, approval hash, status, and execution provenance.",
        ),
        (
            "revise_workflow",
            "POST",
            "/api/workflows/{workflow_id}/revise",
            WorkflowRevision,
            "Edit and revalidate a workflow at its expected revision; previous approval is invalidated.",
        ),
        (
            "approve_workflow",
            "POST",
            "/api/workflows/{workflow_id}/run",
            WorkflowApproval,
            "Approve and start the exact reviewed workflow hash and revision.",
        ),
        (
            "cancel_workflow",
            "DELETE",
            "/api/workflows/{workflow_id}",
            None,
            "Cancel queued or running work and release its device allocation.",
        ),
        (
            "workflow_result",
            "GET",
            "/api/workflows/{workflow_id}/result",
            None,
            "Fetch the full saved result, including completeness and native provenance. Use result_page for large outputs.",
        ),
        (
            "result_page",
            "GET",
            "/api/workflows/{workflow_id}/steps/{step}/ports/{port}",
            None,
            "Read a bounded page of a typed result port; completeness and total size remain explicit.",
        ),
    ]
    rows = {}
    for name, method, path, model, description in definitions:
        schema = (
            deepcopy(model.model_json_schema())
            if model
            else {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
        )
        path_keys = [
            field for _, field, _, _ in string.Formatter().parse(path) if field
        ]
        for key in path_keys:
            schema["properties"][key] = {
                "type": "string",
                "pattern": r"^[A-Za-z0-9_-]{1,128}$",
            }
        schema.setdefault("required", []).extend(path_keys)
        if name == "result_page":
            schema["properties"].update(
                {
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": 100,
                    },
                }
            )
        if name in {"workflow_result", "result_page"}:
            schema["properties"]["expected_revision"] = {"type": "integer", "minimum": 1}
        rows[name] = {
            "definition": {
                "name": name,
                "description": description,
                "inputSchema": schema,
                "annotations": {
                    "readOnlyHint": method == "GET",
                    "openWorldHint": False,
                    "destructiveHint": name == "cancel_workflow",
                },
            },
            "method": method,
            "path": path,
            "path_keys": path_keys,
        }
    rows.update(database_tools())
    return rows


def result(value, error=False):
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, allow_nan=False),
            }
        ],
        "structuredContent": value if isinstance(value, dict) else {"items": value},
        "isError": error,
    }


class Bridge:
    def __init__(self, client):
        self.client = client
        self.tools = tools()
        self.initialized = False
        self.ready = False

    async def handle(self, request):
        identifier = request.get("id") if isinstance(request, dict) else None

        def error(code, message):
            return {
                "jsonrpc": "2.0",
                "id": identifier if type(identifier) in (str, int) and (not isinstance(identifier, str) or len(identifier.encode()) <= 1024) else None,
                "error": {"code": code, "message": message},
            }

        if (
            not isinstance(request, dict)
            or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)
            or ("id" in request and type(identifier) not in (str, int))
            or (isinstance(identifier, str) and len(identifier.encode()) > 1024)
        ):
            return error(-32600, "Invalid JSON-RPC request")
        method, params = request["method"], request.get("params", {})
        if "id" not in request:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        if not isinstance(params, dict):
            return error(-32602, "Parameters must be an object")
        if method == "initialize":
            if (
                not isinstance(params.get("protocolVersion"), str)
                or not isinstance(params.get("capabilities"), dict)
                or not isinstance(params.get("clientInfo"), dict)
            ):
                return error(
                    -32602,
                    "Initialization requires protocolVersion, capabilities, and clientInfo",
                )
            self.initialized = True
            payload = {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "graphmine-workflows", "version": "1.0.0"},
                "instructions": "Discover authorized sources, submit a query with a stable request_key, and follow its durable database job. Save or open temporary snapshots to retain them. Page large tables/results; exports preserve complete artifacts and may return authenticated download links. Interactive workflows require review and exact revision approval. Ownership, evidence, quotas and input validation use the same HTTP API as the browser.",
            }
        elif method == "ping":
            payload = {}
        elif not self.ready:
            return error(-32000, "Initialize the connection before calling tools")
        elif method == "tools/list":
            if params.get("cursor") is not None:
                return error(-32602, "This tool catalog has no further pages")
            payload = {"tools": [row["definition"] for row in self.tools.values()]}
        elif method == "tools/call":
            row = (
                self.tools.get(params.get("name"))
                if isinstance(params.get("name"), str)
                else None
            )
            if row is None:
                return error(-32602, "Unknown tool")
            arguments = params.get("arguments", {})
            try:
                jsonschema.Draft202012Validator(
                    row["definition"]["inputSchema"]
                ).validate(arguments)
            except jsonschema.ValidationError as exc:
                payload = result(
                    {"error": {"code": "invalid_arguments", "message": exc.message}},
                    True,
                )
            else:
                path = row["path"].format(
                    **{key: quote(arguments[key], safe="") for key in row["path_keys"]}
                )
                body = {
                    key: value
                    for key, value in arguments.items()
                    if key not in row["path_keys"]
                }
                headers = dict(row.get("headers", {}))
                for key, header in row.get("header_arguments", {}).items():
                    if key in body:
                        headers[header] = body.pop(key)
                options = {"params": {key: value for key, value in body.items() if value is not None}} if row["method"] == "GET" else {"json": body}
                if headers: options["headers"] = headers
                try:
                    async with self.client.stream(
                        row["method"], path, **options
                    ) as response:
                        if response.is_success and row.get("export"):
                            payload = await read_download(response, MAX_EXPORT_INLINE_BYTES, MAX_MESSAGE_BYTES)
                        elif response.status_code == 204:
                            payload = result({"ok": True})
                        else:
                            raw = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                                if len(raw) + len(chunk) > MAX_MESSAGE_BYTES:
                                    raise ValueError("Result exceeds the MCP message limit; use result_page, query_table_page or an export tool")
                                raw.extend(chunk)
                            value = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid API JSON")))
                            payload = result(value, not response.is_success)
                except httpx.HTTPError:
                    payload = result({"error": {"code": "api_failure", "message": "The GraphMine API request failed. Check the connection and inspect existing jobs before retrying a submission."}}, True)
                except ValueError as exc:
                    payload = result(
                        {"error": {"code": "api_failure", "message": str(exc)}}, True
                    )
        else:
            return error(-32601, "Method not found")
        response = {"jsonrpc": "2.0", "id": identifier, "result": payload}
        if len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode()) > MAX_MESSAGE_BYTES:
            response["result"] = result({"error": {"code": "message_limit", "message": "Result exceeds the MCP message limit; use result_page, query_table_page or an export tool."}}, True)
        return response


async def serve():
    headers = {}
    if token := os.getenv("GRAPHMINE_API_TOKEN"):
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(
        base_url=os.getenv("GRAPHMINE_API_URL", "http://127.0.0.1:8000"),
        headers=headers,
        timeout=400,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        bridge = Bridge(client)
        while raw := await asyncio.to_thread(
            sys.stdin.buffer.readline, MAX_MESSAGE_BYTES + 1
        ):
            if len(raw) > MAX_MESSAGE_BYTES:
                # Do not interpret a fragment of an oversized request as a new message.
                print("MCP request exceeds the message limit", file=sys.stderr)
                return
            try:
                request = json.loads(
                    raw,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(value)
                    ),
                )
                response = await bridge.handle(request)
            except (ValueError, UnicodeError, RecursionError):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Invalid JSON"},
                }
            if response is not None:
                print(
                    json.dumps(response, ensure_ascii=False, allow_nan=False),
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(serve())
