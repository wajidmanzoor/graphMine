"""Neo4j provenance classification and administrator-only record counts."""

import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar

BACKENDS = {"local", "iu-remote"}
_MIXED = "mixed-neo4j-backends"
_worker_backend = ContextVar("neo4j_worker_backend", default=None)


def selected_backend(settings):
    from .neo4j_backend import active_backend_id
    return _worker_backend.get() or active_backend_id(settings)


@contextmanager
def worker_backend(identifier):
    """Already admitted analytics may finish using their immutable local inputs."""
    token = _worker_backend.set(identifier)
    try:
        yield
    finally:
        _worker_backend.reset(token)


def backend_id(document):
    if not isinstance(document, (dict, list)):
        return None
    if isinstance(document, list):
        values = {backend_id(value) for value in document} - {None}
    else:
        tag = document.get("backend_id")
        if isinstance(tag, str) and tag in BACKENDS:
            return tag
        # These are metadata/provenance containers, never uploaded graph rows.
        values = {backend_id(document.get(key)) for key in (
            "source", "parent", "provenance", "database_source", "file_snapshot", "input_provenance", "inputs", "tables")}
        for key in ("input_provenance", "tables"):
            if isinstance(document.get(key), dict):
                values.update(backend_id(value) for value in document[key].values())
        if document.get("database_source") is not None:
            values.add("local") if not (values - {None}) else None
        values.discard(None)
        if not values and (document.get("type") in {"neo4j", "database_query", "database_sync"}
                           or document.get("connector_type") == "neo4j"
                           or document.get("kind") in {"database_query", "database_sync"}):
            return "local"
    # Invalid mixed provenance must never turn a Neo4j record into an upload.
    return next(iter(values)) if len(values) == 1 else _MIXED if values else None


def derived_backend(document, files, workflows=None, jobs=None):
    """Workflow/job provenance may retain file identifiers rather than sources."""
    direct = backend_id(document)
    if direct:
        return direct
    def lookup(mapping, identifier):
        return mapping.get(identifier) if isinstance(identifier, str) else None
    def referenced(value):
        if isinstance(value, dict):
            found = {lookup(files, value.get("file_id")), lookup(files, value.get("graph_id")),
                     lookup(workflows or {}, value.get("workflow_id")), lookup(jobs or {}, value.get("job_id"))}
            for key, item in value.items():
                if key != "file_id":
                    found.update(referenced(item))
            return found - {None}
        if isinstance(value, list):
            return {tag for item in value for tag in referenced(item)}
        return set()
    values = referenced(document)
    return next(iter(values)) if len(values) == 1 else _MIXED if values else None


def tagged(document, tag=None):
    tag = tag or backend_id(document)
    if tag == _MIXED:
        from .database import RecordNotFound
        raise RecordNotFound("not found")
    if tag:
        document["backend_id"] = tag
    return document


def tag_references(db, document):
    if backend_id(document):
        return tagged(document)
    references = {"file_id": set(), "graph_id": set(), "workflow_id": set(), "job_id": set()}
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in references and isinstance(item, str):
                    references[key].add(item)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(document)
    files, workflows, jobs = {}, {}, {}
    for identifier in references["file_id"] | references["graph_id"]:
        row = db.execute("SELECT payload FROM files WHERE id=?", (identifier,)).fetchone()
        if row:
            files[identifier] = backend_id(json.loads(row[0]))
    for identifier in references["workflow_id"]:
        row = db.execute("SELECT backend_id FROM neo4j_workflow_backends WHERE id=?", (identifier,)).fetchone()
        if row:
            workflows[identifier] = row[0]
    for identifier in references["job_id"]:
        row = db.execute("SELECT payload FROM jobs WHERE id=?", (identifier,)).fetchone()
        if row:
            jobs[identifier] = backend_id(json.loads(row[0]))
    return tagged(document, derived_backend(document, files, workflows, jobs))


def visible(document, settings):
    tag = backend_id(document)
    return tag is None or tag == selected_backend(settings)


def require_visible(document, settings):
    if not visible(document, settings):
        from .database import RecordNotFound
        raise RecordNotFound("not found")


def register_visibility(db, settings):
    active = selected_backend(settings)
    def permitted(raw):
        try:
            return backend_id(json.loads(raw)) in (None, active)
        except (TypeError, ValueError):
            return False
    db.create_function("neo4j_visible", 1, permitted, deterministic=True)


