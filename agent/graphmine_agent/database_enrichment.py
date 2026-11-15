"""Source-backed attribute overlays and versioned relationship expansion."""

from __future__ import annotations

import copy
import json
from typing import Literal

from fastapi import Request
from pydantic import Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json, _key
from .database import RecordNotFound
from .database_sources import (
    RelationshipMapping,
    Strict,
    get_source,
    json_value,
    read_rows,
    sql_connection,
)
from .database_sync import mapped_records
from .datasets import DatasetLibrary
from .models import utc_now
from .result_views import focus_graph, input_graph, source_files
from .benchmark_mappings import resolve_source


class ResultSelection(Strict):
    workflow_id: str
    revision: int = Field(ge=1)
    step: str
    port: str
    index: int | None = Field(default=None, ge=0)


class EnrichmentRequest(Strict):
    mapping: str
    fields: list[str] = Field(default_factory=list, max_length=64)
    kind: Literal["vertices", "edges"] = "vertices"
    ids: list[StrictInt | StrictStr] | None = Field(default=None, max_length=5000)
    selection: ResultSelection | None = None


def source_context(runtime, file_id):
    file = runtime.database.get_file(file_id)
    runtime.database.get_session(file.session_id)
    provenance = file.provenance.get("source", {})
    descriptor = provenance.get("database_source", {})
    if not descriptor.get("id") or provenance.get("type") not in {
        "database_query",
        "database_enrichment",
        "database_expansion",
    }:
        raise AnalyticsError(
            "This input has no database source mapping.", "source_unavailable", 409
        )
    source = get_source(runtime.settings, descriptor["id"])
    source = resolve_source(runtime.settings, source, (provenance.get("database_dataset") or {}).get("id"))
    if descriptor.get("mapping_hash") != source.fingerprint():
        raise AnalyticsError(
            "The source mapping changed. Create a fresh query snapshot before enrichment.",
            "source_changed",
            409,
        )
    return file, source, provenance


def selected_graph(runtime, file, body):
    if body.selection:
        selection = body.selection
        service = runtime.analytics
        record = service.get(selection.workflow_id)
        roots = source_files(record, selection.step)
        ancestor = file
        seen = set()
        while ancestor.id not in roots and ancestor.id not in seen and len(seen) < 100:
            seen.add(ancestor.id)
            parent = ancestor.provenance.get("source", {}).get("parent_file_id")
            if not parent:
                break
            ancestor = runtime.database.get_file(parent)
            if ancestor.session_id != file.session_id:
                break
        if (
            record["session_id"] != file.session_id
            or ancestor.id not in roots
            or ancestor.session_id != file.session_id
        ):
            raise AnalyticsError(
                "The selected result does not use this source.", "invalid_selection"
            )
        if record["revision"] != selection.revision:
            raise AnalyticsError(
                "The selected analysis revision changed.", "revision_conflict", 409
            )
        result = service._saved(record["id"], step=selection.step)["result"]
        if body.selection.port not in result.get("ports", {}):
            raise AnalyticsError("Unknown result output.", "invalid_selection")
        graph, _, _, _ = focus_graph(
            input_graph(service, record, selection.step),
            result,
            selection.port,
            selection.index,
        )
        if (
            graph is None
            or result["ports"][selection.port]["type"] == "pattern_collection"
        ):
            raise AnalyticsError(
                "This output has no source-backed graph witness.", "source_unavailable"
            )
        graph = copy.deepcopy(graph)
        if file.id != ancestor.id:
            # Keep prior source lookups while preserving the selected result's
            # topology and weights. Expanded topology requires a new analysis.
            base = json.loads(
                runtime.graph_store.execution_path(file.id, file.session_id).read_text()
            )
            for kind in ("vertices", "edges"):
                attributes = {
                    _key(v["id"]): v.get("attributes", {}) for v in base[kind]
                }
                for item in graph[kind]:
                    item.setdefault("attributes", {}).update(
                        attributes.get(_key(item["id"]), {})
                    )
    else:
        path = runtime.graph_store.execution_path(file.id, file.session_id)
        graph = json.loads(path.read_text())
    return copy.deepcopy(graph)


