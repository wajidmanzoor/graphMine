"""MCP database tools exercise the same authorization and immutable API paths."""

import asyncio
import base64
import csv
import hashlib
import io
import json
import time
import zipfile
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import jsonschema
import pytest

from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.mcp import Bridge, tools
from test_connectors import sources  # noqa: F401
from test_database_workspace import documents, source, workspace  # noqa: F401
from test_query_tables import query_table
from test_workflow_templates import recipes  # noqa: F401


@asynccontextmanager
async def bridge_for(web, headers):
    def transport(request):
        # An absent bridge credential must not inherit a TestClient default.
        forwarded = {**dict(request.headers), "authorization": request.headers.get("authorization", "")}
        response = web.request(request.method, request.url.raw_path.decode(), content=request.content, headers=forwarded)
        # TestClient exposes decoded bytes; don't tell the next client to decode again.
        return httpx.Response(response.status_code, content=response.content, headers={key: value for key, value in response.headers.items() if key not in {"content-encoding", "content-length"}})
    async with httpx.AsyncClient(base_url="http://testserver", transport=httpx.MockTransport(transport), headers=headers) as client:
        bridge = Bridge(client); bridge.initialized = bridge.ready = True
        yield bridge


async def call(bridge, tool_name, **arguments):
    response = await bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}})
    assert "error" not in response, response
    return response["result"]


async def value(bridge, tool_name, **arguments):
    response = await call(bridge, tool_name, **arguments)
    assert not response["isError"], response
    return response["structuredContent"]


async def completed(bridge, identifier):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = await value(bridge, "database_job", identifier=identifier)
        if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            assert job["status"] == "completed", job
            return await value(bridge, "database_job_result", identifier=identifier)
        await asyncio.sleep(.01)
    pytest.fail("MCP query job did not finish")


def test_catalog_validates_all_schemas_and_describes_mutations_and_revision_checks():
    catalog = tools()
    for row in catalog.values():
        jsonschema.Draft202012Validator.check_schema(row["definition"]["inputSchema"])
    assert {"discover_sources", "database_schema", "query_database", "database_job", "save_query_snapshot", "query_table_page", "enrich_file", "expand_file", "export_query_table", "export_workflow_report", "import_connector"} <= catalog.keys()
    for name in ("cancel_database_job", "discard_query_snapshot", "delete_dataset"):
        assert catalog[name]["definition"]["annotations"]["destructiveHint"]
    assert catalog["build_graph_query"]["definition"]["annotations"]["readOnlyHint"]
    assert not catalog["query_database"]["definition"]["annotations"]["readOnlyHint"]
    assert "request_key" in catalog["query_database"]["definition"]["inputSchema"]["required"]
    for name in ("export_workflow_result", "export_result_csv", "export_workflow_report"):
        assert "expected_revision" in catalog[name]["definition"]["inputSchema"]["required"]


