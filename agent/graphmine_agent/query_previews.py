"""Expiring query snapshots, promoted atomically when saved or used in chat."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime

from .analytics import AnalyticsError, _json
from .datasets import DatasetLibrary, _owner
from .identity import AccountError, current_principal
from .models import new_id
from .query_results import is_database_query
from .neo4j_records import require_visible, tagged

PREVIEW_SECONDS = 24 * 3600

# Active jobs are durable snapshot leases; completion/cancellation/recovery
# deletes the job row and releases the lease in the same transaction.
UNPINNED = """NOT EXISTS (SELECT 1 FROM database_jobs j WHERE j.kind='semantic'
    AND j.status IN ('queued','running','cancelling') AND j.owner_id=query_previews.owner_id
    AND json_extract(j.document,'$.query.base_version_id')=query_previews.id)"""


def snapshot_in_use(db, identifier, owner):
    return db.execute("""SELECT 1 FROM database_jobs WHERE kind='semantic' AND owner_id=?
        AND status IN ('queued','running','cancelling')
        AND json_extract(document,'$.query.base_version_id')=? LIMIT 1""", (owner or "", identifier)).fetchone() is not None


def _discard_unreferenced(db):
    db.execute("""
        DELETE FROM query_preview_blobs AS b WHERE NOT EXISTS (
            SELECT 1 FROM query_previews AS p
            WHERE p.owner_id=b.owner_id AND p.sha256=b.sha256
        )
    """)


def _remove_indexes(database, identifiers):
    from .result_index import table_index_path

    for identifier in identifiers:
        table_index_path(database, identifier).unlink(missing_ok=True)


def expire_previews(database, now=None):
    """Global maintenance; never removes promoted datasets or conversation inputs."""
    with database._lock, database._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cutoff = time.time() if now is None else now
        identifiers = [row[0] for row in db.execute("SELECT id FROM query_previews WHERE expires_at<=? AND " + UNPINNED, (cutoff,))]
        deleted = db.execute("DELETE FROM query_previews WHERE expires_at<=? AND " + UNPINNED, (cutoff,)).rowcount
        _discard_unreferenced(db)
    _remove_indexes(database, identifiers)
    return deleted


class QueryPreviews:
    def __init__(self, runtime, *, clock=time.time):
        self.runtime, self.database, self.clock = runtime, runtime.database, clock
        self.library = DatasetLibrary(runtime)
        self.settings = self.library.settings

    def store(self, value, *, name, kind, source, complete):
        if kind == "graph":
            self.runtime.graph_store._validate_graph(value)
        elif kind == "table":
            from .table_artifacts import validate_table

            validate_table(value)
        raw = _json(value).encode()
        unlimited = kind == "graph" and is_database_query(source)
        if self.runtime.settings.analytics_max_input_bytes is not None and not unlimited and len(raw) > self.runtime.settings.analytics_max_input_bytes:
            raise AnalyticsError("Preview exceeds the input byte budget", "resource_limit")
        now = self.clock()
        expire_previews(self.database, now)
        metadata = {
            "id": new_id("dataset_version"), "dataset_id": new_id("dataset"),
            "version": 1, "name": name.strip(), "kind": kind,
            "created_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(now + PREVIEW_SECONDS, UTC).isoformat(),
            "temporary": True, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "source": source, "source_complete": complete,
        }
        if kind == "table":
            from .table_artifacts import summary

            metadata["table"] = summary(value)
        tagged(metadata)
        require_visible(metadata, self.settings)
        owner = _owner() or ""
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM query_preview_blobs WHERE owner_id=? AND sha256=?", (owner, metadata["sha256"])).fetchone()
            serialized = _json(metadata)
            added = len(serialized.encode()) + (0 if exists else len(raw))
            principal = current_principal.get()
            if principal and added > principal.accounts.upload_remaining(principal.user_id):
                raise AccountError("Your storage allowance is full. Discard unused previews or datasets.", "storage_limit")
            db.execute("INSERT OR IGNORE INTO query_preview_blobs VALUES (?,?,?,?)", (owner, metadata["sha256"], raw, len(raw)))
            db.execute("INSERT INTO query_previews VALUES (?,?,?,?,?)", (metadata["id"], owner, serialized, metadata["sha256"], now + PREVIEW_SECONDS))
        return metadata

    def _row(self, db, version_id, *, content=False):
        row = db.execute("SELECT p.metadata, p.expires_at" + (", b.content" if content else "") + """
            FROM query_previews AS p
            JOIN query_preview_blobs AS b ON b.owner_id=p.owner_id AND b.sha256=p.sha256
            WHERE p.id=? AND p.owner_id=?
        """, (version_id, _owner() or "")).fetchone()
        if row:
            require_visible(json.loads(row["metadata"]), self.settings)
        if row and row["expires_at"] <= self.clock() and not snapshot_in_use(db, version_id, _owner()):
            raise AnalyticsError("This query preview expired. Run the query again.", "preview_expired", 410)
        return row

    def get(self, version_id, *, content=False):
        with self.database._connect() as db:
            row = self._row(db, version_id, content=content)
        if row:
            metadata = json.loads(row["metadata"])
            return (metadata, row["content"]) if content else metadata
        return self.library.get(version_id, content=content)

    def promote(self, version_id):
        """Keep the snapshot ID/content/provenance; repeated promotion is harmless."""
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, version_id, content=True)
            if row is None:
                return self.library.get(version_id)
            metadata, raw = json.loads(row["metadata"]), row["content"]
            if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                raise AnalyticsError("The query preview failed its integrity check", "data_integrity", 409)
            references = db.execute("SELECT count(*) FROM query_previews WHERE owner_id=? AND sha256=?", (_owner() or "", metadata["sha256"])).fetchone()[0]
            credit = len(row["metadata"].encode()) + (len(raw) if references == 1 else 0)
            metadata.pop("temporary")
            metadata.pop("expires_at")
            self.library._persist(db, metadata, raw, storage_credit=credit)
            db.execute("DELETE FROM query_previews WHERE id=? AND owner_id=?", (version_id, _owner() or ""))
            _discard_unreferenced(db)
        return metadata

    def discard(self, version_id):
        # Discarding a preview must never delete a dataset already saved or used.
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._row(db, version_id)
            if snapshot_in_use(db, version_id, _owner()):
                raise AnalyticsError("This snapshot is in use by a semantic job. Cancel or finish that job first.", "snapshot_in_use", 409)
            removed = db.execute("DELETE FROM query_previews WHERE id=? AND owner_id=?", (version_id, _owner() or "")).rowcount
            _discard_unreferenced(db)
        if removed:
            _remove_indexes(self.database, [version_id])