def context(runtime, file_id, body):
    file, source, provenance = source_context(runtime, file_id)
    if source.sql_type is None:
        raise AnalyticsError("SQL enrichment is not configured for this connection. The saved graph remains available for analysis.", "sql_unavailable", 409)
    graph = selected_graph(runtime, file, body)
    known = {_key(item["id"]): item for item in graph[body.kind]}
    wanted = set(known) if body.ids is None else {_key(i) for i in body.ids}
    if not wanted.issubset(known):
        raise AnalyticsError(
            "Selection contains entities outside this graph.", "invalid_selection"
        )
    if len(wanted) > 5000:
        raise AnalyticsError(
            "Select at most 5,000 entities for source lookup.", "resource_limit"
        )
    links = provenance.get("lineage", {}).get(body.kind, {})
    selected = [
        (key, links[key])
        for key in wanted
        if key in links and links[key]["mapping"] == body.mapping
    ]
    if not selected:
        raise AnalyticsError(
            "No selected entity has a row mapping for this table.",
            "source_unavailable",
            409,
        )
    return file, source, provenance, graph, known, wanted, selected


def save_child(runtime, file, provenance, graph, kind, details):
    library = DatasetLibrary(runtime)
    metadata = library.store(
        graph,
        name=f"{provenance['database_source']['name']} · {kind}",
        kind="graph",
        complete=True,
        dataset_id=file.provenance.get("dataset_id"),
        source={
            **provenance,
            "type": f"database_{kind}",
            "parent_file_id": file.id,
            "fetched_at": utc_now().isoformat(),
            **details,
        },
    )
    try:
        imported = library.import_into(metadata["id"], file.session_id)
    except Exception:
        library.delete(metadata["id"])
        raise
    return {"dataset": metadata, **imported}


def enrich(runtime, file_id, body):
    file, source, provenance, graph, known, wanted, selected = context(
        runtime, file_id, body
    )
    mapping = source.mapping(body.mapping)
    if isinstance(mapping, RelationshipMapping) != (body.kind == "edges"):
        raise AnalyticsError(
            "Choose a mapping for this entity kind.", "database_mapping"
        )
    if not body.fields or any(field not in mapping.attributes for field in body.fields):
        raise AnalyticsError(
            "Choose fields exposed by this source mapping.", "database_mapping"
        )
    values = {}
    with sql_connection(source) as db:
        keys = list({_json(link["keys"]): link["keys"] for _, link in selected}.values())
        for offset in range(0, len(keys), 100):
            for row in read_rows(
                db,
                source,
                mapping,
                keys=keys[offset : offset + 100],
                fields=body.fields,
            ):
                key = _json(json_value([row[k] for k in mapping.key]))
                if key in values:
                    raise AnalyticsError("This source key matches multiple rows. Use a unique table mapping.", "database_mapping", 409)
                values[key] = row
    if source.fingerprint() != source_context(runtime, file_id)[1].fingerprint():
        raise AnalyticsError(
            "Source settings changed during lookup.", "source_changed", 409
        )
    changed, missing = [], []
    at = utc_now().isoformat()
    for key, link in selected:
        row = values.get(_json(link["keys"]))
        if row is None:
            missing.append(known[key]["id"])
            continue
        attributes = {field: json_value(row.get(field)) for field in body.fields}
        known[key].setdefault("attributes", {}).update(attributes)
        changed.append({"id": known[key]["id"], "attributes": attributes})
    response = save_child(
        runtime,
        file,
        provenance,
        graph,
        "enrichment",
        {
            "enrichment": {
                "kind": body.kind,
                "mapping": body.mapping,
                "fields": body.fields,
                "selection": body.selection.model_dump() if body.selection else None,
                "fetched_at": at,
                "missing": missing,
                "updated_ids": [row["id"] for row in changed],
            }
        },
    )
    return {
        **response,
        "updates": changed,
        "entity_kind": body.kind,
        "fetched_at": at,
        "missing": missing,
        "unmapped_count": len(wanted) - len(selected),
        "note": "Attributes reflect the source at lookup time. Saved analysis metrics retain their original graph version.",
    }


def canonical_records(source, nodes, edges):
    graph = {
        "graph": {
            "id": source.id,
            "directed": True,
            "allows_self_loops": True,
            "allows_parallel_edges": True,
        },
        "vertices": [],
        "edges": [],
    }
    lineage = {"vertices": {}, "edges": {}}
    for kind, rows in (("vertices", nodes), ("edges", edges)):
        for row in rows:
            props = row["properties"]
            value = {
                "id": props["gm_id"],
                "type": row.get("label", row.get("type")),
                "attributes": {
                    k: v for k, v in props.items() if not k.startswith("gm_")
                },
            }
            if kind == "edges":
                value.update(source=row["source"], target=row["target"])
                for name in ("weight", "timestamp"):
                    if "gm_" + name in props:
                        value[name] = props["gm_" + name]
            elif "gm_display" in props:
                value["label"] = props["gm_display"]
            graph[kind].append(value)
            lineage[kind][_key(value["id"])] = {
                "mapping": row["mapping"],
                "keys": json.loads(props["gm_key"]),
            }
    return graph, lineage


