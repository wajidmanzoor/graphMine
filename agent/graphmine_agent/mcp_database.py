"""Database MCP tools use the existing API models and authenticated routes."""

from copy import deepcopy
import string
from typing import Literal

from pydantic import Field

from .connectors import ImportConnector
from .database_enrichment import EnrichmentRequest
from .database_queries import CypherRequest, OpenChat
from .database_sources import Strict
from .datasets import SaveDataset
from .models import SessionCreate


class QuerySnapshot(CypherRequest):
    request_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$", description="Unique key for this query submission. Reuse it only to recover the same request after a lost response.")


class DatasetPage(Strict):
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=20, ge=1, le=100)
    q: str = Field(default="", max_length=200)
    kind: Literal["graph", "graph_collection", "feature_vectors", "hypergraph", "table"] | None = None
    latest: bool = False


class JobPage(Strict):
    source_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["query", "sync"] | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class DatasetSchema(Strict):
    dataset_id: str = Field(default="default", min_length=1, max_length=128)


class TableSort(Strict):
    sort: str | None = Field(default=None, max_length=20_000)
    direction: Literal["asc", "desc"] = "asc"


class TablePage(TableSort):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class TableExport(TableSort):
    format: Literal["csv", "json"]


class ReviewedExport(Strict):
    expected_revision: int = Field(ge=1, description="Revision of the saved workflow being exported; a changed revision returns a conflict.")


