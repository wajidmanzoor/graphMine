"""Lightweight workflow discovery without loading immutable input provenance."""

import json
import sqlite3
from contextlib import closing

from .analytics_modes import saved_mode


def initialize(db):
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_summaries'").fetchone()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_summaries (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL,
          turn_id TEXT, document TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS workflow_summary_session ON workflow_summaries(session_id,created_at,id);
        CREATE INDEX IF NOT EXISTS workflow_summary_manual ON workflow_summaries(session_id,created_at DESC,id DESC) WHERE turn_id IS NULL;
    """)
    projection = "id,session_id,coalesce(json_extract(document,'$.created_at'),''),nullif(json_extract(document,'$.planning_turn_id'),''),json_remove(document,'$.input_provenance','$.validation.inputs')"
    for problem in ("INSERT", "UPDATE"):
        db.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS workflow_summary_{problem.lower()} AFTER {problem} ON workflows BEGIN
              DELETE FROM workflow_summaries WHERE id=new.id;
              INSERT INTO workflow_summaries SELECT {projection} FROM workflows WHERE id=new.id;
            END;
        """)
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS workflow_summary_delete AFTER DELETE ON workflows BEGIN
          DELETE FROM workflow_summaries WHERE id=old.id;
        END;
    """)
    if not present:
        db.execute(f"INSERT INTO workflow_summaries SELECT {projection} FROM workflows")


def summaries(service, session_id):
    service.database.get_session(session_id)
    with closing(sqlite3.connect(service.path)) as db:
        from .neo4j_records import register_visibility
        register_visibility(db, service.settings)
        return [saved_mode(json.loads(row[0])) for row in db.execute(
            "SELECT document FROM workflow_summaries WHERE session_id=? AND neo4j_visible(document) ORDER BY created_at,id", (session_id,))]


def manual_page(service, session_id, cursor, limit):
    service.database.get_session(session_id)
    where, args = ["session_id=?", "turn_id IS NULL", "neo4j_visible(document)"], [session_id]
    if cursor:
        where.append("(created_at,3,0,'workflow_'||id)<(?,?,?,?)"); args.extend(cursor)
    with closing(sqlite3.connect(service.path)) as db:
        db.row_factory = sqlite3.Row
        from .neo4j_records import register_visibility
        register_visibility(db, service.settings)
        return [dict(row) for row in db.execute(
            "SELECT 'workflow_'||id id,created_at,3 lane,0 ordinal,NULL turn_id,document FROM workflow_summaries WHERE "
            + " AND ".join(where) + " ORDER BY created_at DESC,workflow_summaries.id DESC LIMIT ?", [*args, limit])]
