"""Bounded keyed reconciliation of the graph records owned by a SQL source."""

import hashlib
import json
import re
from collections import defaultdict

from .analytics import AnalyticsError, _json
from .database_job_context import checkpoint
from .database_sources import json_value


def conflict(message="The managed graph changed during synchronization. Preview its current state before retrying."):
    return AnalyticsError(message, "database_sync_conflict", 409)


def quoted(value):
    return "`" + value.replace("`", "``") + "`"


def read_state(tx, source, byte_limit):
    """Read complete managed state or fail; never infer deletions from a sample."""
    nodes, edges = {}, {}
    count, used = 0, 0
    statements = (
        (nodes, "MATCH (n:GraphMineEntity {gm_source: $source}) RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties LIMIT $limit"),
        (edges, "MATCH (a)-[r]->(b) WHERE r.gm_source = $source RETURN elementId(r) AS element_id, type(r) AS type, properties(r) AS properties, a.gm_id AS source, b.gm_id AS target, a.gm_source AS source_owner, b.gm_source AS target_owner LIMIT $limit"),
    )
    for output, statement in statements:
        for row in tx.run(statement, source=source.id, limit=source.max_rows + 1):
            value = json_value(dict(row))
            count += 1; used += len(_json(value).encode())
            if count > source.max_rows or (byte_limit is not None and used > byte_limit):
                raise AnalyticsError("The existing managed graph exceeds the synchronization read budget. Increase the source limit before retrying.", "resource_limit")
            props = value["properties"]
            identifier = props.get("gm_id")
            if not isinstance(identifier, str) or not identifier or identifier in output or props.get("gm_source") != source.id:
                raise conflict("Managed graph keys are missing or duplicated. Repair the graph before synchronizing.")
            output[identifier] = value
            checkpoint("comparing", count)
    for edge in edges.values():
        if any(edge.get(name) not in nodes for name in ("source", "target")) or any(edge.get(name) != source.id for name in ("source_owner", "target_owner")):
            raise conflict("A managed relationship has an endpoint outside its source. Repair the graph before synchronizing.")
    return nodes, edges


def _properties(before, desired):
    # Legacy refresh owned every property. New records explicitly remember the
    # mapped fields so future mapping removals can retain unrelated annotations.
    fields = before.get("gm_fields", list(before))
    if not isinstance(fields, list) or any(not isinstance(key, str) for key in fields):
        raise conflict("Managed property metadata is invalid. Repair the graph before synchronizing.")
    fields = set(fields)
    after = {key: value for key, value in before.items() if key not in fields and not key.startswith("gm_")}
    after.update({key: value for key, value in desired.items() if value is not None})
    return after


def _same_properties(before, after):
    # gm_build is the last change time, not a reason to rewrite unchanged rows.
    def canonical(value):
        return json.dumps({key: item for key, item in value.items() if key != "gm_build"}, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return canonical(before) == canonical(after)


def plan_changes(source, nodes, edges, old_nodes, old_edges):
    changes = {kind: {action: [] for action in ("created", "updated", "deleted")} | {"unchanged": 0} for kind in ("nodes", "relationships")}
    wanted_nodes = {row["properties"]["gm_id"]: row for row in nodes}
    wanted_edges = {row["properties"]["gm_id"]: row for row in edges}
    for kind, desired, existing in (("nodes", wanted_nodes, old_nodes), ("relationships", wanted_edges, old_edges)):
        for identifier in sorted(existing.keys() - desired.keys()):
            changes[kind]["deleted"].append({"id": identifier, **existing[identifier]})
        for identifier, row in desired.items():
            before = existing.get(identifier)
            after = _properties(before["properties"] if before else {}, row["properties"])
            item = {**row, "id": identifier, "properties": after}
            if before is None:
                changes[kind]["created"].append(item); continue
            item["before"] = before
            if kind == "nodes":
                previous_label = before["properties"].get("gm_label")
                if previous_label is None:
                    labels = set(before["labels"]) - {"GraphMineEntity"}
                    previous_label = row["label"] if row["label"] in labels else next(iter(labels)) if len(labels) == 1 else None
                    if previous_label is None and labels:
                        raise conflict("A legacy node has ambiguous labels. Review its labels before changing the mapping.")
                if previous_label is not None and not isinstance(previous_label, str):
                    raise conflict("Managed label metadata is invalid.")
                item["remove_label"] = previous_label if previous_label and previous_label != row["label"] else None
                same_shape = row["label"] in before["labels"] and not item["remove_label"]
            else:
                same_shape = all(before[key] == row[key] for key in ("source", "target", "type"))
                item["recreated"] = not same_shape
            if same_shape and _same_properties(before["properties"], after):
                changes[kind]["unchanged"] += 1
            else:
                changes[kind]["updated"].append(item)
    return changes


def change_summary(source, changes, old_nodes, old_edges):
    counts = {kind: {action: values if action == "unchanged" else len(values) for action, values in problems.items()} for kind, problems in changes.items()}
    counts["relationships"]["recreated"] = sum(row["recreated"] for row in changes["relationships"]["updated"])
    hashes = set()
    for row in [*old_nodes.values(), *old_edges.values()]:
        value = row["properties"].get("gm_mapping_hash")
        hashes.add(value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) else "unrecorded")
    hashes = sorted(hashes)
    return {"changes": counts, "schema_change": {"changed": bool(hashes and hashes != [source.fingerprint()]),
            "previous_hashes": hashes[:16], "previous_hash_count": len(hashes), "previous_hashes_complete": len(hashes) <= 16,
            "mapping_hash": source.fingerprint(), "revision": source.revision}}