def tool(name, method, path, model, description, *, read_only=None, destructive=False, open_world=False, **transport):
    schema = deepcopy(model.model_json_schema()) if model else {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    path_keys = [field for _, field, _, _ in string.Formatter().parse(path) if field]
    for key in path_keys:
        schema["properties"].setdefault(key, {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,128}$"})
        if key not in schema.setdefault("required", []):
            schema["required"].append(key)
    return {"definition": {"name": name, "description": description, "inputSchema": schema,
                           "annotations": {"readOnlyHint": method == "GET" if read_only is None else read_only,
                                           "destructiveHint": destructive, "openWorldHint": open_world}},
            "method": method, "path": path, "path_keys": path_keys, **transport}


def database_tools():
    rows = [
        tool("discover_sources", "GET", "/api/data-sources", None,
             "List authorized Neo4j, SQLite and REST connections, their capabilities and discovery warnings. Use source_id with the provider's tools; credentials are omitted."),
        tool("database_source", "GET", "/api/database-sources/{source_id}", None,
             "Inspect one authorized graph connection's mappings, revision and available operations."),
        tool("database_datasets", "GET", "/api/database-sources/{source_id}/datasets", None,
             "Discover the default graph and available SQL catalog datasets for a connection.", open_world=True),
        tool("database_schema", "GET", "/api/database-sources/{source_id}/schema", DatasetSchema,
             "Inspect mapped or sampled graph schema for a dataset. Sample limits and incompleteness remain explicit.", open_world=True),
        tool("query_database", "POST", "/api/database-sources/{source_id}/queries", QuerySnapshot,
             "Submit a read-only Cypher query as a durable job. Poll database_job, then read database_job_result for its immutable graph/table snapshot. Save or open temporary snapshots to retain them. Does not execute an analysis.",
             open_world=True, headers={"Prefer": "respond-async"}, header_arguments={"request_key": "Idempotency-Key"}),
        tool("list_database_jobs", "GET", "/api/database-jobs", JobPage,
             "Page the owner's queued or running database work, optionally by source and kind. Finished jobs are not listed or stored as history."),
        tool("database_job", "GET", "/api/database-jobs/{identifier}", None,
             "Inspect active query or synchronization work and its cancellation boundary; finished status is available in memory for five minutes."),
        tool("database_job_result", "GET", "/api/database-jobs/{identifier}/result", None,
             "Collect a completed query snapshot or synchronization summary within five minutes, before its memory-only delivery record expires. Graph/row samples disclose their limits; use query_table_page for complete scalar rows."),
        tool("cancel_database_job", "DELETE", "/api/database-jobs/{identifier}", None,
             "Request cancellation of owned database work before its commit boundary. Poll until cancellation/rollback finishes; closing the client alone does not cancel it.", destructive=True),
        tool("save_query_snapshot", "POST", "/api/database-query-snapshots/{version_id}/save", None,
             "Retain an immutable graph or table preview in the private dataset library before its expiry."),
        tool("discard_query_snapshot", "DELETE", "/api/database-query-snapshots/{version_id}", None,
             "Discard an unused temporary preview. Saved or consumed inputs cannot be discarded by this action.", destructive=True),
        tool("open_query_snapshot", "POST", "/api/database-query-snapshots/{version_id}/chat", OpenChat,
             "Retain a query snapshot and open its exact input in a new conversation. Does not run an algorithm."),
        tool("list_datasets", "GET", "/api/datasets/page", DatasetPage,
             "Search and page lightweight summaries of the owner's saved datasets. Use dataset_provenance for complete source details."),
        tool("dataset_provenance", "GET", "/api/datasets/{version_id}/provenance", None,
             "Read an authorized immutable dataset's source, query, content hash and completeness."),
        tool("save_dataset", "POST", "/api/datasets", SaveDataset,
             "Save an existing input or an exact reviewed result revision as an immutable reusable dataset."),
        tool("import_dataset", "POST", "/api/sessions/{session_id}/datasets/{version_id}/import", None,
             "Copy a saved dataset version into an owned conversation, preserving its content and provenance."),
        tool("open_dataset", "POST", "/api/datasets/{version_id}/chat", SessionCreate,
             "Open an authorized saved dataset in a new conversation without querying its source or running an analysis."),
        tool("delete_dataset", "DELETE", "/api/datasets/{version_id}", None,
             "Delete an owned dataset-library version. Inputs already copied into conversations remain independent.", destructive=True),
        tool("file_source_schema", "GET", "/api/files/{file_id}/source-schema", None,
             "Inspect the authorized SQL mapping and fetched time behind a saved graph input. Changed source mappings return a conflict."),
        tool("enrich_file", "POST", "/api/files/{file_id}/enrichments", EnrichmentRequest,
             "Fetch selected mapped SQL attributes into a new graph version with timestamp and lineage. Earlier analysis inputs and scores remain unchanged.", open_world=True),
        tool("expand_file", "POST", "/api/files/{file_id}/expansions", EnrichmentRequest,
             "Fetch selected mapped SQL relationships into a new graph version. Does not mutate Neo4j or earlier saved inputs.", open_world=True),
        tool("query_table_page", "GET", "/api/database-query-snapshots/{identifier}/table", TablePage,
             "Page or sort all stored scalar query rows with exact types, total count and completeness, without rerunning Cypher."),
        tool("export_query_table", "GET", "/api/database-query-snapshots/{identifier}/table/{format}", TableExport,
             "Export every stored table row as CSV or JSON. CSV escapes spreadsheet formulas. Small exports are embedded; large exports return an authenticated download link.", export=True),
        tool("export_workflow_result", "GET", "/api/workflows/{workflow_id}/result", ReviewedExport,
             "Export the complete saved JSON result at the reviewed revision, with provenance. Large exports return an authenticated download link.", export=True),
        tool("export_result_csv", "GET", "/api/workflows/{workflow_id}/steps/{step}/ports/{port}/csv", ReviewedExport,
             "Export every row of a saved result port at the reviewed revision as CSV, without recomputation.", export=True),
        tool("export_workflow_report", "GET", "/api/workflows/{workflow_id}/report", ReviewedExport,
             "Export the saved report ZIP, including inputs, results and evidence, at the reviewed revision. Large exports return an authenticated download link.", export=True),
        tool("preview_connector", "POST", "/api/connectors/{connector_id}/preview", None,
             "Preview an authorized SQLite or REST graph import and obtain its exact content fingerprint and scope before importing.", read_only=True, open_world=True),
        tool("import_connector", "POST", "/api/connectors/{connector_id}/import", ImportConnector,
             "Save the exact previewed connector content as a private dataset using expected_sha256. Changed source content requires a new preview.", open_world=True),
    ]
    return {row["definition"]["name"]: row for row in rows}
