"""Read-only mapped or sampled schema for a selected Neo4j dataset."""

from fastapi import Query, Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .benchmark_mappings import resolve_source
from .database_datasets import selected_dataset
from .database_sources import get_source


def describe_schema(settings, source_id, dataset_id):
    source = get_source(settings, source_id)
    dataset = selected_dataset(settings, source, dataset_id)
    mapped = resolve_source(settings, source, dataset_id)
    entities, relationships = [], []
    sampled = None
    if (dataset_id == "default" or dataset.get("registry")) and not mapped.entities:
        from .neo4j_schema import sample_schema

        sampled = sample_schema(mapped)
        entities, relationships = sampled["entities"], sampled["relationships"]
        if resolve_source(settings, get_source(settings, source_id), dataset_id).fingerprint() != mapped.fingerprint():
            raise AnalyticsError("The connection changed. Reload its schema.", "source_changed", 409)
    # Mappings expose only properties actually copied to Neo4j. SQL-only fields
    # remain available through enrichment, not as misleading query filters.
    for mappings, target in ((mapped.entities, entities), (mapped.relationships, relationships)):
        for mapping in mappings:
            properties = mapping.graph_attributes if mapping.graph_attributes is not None else mapping.attributes
            item = {"id": mapping.id, "label": mapping.label, "mapping_id": mapping.id,
                    "properties": [{"name": name, "type": ""} for name in properties]}
            if hasattr(mapping, "source_entity"):
                item.update(source_entity=mapping.source_entity, target_entity=mapping.target_entity)
            target.append(item)
    return {"source_id": source.id, "dataset_id": dataset_id, "graph_label": None,
            "mapping_hash": mapped.fingerprint(), "max_rows": source.max_rows,
            "entities": entities, "relationships": relationships,
            "message": "" if entities else "This connection has no graph schema yet. Use the Cypher editor or add a graph mapping.",
            **({"schema_scope": sampled["schema_scope"], "message": sampled["message"]} if sampled else {})}


def register_schema_routes(router):
    @router.get("/database-sources/{source_id}/schema")
    async def describe(source_id: str, request: Request, dataset_id: str = Query(default="default", max_length=128)):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(describe_schema, runtime.settings, source_id, dataset_id)