def prepare_constraints(session, source):
    session.run("CREATE CONSTRAINT graphmine_entity_id IF NOT EXISTS FOR (n:GraphMineEntity) REQUIRE n.gm_id IS UNIQUE").consume()
    for label in sorted({mapping.label for mapping in source.relationships}):
        name = "graphmine_relationship_" + hashlib.sha256(label.encode()).hexdigest()
        session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR ()-[r:{quoted(label)}]-() REQUIRE r.gm_id IS UNIQUE").consume()


def apply_changes(tx, source, changes):
    """Touch changed records only; never detach-delete someone else's edges."""
    total = sum(len(rows) for problems in changes.values() for action, rows in problems.items() if action != "unchanged")
    written = 0
    checkpoint("writing", written, total)

    def batches(statement, rows, *, progress=True):
        nonlocal written
        for offset in range(0, len(rows), 500):
            batch = rows[offset:offset + 500]
            checkpoint("writing", written, total)
            result = tx.run(statement, source=source.id, rows=batch).single()
            if result is None or result["changed"] != len(batch):
                raise conflict()
            if progress:
                written += len(batch)

    # Taking temporary write locks before checking old values avoids lost updates
    # on a record that another writer changed after the comparison read.
    node_match = "UNWIND $rows AS row MATCH (n:GraphMineEntity {gm_source: $source, gm_id: row.id}) SET n.gm_sync_lock = true REMOVE n.gm_sync_lock WITH n,row WHERE properties(n) = row.before.properties AND size(labels(n)) = size(row.before.labels) AND all(label IN labels(n) WHERE label IN row.before.labels) "
    edge_match = "UNWIND $rows AS row MATCH ()-[r]->() WHERE elementId(r) = row.before.element_id AND r.gm_source = $source AND r.gm_id = row.id SET r.gm_sync_lock = true REMOVE r.gm_sync_lock WITH r,row WHERE properties(r) = row.before.properties "

    deleted_nodes = changes["nodes"]["deleted"]
    for offset in range(0, len(deleted_nodes), 500):
        checkpoint("writing", written, total)
        found = tx.run("UNWIND $ids AS id MATCH (n:GraphMineEntity {gm_source: $source, gm_id: id})-[r]-() WHERE r.gm_source IS NULL OR r.gm_source <> $source RETURN count(r) AS foreign_relationships",
                       source=source.id, ids=[row["id"] for row in deleted_nodes[offset:offset + 500]]).single()
        if found and found["foreign_relationships"]:
            raise conflict("A removed source node still has relationships outside this mapping. Review those relationships before synchronizing; no graph changes were committed.")

    deleted_edges = [{"id": row["id"], "before": row} for row in changes["relationships"]["deleted"]]
    rewired = [row for row in changes["relationships"]["updated"] if row["recreated"]]
    batches(edge_match + "DELETE r RETURN count(*) AS changed", deleted_edges)
    batches(edge_match + "DELETE r RETURN count(*) AS changed", rewired, progress=False)
    batches(node_match + "DELETE n RETURN count(*) AS changed", [{"id": row["id"], "before": row} for row in deleted_nodes])

    grouped = defaultdict(list)
    for row in changes["nodes"]["updated"]:
        grouped[(row["label"], row["remove_label"])].append(row)
    for (label, old_label), rows in grouped.items():
        statement = node_match + "SET n = row.properties "
        if old_label:
            statement += f"REMOVE n:{quoted(old_label)} "
        batches(statement + f"SET n:{quoted(label)} RETURN count(*) AS changed", rows)
    grouped.clear()
    for row in changes["nodes"]["created"]:
        grouped[row["label"]].append(row)
    for label, rows in grouped.items():
        batches(f"UNWIND $rows AS row CREATE (n:GraphMineEntity:{quoted(label)}) SET n = row.properties RETURN count(*) AS changed", rows)

    batches(edge_match + "SET r = row.properties RETURN count(*) AS changed", [row for row in changes["relationships"]["updated"] if not row["recreated"]])
    grouped.clear()
    for row in [*changes["relationships"]["created"], *rewired]:
        grouped[row["type"]].append(row)
    for label, rows in grouped.items():
        batches(f"UNWIND $rows AS row MATCH (a:GraphMineEntity {{gm_source: $source, gm_id: row.source}}), (b:GraphMineEntity {{gm_source: $source, gm_id: row.target}}) CREATE (a)-[r:{quoted(label)}]->(b) SET r = row.properties RETURN count(*) AS changed", rows)
    checkpoint("writing", written, total)
