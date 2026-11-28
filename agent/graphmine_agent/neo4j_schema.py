"""Bounded, read-only graph schema samples without SQL or admin procedures."""

import hashlib

from .analytics import AnalyticsError, _json
from .database_sources import neo4j_read, neo4j_session


def diagram_schema(source):
    """Read all catalog labels, then bounded property samples per label/type.

    Neo4j's visualization procedure infers possible endpoint combinations from
    its catalog. Report that distinction instead of calling it exact topology.
    """
    def quote(name):
        return "`" + name.replace("`", "``") + "`"

    def properties(rows):
        return [{"name": name, "type": ""} for name in sorted({name for row in rows for name in row["properties"]
                 if isinstance(name, str) and len(name) <= 128 and not name.startswith(("gm_", "_gm_"))})][:128]

    def read(tx):
        rows = list(tx.run("CALL db.schema.visualization()", {}))
        if len(rows) != 1:
            raise ValueError("Schema metadata unavailable")
        nodes, edges = rows[0]["nodes"], rows[0]["relationships"]
        if len(nodes) > 128 or len(edges) > 512:
            raise AnalyticsError("This schema is too large for the diagram. Narrow the dataset scope.", "resource_limit")
        entities, relationships, identifiers, edge_properties = [], [], {}, {}
        for item in nodes:
            label = item.get("name")
            if not isinstance(label, str) or not label:
                raise ValueError("Invalid schema label")
            identity = "label:" + label
            identifiers[item.element_id] = identity
            props = properties(tx.run(f"MATCH (n:{quote(label)}) RETURN keys(n) AS properties LIMIT 8", {}))
            entities.append({"id": identity, "label": label, "properties": props})
        for i, item in enumerate(edges):
            if item.type not in edge_properties:
                edge_properties[item.type] = properties(tx.run(f"MATCH ()-[r:{quote(item.type)}]->() RETURN keys(r) AS properties LIMIT 8", {}))
            relationships.append({"id": f"schema-edge:{i}", "label": item.type,
                                  "source_entity": identifiers[item.start_node.element_id], "target_entity": identifiers[item.end_node.element_id],
                                  "properties": edge_properties[item.type]})
        result = {"entities": entities, "relationships": relationships,
                  "schema_scope": {"complete_labels": True, "sampled_properties": True, "inferred_relationships": True},
                  "message": "All catalog labels are shown. Properties are sampled per label and type; Neo4j infers the possible relationship patterns."}
        if len(_json(result).encode()) > 256 * 1024:
            raise AnalyticsError("Schema exceeds the diagram byte limit.", "resource_limit")
        return result
    try:
        with neo4j_session(source) as session:
            return neo4j_read(session, source, read, timeout=min(source.timeout_seconds, 15))
    except AnalyticsError:
        raise
    except Exception:
        result = sample_schema(source)
        result["message"] = "Full catalog access is unavailable. " + result["message"]
        return result


def sample_schema(source):
    limit = min(500, source.max_rows)
    entities, relationships = {}, {}
    used = 0

    def names(values):
        nonlocal used
        result = []
        for value in values:
            used += len(value.encode("utf-8")) if isinstance(value, str) else 0
            if used > min(source.max_bytes if source.max_bytes is not None else 256 * 1024, 256 * 1024):
                raise AnalyticsError("Graph schema exceeds the discovery byte limit. Use the Cypher editor to select a smaller scope.", "resource_limit")
            if isinstance(value, str) and value and len(value) <= 128 and not value.startswith(("gm_", "_gm_")):
                result.append(value)
        return result

    def node(label, properties=()):
        if label not in entities and len(entities) < 64:
            entities[label] = {"id": "label:" + label, "label": label, "properties": set()}
        value = entities.get(label)
        if value:
            value["properties"].update(properties[:max(0, 128 - len(value["properties"]))])
        return value

    def read(tx):
        nonlocal used
        entities.clear()
        relationships.clear()
        used = 0
        for index, row in enumerate(tx.run("MATCH (n) RETURN labels(n) AS labels, keys(n) AS properties LIMIT $limit", {"limit": limit})):
            if index >= limit:
                raise AnalyticsError("Graph schema exceeded its row limit.", "resource_limit")
            labels, properties = names(row["labels"]), names(row["properties"])
            for label in labels:
                node(label, properties)
        for index, row in enumerate(tx.run("MATCH (a)-[r]->(b) RETURN labels(a) AS source_labels, labels(b) AS target_labels, type(r) AS relationship, keys(r) AS properties LIMIT $limit", {"limit": limit})):
            if index >= limit:
                raise AnalyticsError("Graph schema exceeded its row limit.", "resource_limit")
            starts, ends = names(row["source_labels"]), names(row["target_labels"])
            labels, properties = names([row["relationship"]]), names(row["properties"])
            for start in starts:
                a = node(start)
                for end in ends:
                    b = node(end)
                    if not a or not b or not labels:
                        continue
                    key = (start, labels[0], end)
                    if key not in relationships and len(relationships) < 64:
                        relationships[key] = {"id": "relationship:" + hashlib.sha256(_json(key).encode()).hexdigest(),
                                              "label": labels[0], "source_entity": a["id"], "target_entity": b["id"], "properties": set()}
                    if key in relationships:
                        value = relationships[key]["properties"]
                        value.update(properties[:max(0, 128 - len(value))])

    try:
        with neo4j_session(source) as session:
            neo4j_read(session, source, read, timeout=min(source.timeout_seconds, 10))
    except AnalyticsError:
        raise
    except Exception as error:
        raise AnalyticsError("Neo4j schema could not be read. Check the connection or use the Cypher editor.", "database_schema", 502) from error
    def public(values):
        return [{**item, "properties": [{"name": name, "type": ""} for name in sorted(item["properties"])]} for item in values]
    return {"entities": public(entities[key] for key in sorted(entities)),
            "relationships": public(relationships[key] for key in sorted(relationships)),
            "schema_scope": {"sampled": True, "complete": False, "max_nodes": limit, "max_relationships": limit},
            "message": "Choices come from a bounded Neo4j sample and may omit labels, relationships or properties. Use the Cypher editor for other graph data."}
