"""Compile schema choices into bounded, parameterized, inspectable read queries."""

import math
from typing import Any, Literal

from fastapi import Query, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .benchmark_mappings import resolve_source
from .database_datasets import selected_dataset
from .database_sources import Strict, get_source, validate_cypher


class GraphFilter(Strict):
    scope: Literal["source", "target", "relationship"] = "source"
    property: str = Field(min_length=1, max_length=128)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "starts_with", "is_null", "not_null"] = "eq"
    value: Any = None


class GraphBuild(Strict):
    dataset_id: str = Field(default="default", min_length=1, max_length=128)
    source_entity: str = Field(min_length=1, max_length=256)
    relationship: str | None = Field(default=None, max_length=256)
    target_entity: str | None = Field(default=None, max_length=256)
    match_direction: Literal["outgoing", "incoming", "either"] = "outgoing"
    directed: bool = True
    weight_property: str | None = Field(default=None, min_length=1, max_length=128)
    filters: list[GraphFilter] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=1000, ge=1, le=100_000)


def builder_schema(settings, source_id, dataset_id):
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
            raise AnalyticsError("The connection changed. Reload its graph choices.", "source_changed", 409)
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


def compile_query(schema, body):
    def fail(message):
        raise AnalyticsError(message, "graph_builder")

    def find(items, identifier, name):
        value = next((item for item in items if item["id"] == identifier), None)
        if value is None:
            fail(f"Choose a {name} from the selected dataset.")
        return value

    def quoted(identifier):
        return "`" + identifier.replace("`", "``") + "`"

    source = find(schema["entities"], body.source_entity, "source entity")
    relation = find(schema["relationships"], body.relationship, "relationship") if body.relationship else None
    target = find(schema["entities"], body.target_entity, "target entity") if relation else None
    if not relation and (body.target_entity or body.weight_property):
        fail("Choose a relationship before selecting an endpoint or edge weight.")
    if relation and relation.get("source_entity") and relation.get("target_entity"):
        forward = (source["id"], target["id"]) == (relation["source_entity"], relation["target_entity"])
        reverse = (source["id"], target["id"]) == (relation["target_entity"], relation["source_entity"])
        if not {"outgoing": forward, "incoming": reverse, "either": forward or reverse}[body.match_direction]:
            fail("These entity types do not match the selected relationship and direction.")
    if body.limit > schema["max_rows"]:
        fail(f"Use a row limit no greater than {schema['max_rows']} for this connection.")
    params, clauses = {"row_limit": body.limit}, []
    items = {"source": ("a", source), "target": ("b", target), "relationship": ("r", relation)}
    for alias, item in items.values():
        if item and item.get("mapping_id"):
            params["source_id"] = schema["source_id"]
            params[f"mapping_{alias}"] = item["mapping_id"]
            clauses.append(f"{alias}.gm_source = $source_id AND {alias}.gm_mapping = $mapping_{alias}")

    def node_pattern(alias, entity):
        return f"({alias}:{quoted(entity['label'])})"

    pattern = node_pattern("a", source)
    if relation:
        left, right = {"outgoing": ("-", "->"), "incoming": ("<-", "-"), "either": ("-", "-")}[body.match_direction]
        pattern = "p = " + pattern + left + f"[r:{quoted(relation['label'])}]" + right + node_pattern("b", target)
    for index, condition in enumerate(body.filters):
        alias, item = items[condition.scope]
        if not item or condition.property not in {p["name"] for p in item["properties"]}:
            fail("Choose a filter property available on the selected graph element.")
        prop = f"{alias}.{quoted(condition.property)}"
        if condition.operator in {"is_null", "not_null"}:
            clauses.append(prop + (" IS NULL" if condition.operator == "is_null" else " IS NOT NULL"))
            continue
        value = condition.value
        if type(value) not in (str, int, float, bool) or isinstance(value, float) and not math.isfinite(value):
            fail("Filter values must be text, numbers or booleans. Use 'is missing' for null.")
        if isinstance(value, str) and len(value) > 8000:
            fail("Filter text exceeds 8,000 characters.")
        if condition.operator in {"contains", "starts_with"} and not isinstance(value, str):
            fail("Text filters require a text value.")
        operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "CONTAINS", "starts_with": "STARTS WITH"}[condition.operator]
        params[f"filter_{index}"] = value
        clauses.append(f"{prop} {operator} $filter_{index}")
    if body.weight_property and body.weight_property not in {p["name"] for p in relation["properties"]}:
        fail("Choose an edge weight property from the selected relationship.")
    lines = ["MATCH " + pattern]
    if clauses:
        lines.append("WHERE " + "\n  AND ".join(clauses))
    # DISTINCT avoids matching the same relationship twice for undirected
    # traversal while preserving actual relationship identity and orientation.
    lines.extend(["RETURN DISTINCT r" if relation and body.match_direction == "either" else "RETURN p" if relation else "RETURN a", "LIMIT $row_limit"])
    statement = "\n".join(lines)
    validate_cypher(statement)
    return {"statement": statement, "parameters": params, "dataset_id": body.dataset_id,
            "directed": body.directed, "projection": "elements", "weight_property": body.weight_property,
            "description": f"Up to {body.limit:,} matching {'relationships and their endpoints' if relation else 'nodes'}. "
            + ("Original relationship direction is preserved." if body.directed else "Analysis treats relationships as undirected.")}


def register_builder_routes(router):
    async def schema(request, source_id, dataset_id):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(builder_schema, runtime.settings, source_id, dataset_id)

    @router.get("/database-sources/{source_id}/graph-builder")
    async def describe(source_id: str, request: Request, dataset_id: str = Query(default="default", max_length=128)):
        return await schema(request, source_id, dataset_id)

    @router.post("/database-sources/{source_id}/graph-builder")
    async def build(source_id: str, body: GraphBuild, request: Request):
        return compile_query(await schema(request, source_id, body.dataset_id), body)