def require_history_visible(runtime, session_id):
    """A complete archive includes old revisions; never export a hidden record.

    Individual files and results still use their own visibility checks. This
    guard covers the unfiltered evidence bundle, its manifest and model notes.
    It preserves the archive bytes so switching back restores access.
    """
    from .database import RecordNotFound
    database = runtime.database
    database.get_session(session_id)
    with database._connect() as db:
        for table in ("files", "jobs", "results"):
            if db.execute(f"SELECT 1 FROM {table} WHERE session_id=? AND NOT neo4j_visible(payload) LIMIT 1", (session_id,)).fetchone():
                raise RecordNotFound("not found")
        for event in database.history.session_events(session_id):
            data = event.get("data")
            metadata = {"job_id": event.get("job_id"), "source": data}
            require_visible(tag_references(db, metadata), runtime.settings)
        root = database.history.session_path(session_id)
        for path in (root / "files").glob("*/metadata.json"):
            require_visible(json.loads(path.read_text()).get("file", {}), runtime.settings)
    with sqlite3.connect(runtime.analytics.path) as db:
        for identifier, raw in db.execute("SELECT id,document FROM workflows WHERE session_id=?", (session_id,)):
            require_visible(json.loads(raw), runtime.settings)
            for row in db.execute("SELECT DISTINCT backend_id FROM neo4j_result_backends WHERE artifact LIKE ?", (identifier + "/%",)):
                require_visible({"backend_id": row[0]}, runtime.settings)


def migrate_database(db, *, workflows=None):
    """Tag metadata only; graph/table bytes, identifiers and versions are retained."""
    db.execute("CREATE TABLE IF NOT EXISTS neo4j_workflow_backends (id TEXT PRIMARY KEY, backend_id TEXT NOT NULL)")
    files, jobs = {}, {}
    for table, column in (("files", "payload"), ("dataset_versions", "metadata"),
                          ("query_previews", "metadata"), ("user_connectors", "document"),
                          ("jobs", "payload"), ("results", "payload"), ("project_items", "metadata")):
        for identifier, raw in db.execute(f"SELECT id,{column} FROM {table}").fetchall():
            value = json.loads(raw)
            tag = derived_backend(value, files, workflows, jobs)
            if tag and value.get("backend_id") != tag:
                value["backend_id"] = tag
                db.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (json.dumps(value), identifier))
            if table == "files":
                files[identifier] = tag
                metadata = value.get("metadata") or {}
                if isinstance(metadata, dict) and isinstance(metadata.get("id"), str):
                    files[metadata["id"]] = tag
            if table == "jobs":
                jobs[identifier] = tag
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_library'").fetchone():
        columns = {row[1] for row in db.execute("PRAGMA table_info(query_library)")}
        if "backend_id" not in columns:
            db.execute("ALTER TABLE query_library ADD COLUMN backend_id TEXT NOT NULL DEFAULT 'local'")
        if "document" in columns:
            for identifier, raw in db.execute("SELECT id,document FROM query_library").fetchall():
                value = json.loads(raw)
                if value.get("backend_id") is None:
                    db.execute("UPDATE query_library SET document=? WHERE id=?", (json.dumps(tagged(value, "local")), identifier))
    # Rebuild only the lightweight archive index; preserve every history file.
    db.execute("DELETE FROM conversation_archive_state")
    db.execute("DELETE FROM conversation_archive_files")
    db.execute("DELETE FROM conversation_entries WHERE lane=1")
    return files