def expand(runtime, file_id, body):
    file, source, provenance = source_context(runtime, file_id)
    if body.kind != "vertices":
        raise AnalyticsError(
            "Choose vertices before expanding relationships.", "invalid_selection"
        )
    mapping = source.mapping(body.mapping)
    if not isinstance(mapping, RelationshipMapping):
        raise AnalyticsError("Choose a relationship mapping.", "database_mapping")
    graph = selected_graph(runtime, file, body)
    known = {_key(v["id"]) for v in graph["vertices"]}
    wanted = known if body.ids is None else {_key(v) for v in body.ids}
    if not wanted.issubset(known) or len(wanted) > 1000:
        raise AnalyticsError(
            "Select up to 1,000 vertices from this graph.", "invalid_selection"
        )
    links = provenance.get("lineage", {}).get("vertices", {})
    selected = [
        links[k]
        for k in wanted
        if k in links
        and links[k]["mapping"] in {mapping.source_entity, mapping.target_entity}
    ]
    if not selected:
        raise AnalyticsError(
            "No selected vertex is mapped to an endpoint table for this relationship.",
            "source_unavailable",
            409,
        )
    at = utc_now().isoformat()
    with sql_connection(source) as db:
        nodes, edges = mapped_records(
            source, db, at, relationship=mapping, selected=selected
        )
    added, lineage = canonical_records(source, nodes, edges)
    counts = {}
    for kind in ("vertices", "edges"):
        before = {_key(v["id"]): v for v in graph[kind]}
        counts[kind] = sum(_key(v["id"]) not in before for v in added[kind])
        for value in added[kind]:
            key = _key(value["id"])
            previous = before.get(key, {})
            before[key] = {
                **previous,
                **value,
                "attributes": {
                    **previous.get("attributes", {}),
                    **value.get("attributes", {}),
                },
            }
        graph[kind] = list(before.values())
        lineage[kind] = {**provenance.get("lineage", {}).get(kind, {}), **lineage[kind]}
    if len(_json(graph).encode()) > min(
        runtime.settings.analytics_max_input_bytes,
        runtime.settings.account_upload_bytes,
    ):
        raise AnalyticsError(
            "Expanded graph exceeds the input limit.", "resource_limit"
        )
    if source.fingerprint() != source_context(runtime, file_id)[1].fingerprint():
        raise AnalyticsError(
            "Source settings changed during expansion.", "source_changed", 409
        )
    return {
        **save_child(
            runtime,
            file,
            provenance,
            graph,
            "expansion",
            {
                "lineage": lineage,
                "expansion": {
                    "mapping": body.mapping,
                    "fetched_at": at,
                    "selection": body.selection.model_dump()
                    if body.selection
                    else None,
                    "added": counts,
                },
            },
        ),
        "added": counts,
        "fetched_at": at,
        "note": "A new graph version is ready. Run analysis on this version to compute updated metrics.",
    }


def register_database_enrichment_routes(router):
    @router.get("/files/{file_id}/source-schema")
    def schema(file_id: str, request: Request):
        _, source, provenance = source_context(request.app.state.runtime, file_id)
        return {
            **source.public(),
            "fetched_at": provenance.get("fetched_at"),
            "query": provenance.get("query"),
            "parameters": provenance.get("parameters", {}),
        }

    async def run(request, fn, file_id, body):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy.", "busy", 429)
        async with runtime.upload_slots:
            try:
                return await run_in_threadpool(fn, runtime, file_id, body)
            except (AnalyticsError, RecordNotFound):
                raise
            except Exception as exc:
                raise AnalyticsError(
                    "Source lookup failed. Check the connection and mapped columns.",
                    "database_lookup",
                    502,
                ) from exc

    @router.post("/files/{file_id}/enrichments", status_code=201)
    async def attributes(file_id: str, body: EnrichmentRequest, request: Request):
        return await run(request, enrich, file_id, body)

    @router.post("/files/{file_id}/expansions", status_code=201)
    async def relationships(file_id: str, body: EnrichmentRequest, request: Request):
        return await run(request, expand, file_id, body)