@pytest.mark.asyncio
async def test_graph_query_job_is_idempotent_and_snapshots_can_be_retained_and_reused(workspace):
    async with bridge_for(workspace.client, {"Authorization": "Bearer test-secret"}) as bridge:
        inventory = await value(bridge, "discover_sources")
        assert inventory["items"][0]["source_id"] == "demo" and inventory["items"][0]["capabilities"]["cypher"]
        assert "TEST_NEO4J_PASSWORD" not in json.dumps(inventory)
        source = await value(bridge, "database_source", source_id="demo")
        assert source["entities"][0]["label"] == "Account"
        assert (await value(bridge, "database_datasets", source_id="demo"))["items"][0]["id"] == "default"
        schema = await value(bridge, "database_schema", source_id="demo")
        assert schema["entities"]
        built = await value(bridge, "build_graph_query", source_id="demo", source_entity="accounts")
        assert built["statement"] and len(workspace.calls) == 1
        arguments = {"source_id": "demo", "statement": "MATCH (n) RETURN n", "parameters": {"exact": 9007199254740993}, "request_key": "mcp-query-1"}
        first = await value(bridge, "query_database", **arguments)
        again = await value(bridge, "query_database", **arguments)
        assert first["job"]["id"] == again["job"]["id"]
        result = await completed(bridge, first["job"]["id"])
        assert len(workspace.calls) == 2
        identifier = result["dataset"]["id"]
        assert result["dataset"]["temporary"]
        saved = await value(bridge, "save_query_snapshot", version_id=identifier)
        assert saved["id"] == identifier and not saved.get("temporary")
        provenance = await value(bridge, "dataset_provenance", version_id=identifier)
        assert provenance["source"]["parameters"]["exact"] == 9007199254740993
        original = DatasetLibrary(workspace.runtime).get(identifier, content=True)
        opened = await value(bridge, "open_dataset", version_id=identifier)
        copied = await value(bridge, "import_dataset", version_id=identifier, session_id=workspace.session["id"])
        assert opened["file"]["sha256"] == copied["file"]["sha256"] == original[0]["sha256"]
        assert DatasetLibrary(workspace.runtime).get(identifier, content=True) == original and len(workspace.calls) == 2
        page = await value(bridge, "list_datasets", limit=1, latest=True, kind=None)
        assert len(page["items"]) == 1
        jobs = await value(bridge, "list_database_jobs", source_id="demo", kind="query")
        assert len(jobs["items"]) == 1
        detail = await value(bridge, "database_job", identifier=first["job"]["id"])
        assert detail["query"]["parameters"]["exact"] == 9007199254740993
        conflict = await call(bridge, "query_database", **{**arguments, "statement": "MATCH (m) RETURN m"})
        assert conflict["isError"]
        bridge.client.headers.pop("Authorization")
        assert (await call(bridge, "database_job", identifier=first["job"]["id"]))["isError"]


@pytest.mark.asyncio
async def test_table_paging_and_exports_preserve_all_types_without_querying_again(workspace, monkeypatch):
    table = query_table(workspace, monkeypatch)["table"]
    def forbidden(*_): raise AssertionError("Stored table access cannot rerun the query")
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", forbidden)
    async with bridge_for(workspace.client, {"Authorization": "Bearer test-secret"}) as bridge:
        page = await value(bridge, "query_table_page", identifier=table["id"], offset=100, limit=50)
        assert len(page["rows"]) == 25 and page["rows"][0]["source"] == 9007199254741093 and page["complete"]
        exported = await call(bridge, "export_query_table", identifier=table["id"], format="csv", sort="amount", direction="desc")
        assert not exported["isError"] and exported["structuredContent"]["embedded"]
        raw = exported["content"][1]["resource"]["text"].encode()
        assert hashlib.sha256(raw).hexdigest() == exported["structuredContent"]["sha256"]
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        assert len(rows) == 125 and rows[-1]["note"] == "'=1+1" and rows[0]["source"] == "9007199254741117"
        exported = await call(bridge, "export_query_table", identifier=table["id"], format="json")
        parsed = json.loads(exported["content"][1]["resource"]["text"])
        assert parsed["rows"][0]["source"] == 9007199254740993 and parsed["rows"][0]["optional"] is None
        assert parsed["rows"][0]["active"] is True and parsed["rows"][0]["target"] == "000"
        monkeypatch.setattr("graphmine_agent.mcp.MAX_EXPORT_INLINE_BYTES", 128)
        linked = await call(bridge, "export_query_table", identifier=table["id"], format="json")
        assert not linked["structuredContent"]["embedded"] and linked["content"][1]["type"] == "resource_link"
        downloaded = workspace.client.get(linked["structuredContent"]["download_uri"])
        assert downloaded.json() == parsed


