"""Connection-scoped datasets from the verified instance registry."""

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .benchmark_datasets import describe
from .database import RecordNotFound
from .database_sources import get_source
from .neo4j_registry import ready_datasets


def default_dataset(source):
    return {
        "id": "default",
        "name": ("Transfers demo" if source.id == "local-transfers" else "Mapped graph") if source.entities else "Neo4j graph",
        "status": "ready", "graph_label": None, "schemas": [],
        "tables": [
            {"name": m.table, "kind": "relationships" if hasattr(m, "source_entity") else "nodes",
             "labels": [m.label], "columns": [{"name": c, "type": ""} for c in m.attributes]}
            for m in source.entities + source.relationships
        ],
        "default_query": ("MATCH p = (a:" + source.entities[0].label + ")-[r"
                          + (":" + source.relationships[0].label if source.relationships else "")
                          + "]->(b) RETURN p LIMIT 1000") if source.entities
                         else "MATCH p = (a)-[r]->(b) RETURN p LIMIT 1000",
    }


def datasets(settings, source):
    identifier = source._catalog.get("id") if source._catalog.get("registry") else None
    if identifier is None:
        return [default_dataset(source)]
    result = []
    for entry in ready_datasets(settings):
        if entry["id"] != identifier:
            continue
        if settings.benchmark_datasets_root:
            try:
                published = describe(settings, identifier)
                entry.update(schemas=published["schemas"], source_url=published["source_url"])
            except RecordNotFound:
                pass
        result.append(entry)
    return result


def selected_dataset(settings, source, identifier):
    if identifier == "default" and not source._catalog.get("registry"):
        return default_dataset(source)
    for item in datasets(settings, source):
        if item["id"] == identifier or identifier == "default" and source._catalog.get("registry"):
            if item["status"] != "ready":
                raise AnalyticsError("This dataset is not ready for graph queries yet.", "dataset_not_ready", 409)
            return item
    raise RecordNotFound("Dataset not found in this database connection")


def register_dataset_routes(router):
    @router.get("/database-sources/{source_id}/datasets")
    async def list_datasets(source_id: str, request: Request):
        runtime = request.app.state.runtime
        source = get_source(runtime.settings, source_id)
        # This reads bounded local registry/schema metadata only. A connection
        # health check or graph query must not prevent selecting its dataset.
        return await run_in_threadpool(datasets, runtime.settings, source)