def migrate_workflows(service):
    """Keep immutable result bytes; store their backend in a small metadata index."""
    with service.database._connect() as main:
        files = {row[0]: backend_id(json.loads(row[1])) for row in main.execute("SELECT id,payload FROM files")}
    workflows = {}
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS neo4j_result_backends (artifact TEXT PRIMARY KEY, backend_id TEXT NOT NULL)")
        for identifier, raw in db.execute("SELECT id,document FROM workflows").fetchall():
            value = json.loads(raw)
            tag = derived_backend(value, files)
            workflows[identifier] = tag
            if tag:
                if value.get("backend_id") != tag:
                    db.execute("UPDATE workflows SET document=? WHERE id=?", (json.dumps(tagged(value, tag)), identifier))
                for path in (service.root / identifier).glob("revision-*/*.json"):
                    if path.name == "result.json" or path.name.startswith("step-"):
                        db.execute("INSERT OR IGNORE INTO neo4j_result_backends VALUES (?,?)", (str(path.relative_to(service.root)), tag))
    with service.database._lock, service.database._connect() as db:
        db.executemany("INSERT OR REPLACE INTO neo4j_workflow_backends VALUES (?,?)", [(key, tag) for key, tag in workflows.items() if tag])
        migrate_database(db, workflows=workflows)
        # Event payloads may embed full results, file snapshots or workflow IDs.
        for table, key in (("conversation_events", "sequence"), ("messages", "id")):
            for identifier, raw in db.execute(f"SELECT {key},payload FROM {table}").fetchall():
                value = json.loads(raw)
                tag = derived_backend(value, files, workflows)
                if tag and value.get("backend_id") != tag:
                    db.execute(f"UPDATE {table} SET payload=? WHERE {key}=?", (json.dumps(tagged(value, tag)), identifier))
    with sqlite3.connect(service.path) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviewed_examples'").fetchone():
            for identifier, raw in db.execute("SELECT id,document FROM reviewed_examples").fetchall():
                value = json.loads(raw)
                tag = derived_backend(value, files, workflows)
                if tag and value.get("backend_id") != tag:
                    db.execute("UPDATE reviewed_examples SET document=? WHERE id=?", (json.dumps(tagged(value, tag)), identifier))


def migrate_connections(settings):
    """Existing account connection files belong to local; preserve credentials."""
    from .neo4j_backend import atomic_json
    import os
    import stat
    for path in (Path(settings.data_root) / "database-connections").glob("*/*.json"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
                    continue
                value = json.load(stream)
            if not isinstance(value, dict) or not isinstance(value.get("source"), dict):
                continue
        except (OSError, ValueError):
            continue  # Invalid private connections remain unavailable; do not rewrite them.
        if value.get("source", {}).get("backend_id") is None:
            value["source"]["backend_id"] = "local"
            atomic_json(path, value)


def counts(runtime):
    from .database_sources import configured
    from .neo4j_backend import source_backend_id
    from .neo4j_registry import sources

    kinds = ("connections", "curated_datasets", "snapshots", "saved_queries", "files", "workflows", "results")
    result = {name: dict.fromkeys(kinds, 0) for name in sorted(BACKENDS)}
    def add(kind, document, *, default=None):
        tag = backend_id(document) or default
        if tag in BACKENDS:
            result[tag][kind] += 1
    for source in configured(runtime.settings):
        add("connections", {}, default=source_backend_id(source))
    for source in sources(runtime.settings):
        tag = source_backend_id(source)
        add("connections", {}, default=tag)
        add("curated_datasets", {}, default=tag)
    for path in (Path(runtime.settings.data_root) / "database-connections").glob("*/*.json"):
        value = json.loads(path.read_text())
        add("connections", value.get("source", {}), default="local")
    with runtime.database._connect() as db:
        files = {row[0]: backend_id(json.loads(row[1])) for row in db.execute("SELECT id,payload FROM files")}
        for table, column, kind in (("dataset_versions", "metadata", "snapshots"),
                                    ("query_previews", "metadata", "snapshots"),
                                    ("files", "payload", "files"), ("results", "payload", "results"),
                                    ("user_connectors", "document", "connections")):
            for row in db.execute(f"SELECT {column} FROM {table}"):
                add(kind, json.loads(row[0]))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_library'").fetchone():
            columns = {row[1] for row in db.execute("PRAGMA table_info(query_library)")}
            if "backend_id" in columns:
                for row in db.execute("SELECT backend_id,count(*) FROM query_library GROUP BY backend_id"):
                    result[row[0] or "local"]["saved_queries"] += row[1]
            else:
                result["local"]["saved_queries"] = db.execute("SELECT count(*) FROM query_library").fetchone()[0]
    with sqlite3.connect(runtime.analytics.path) as db:
        for row in db.execute("SELECT document FROM workflows"):
            value = json.loads(row[0])
            tag = derived_backend(value, files)
            add("workflows", value, default=tag)
            if value.get("status") == "completed":
                add("results", value, default=tag)
    return result