@pytest.mark.asyncio
async def test_enrichment_and_expansion_create_new_inputs_and_mapping_changes_fail(workspace):
    identifier = workspace.file["id"]
    before = workspace.runtime.graph_store.read_graph(identifier, workspace.session["id"])
    async with bridge_for(workspace.client, {"Authorization": "Bearer test-secret"}) as bridge:
        schema = await value(bridge, "file_source_schema", file_id=identifier)
        assert schema["fetched_at"] and schema["entities"][0]["id"] == "accounts"
        enriched = await value(bridge, "enrich_file", file_id=identifier, mapping="accounts", fields=["risk"])
        assert sorted(row["attributes"]["risk"] for row in enriched["updates"]) == [2, 9] and enriched["file"]["id"] != identifier
        expanded = await value(bridge, "expand_file", file_id=identifier, mapping="transfers")
        assert expanded["added"]["edges"] == 1 and expanded["dataset"]["source"]["type"] == "database_expansion"
        assert workspace.runtime.graph_store.read_graph(identifier, workspace.session["id"]) == before
        config = json.loads(workspace.config.read_text()); config[0]["revision"] += 1; workspace.config.write_text(json.dumps(config))
        failed = await call(bridge, "enrich_file", file_id=identifier, mapping="accounts", fields=["risk"])
        assert failed["isError"] and failed["structuredContent"]["error"]["code"] == "source_changed"


@pytest.mark.asyncio
async def test_query_write_rejection_and_queued_cancellation_keep_the_native_api_boundary(workspace):
    workspace.client.portal.call(workspace.runtime.database_jobs.stop)
    async with bridge_for(workspace.client, {"Authorization": "Bearer test-secret"}) as bridge:
        refused = await call(bridge, "query_database", source_id="demo", statement="MATCH (n) DELETE n", request_key="write-rejected")
        assert refused["isError"] and len(workspace.calls) == 1
        job = (await value(bridge, "query_database", source_id="demo", statement="RETURN 1", request_key="queued"))["job"]
        assert job["status"] == "queued"
        stopped = await value(bridge, "cancel_database_job", identifier=job["id"])
        assert stopped["status"] == "cancelled" and len(workspace.calls) == 1


@pytest.mark.asyncio
async def test_unused_preview_discard_handles_204_and_does_not_remove_saved_inputs(workspace):
    async with bridge_for(workspace.client, {"Authorization": "Bearer test-secret"}) as bridge:
        job = (await value(bridge, "query_database", source_id="demo", statement="RETURN 1", request_key="discard"))["job"]
        snapshot = (await completed(bridge, job["id"]))["dataset"]
        assert await value(bridge, "discard_query_snapshot", version_id=snapshot["id"]) == {"ok": True}
        assert (await call(bridge, "dataset_provenance", version_id=snapshot["id"]))["isError"]
        retained_id = workspace.snapshot["dataset"]["id"]
        retained = DatasetLibrary(workspace.runtime).get(retained_id, content=True)
        assert await value(bridge, "discard_query_snapshot", version_id=retained_id) == {"ok": True}
        assert DatasetLibrary(workspace.runtime).get(retained_id, content=True) == retained


@pytest.mark.asyncio
async def test_private_database_jobs_and_snapshots_enforce_owner_and_token_revocation(sources, source, tmp_path, monkeypatch):
    web, runtime, alice, bob, _, _, _ = sources
    config = tmp_path/"mcp-sources.json"
    config.write_text(json.dumps([{**source.model_dump(), "users": ["alice"]}]))
    config.chmod(0o600)
    runtime.settings = replace(runtime.settings, database_sources_file=config)
    graph, lineage = documents(source)
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", lambda *_: (graph, lineage, [], 1, None))
    async with bridge_for(web, alice) as bridge:
        first = await value(bridge, "query_database", source_id="demo", statement="MATCH (n) RETURN n", request_key="private-query")
        identifier = first["job"]["id"]
        snapshot = (await completed(bridge, identifier))["dataset"]["id"]
        await value(bridge, "save_query_snapshot", version_id=snapshot)
        bridge.client.headers.update(bob)
        assert not (await value(bridge, "list_database_jobs"))["items"]
        assert not (await value(bridge, "list_datasets"))["items"]
        for name, arguments in [("database_source", {"source_id": "demo"}), ("database_job", {"identifier": identifier}),
                                ("database_job_result", {"identifier": identifier}), ("cancel_database_job", {"identifier": identifier}),
                                ("save_query_snapshot", {"version_id": snapshot}), ("open_query_snapshot", {"version_id": snapshot}),
                                ("dataset_provenance", {"version_id": snapshot})]:
            denied = await call(bridge, name, **arguments)
            assert denied["isError"]
        bridge.client.headers.update(alice)
        assert (await value(bridge, "database_job", identifier=identifier))["status"] == "completed"
        runtime.accounts.logout(runtime.accounts.authenticate(alice["Authorization"].removeprefix("Bearer ")))
        assert (await call(bridge, "database_job_result", identifier=identifier))["isError"]


@pytest.mark.asyncio
async def test_connector_to_dataset_workflow_is_private_and_checks_preview_fingerprint(sources):
    web, runtime, alice, bob, _, _, database = sources
    before = database.read_bytes()
    async with bridge_for(web, alice) as bridge:
        assert (await value(bridge, "discover_sources"))["items"][0]["id"] == "connector:ledger"
        preview = await value(bridge, "preview_connector", connector_id="ledger")
        assert [node["id"] for node in preview["vertices"]] == ["001", "1", 1, 9007199254740993]
        wrong = await call(bridge, "import_connector", connector_id="ledger", name="Ledger", expected_sha256="0"*64)
        assert wrong["isError"]
        saved = await value(bridge, "import_connector", connector_id="ledger", name="Ledger", expected_sha256=preview["sha256"])
        opened = await value(bridge, "open_dataset", version_id=saved["id"])
        assert opened["file"]["sha256"] == saved["sha256"] and database.read_bytes() == before
        second = await value(bridge, "save_dataset", file_id=opened["file"]["id"], name="Retained ledger")
        assert second["sha256"] == saved["sha256"]
        bridge.client.headers.update(bob)
        assert not (await value(bridge, "discover_sources"))["items"]
        assert not (await value(bridge, "list_datasets"))["items"]
        for name, arguments in [("preview_connector", {"connector_id": "ledger"}), ("dataset_provenance", {"version_id": saved["id"]}),
                                ("open_dataset", {"version_id": saved["id"]}), ("delete_dataset", {"version_id": saved["id"]})]:
            assert (await call(bridge, name, **arguments))["isError"]
        bridge.client.headers.update(alice)
        assert await value(bridge, "delete_dataset", version_id=second["id"]) == {"ok": True}


@pytest.mark.asyncio
async def test_workflow_exports_check_owner_and_reviewed_revision_and_keep_evidence(recipes):
    web, runtime, alice, bob, _, file, record, saved = recipes
    directory = runtime.analytics._directory(record)
    graph = runtime.graph_store.read_graph(file["id"], record["session_id"])
    runtime.analytics._write(directory/"inputs.json", {"main": {"kind": "graph", "data": graph}})
    runtime.analytics._write(directory/"step-core.json", saved["steps"]["core"])
    async with bridge_for(web, alice) as bridge:
        exported = await call(bridge, "export_workflow_report", workflow_id=record["id"], expected_revision=1)
        assert not exported["isError"], exported
        raw = base64.b64decode(exported["content"][1]["resource"]["blob"])
        assert hashlib.sha256(raw).hexdigest() == exported["structuredContent"]["sha256"]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert json.loads(archive.read("result.json")) == saved
            assert json.loads(archive.read("inputs.json"))["main"]["data"] == graph
        exact = await call(bridge, "export_workflow_result", workflow_id=record["id"], expected_revision=1)
        assert json.loads(exact["content"][1]["resource"]["text"]) == saved
        assert not (await call(bridge, "export_result_csv", workflow_id=record["id"], step="core", port="count", expected_revision=1))["isError"]
        for name, arguments in [("export_workflow_report", {}), ("export_workflow_result", {}), ("export_result_csv", {"step": "core", "port": "count"})]:
            conflict = await call(bridge, name, workflow_id=record["id"], expected_revision=2, **arguments)
            assert conflict["isError"] and conflict["structuredContent"]["error"]["code"] == "revision_conflict"
        bridge.client.headers.update(bob)
        denied = await call(bridge, "export_workflow_report", workflow_id=record["id"], expected_revision=1)
        assert denied["isError"] and all(item["type"] == "text" for item in denied["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [
    ("database_source", {"source_id": "../secrets"}),
    ("query_database", {"source_id": "demo", "statement": "RETURN 1", "request_key": "bad\nheader"}),
    ("query_database", {"source_id": "demo", "statement": "RETURN 1"}),
    ("query_table_page", {"identifier": "table", "limit": 501}),
    ("export_query_table", {"identifier": "table", "format": "../csv"}),
    ("export_workflow_report", {"workflow_id": "workflow"}),
    ("discover_sources", {"url": "https://outside.invalid"}),
    ("enrich_file", {"file_id": "file", "mapping": "accounts", "ids": [True]}),
])
async def test_invalid_tool_inputs_never_reach_http(name, arguments):
    def forbidden(_): raise AssertionError("Invalid arguments reached HTTP")
    async with httpx.AsyncClient(base_url="http://testserver", transport=httpx.MockTransport(forbidden)) as client:
        bridge = Bridge(client); bridge.initialized = bridge.ready = True
        response = await call(bridge, name, **arguments)
        assert response["isError"] and response["structuredContent"]["error"]["code"] == "invalid_arguments"


@pytest.mark.asyncio
@pytest.mark.parametrize("known_size", [False, True])
async def test_large_exports_return_credential_free_links_and_close_streams(monkeypatch, known_size):
    monkeypatch.setattr("graphmine_agent.mcp.MAX_EXPORT_INLINE_BYTES", 32_768)
    class Stream(httpx.AsyncByteStream):
        count = 0; closed = False
        async def __aiter__(self):
            for _ in range(100):
                self.count += 1; yield b"x"*65_536
        async def aclose(self): self.closed = True
    stream = Stream()
    def transport(_):
        return httpx.Response(200, headers={"Content-Type": "text/csv", **({"Content-Length": str(100*65_536)} if known_size else {})}, stream=stream)
    async with httpx.AsyncClient(base_url="https://user:private-password@graphmine.test", headers={"Authorization": "Bearer private-token"}, transport=httpx.MockTransport(transport)) as client:
        bridge = Bridge(client); bridge.initialized = bridge.ready = True
        response = await call(bridge, "export_query_table", identifier="table", format="csv")
        assert not response["isError"] and not response["structuredContent"]["embedded"]
        assert response["structuredContent"]["download_uri"] == "https://graphmine.test/api/database-query-snapshots/table/table/csv"
        assert response["content"][1]["type"] == "resource_link" and response["structuredContent"]["requires_authentication"]
        assert "private-password" not in json.dumps(response) and "private-token" not in json.dumps(response)
        assert stream.closed and stream.count <= 1


@pytest.mark.asyncio
async def test_output_limit_covers_structured_and_text_copies(monkeypatch):
    monkeypatch.setattr("graphmine_agent.mcp.MAX_MESSAGE_BYTES", 2048)
    def transport(_): return httpx.Response(200, json={"text": "x"*1200})
    async with httpx.AsyncClient(base_url="http://testserver", transport=httpx.MockTransport(transport)) as client:
        bridge = Bridge(client); bridge.initialized = bridge.ready = True
        response = await call(bridge, "database_source", source_id="demo")
        assert response["isError"] and response["structuredContent"]["error"]["code"] == "message_limit"
        assert len(json.dumps(response).encode()) < 2048


@pytest.mark.asyncio
async def test_transport_errors_do_not_echo_credentials_and_invalid_rpc_ids_are_bounded():
    def transport(_): raise httpx.ConnectError("Could not connect to https://user:secret@host?token=private")
    async with httpx.AsyncClient(base_url="http://testserver", transport=httpx.MockTransport(transport)) as client:
        bridge = Bridge(client); bridge.initialized = bridge.ready = True
        response = await call(bridge, "discover_sources")
        assert response["isError"] and response["structuredContent"]["error"]["code"] == "api_failure"
        assert "secret" not in json.dumps(response) and "private" not in json.dumps(response)
        for identifier in (["invalid"], "x"*2048):
            response = await bridge.handle({"jsonrpc": "2.0", "id": identifier, "method": "tools/list"})
            assert response["id"] is None and response["error"]["code"] == -32600
            assert len(json.dumps(response)) < 1024
