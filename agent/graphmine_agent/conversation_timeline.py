"""Private, indexed conversation pages over classic archives and workflow events."""

import base64
import json
from threading import RLock

from .analytics import AnalyticsError, _json

_locks = [RLock() for _ in range(32)]


def initialize(db, *, backfill=False):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_entries (
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          id TEXT NOT NULL, created_at TEXT NOT NULL, lane INTEGER NOT NULL,
          ordinal INTEGER NOT NULL, turn_id TEXT, dedupe_key TEXT NOT NULL,
          origin TEXT, document TEXT NOT NULL, PRIMARY KEY(session_id,id)
        );
        CREATE INDEX IF NOT EXISTS conversation_entry_page ON conversation_entries(session_id,created_at DESC,lane DESC,ordinal DESC,id DESC);
        CREATE INDEX IF NOT EXISTS conversation_entry_dedupe ON conversation_entries(session_id,dedupe_key,created_at DESC,ordinal DESC,id DESC);
        CREATE INDEX IF NOT EXISTS conversation_entry_lane ON conversation_entries(session_id,lane,created_at);
        CREATE INDEX IF NOT EXISTS conversation_entry_origin ON conversation_entries(session_id,origin);
        CREATE TABLE IF NOT EXISTS conversation_archive_files (
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          filename TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
          PRIMARY KEY(session_id,filename)
        );
        CREATE TABLE IF NOT EXISTS conversation_archive_state (
          session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
          stamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_turns (
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          turn_id TEXT NOT NULL, number INTEGER NOT NULL,
          PRIMARY KEY(session_id,turn_id), UNIQUE(session_id,number)
        );
        CREATE INDEX IF NOT EXISTS events_turn ON events(session_id,json_extract(payload,'$.turn_id'),sequence);
        CREATE INDEX IF NOT EXISTS events_type ON events(session_id,type,sequence);
        CREATE INDEX IF NOT EXISTS events_chat_turn ON events(session_id,json_extract(payload,'$.turn_id'),json_extract(payload,'$.role'),sequence)
          WHERE type='workflow.chat';
        CREATE INDEX IF NOT EXISTS events_workflow_answer ON events(session_id,json_extract(payload,'$.workflow_id'),json_extract(payload,'$.revision'),sequence)
          WHERE type='workflow.answer';
        CREATE INDEX IF NOT EXISTS events_reasoning_stage ON events(session_id,json_extract(payload,'$.turn_id'),json_extract(payload,'$.stage'),sequence)
          WHERE type='workflow.reasoning';
    """)
    public = "type='workflow.chat' AND coalesce(json_extract(payload,'$.evaluation_id'),'')=''"
    event_row = """session_id,'event_'||sequence,created_at,2,sequence,json_extract(payload,'$.turn_id'),
        'event_'||sequence,NULL,'{}'"""  # Native payloads stay in events, without a second full copy.
    message = "coalesce(nullif(json_extract(payload,'$.message'),''),nullif(json_extract(payload,'$.summary'),''),json_extract(payload,'$.interpretation.summary'))"
    message_row = f"""session_id,'legacy_'||id,created_at,0,id,NULL,'legacy_'||id,NULL,
        json_object('id','legacy_'||id,'kind','conversation.legacy','role',role,'created_at',created_at,
                    'message',{message},'plan',json_extract(payload,'$.plan'))"""
    # The rows remain derived; their sources keep the original payloads/evidence.
    for table, prefix, key, row, predicate in (("events", "event_", "sequence", event_row, public), ("messages", "legacy_", "id", message_row, f"{message} IS NOT NULL")):
        for operation in ("INSERT", "UPDATE"):
            delete = f"DELETE FROM conversation_entries WHERE session_id=old.session_id AND id='{prefix}'||old.{key};" if operation == "UPDATE" else ""
            db.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS conversation_{table}_{operation.lower()} AFTER {operation} ON {table} BEGIN
                  {delete}
                  INSERT OR REPLACE INTO conversation_entries SELECT {row} FROM {table} WHERE {key}=new.{key} AND {predicate};
                END;
            """)
        db.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS conversation_{table}_delete AFTER DELETE ON {table} BEGIN
              DELETE FROM conversation_entries WHERE session_id=old.session_id AND id='{prefix}'||old.{key};
            END;
        """)
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS conversation_turn_insert AFTER INSERT ON events
          WHEN new.type='workflow.chat' AND json_extract(new.payload,'$.role')='user'
            AND coalesce(json_extract(new.payload,'$.evaluation_id'),'')=''
            AND json_extract(new.payload,'$.turn_id') IS NOT NULL BEGIN
          INSERT OR IGNORE INTO conversation_turns SELECT new.session_id,json_extract(new.payload,'$.turn_id'),
            coalesce((SELECT max(number) FROM conversation_turns WHERE session_id=new.session_id),0)+1;
        END;
    """)
    if backfill:
        db.execute(f"INSERT OR IGNORE INTO conversation_entries SELECT {event_row} FROM events WHERE {public}")
        db.execute(f"INSERT OR IGNORE INTO conversation_entries SELECT {message_row} FROM messages WHERE {message} IS NOT NULL")
        db.execute(f"""INSERT OR IGNORE INTO conversation_turns
            SELECT session_id,turn_id,row_number() OVER(PARTITION BY session_id ORDER BY first_sequence)
            FROM (SELECT session_id,json_extract(payload,'$.turn_id') turn_id,min(sequence) first_sequence
                  FROM events WHERE {public} AND json_extract(payload,'$.role')='user'
                  AND json_extract(payload,'$.turn_id') IS NOT NULL GROUP BY session_id,turn_id)""")


def archive_entry(event):
    """The same public fields as HistoryStore.transcript; never model prompts."""
    kind, data = event["type"], event["data"]
    row = {"id": "history_" + event["id"], "turn_id": event.get("turn_id"), "created_at": event["timestamp"], "kind": kind}
    key = row["id"]
    if kind in {"chat.request", "feedback_command.request"}:
        row.update(role="user", message=data["message"])
    elif kind in {"chat.response", "feedback_command.response"}:
        row.update({"role": "assistant", **data})
    elif kind == "chat.error":
        row.update(role="assistant", message=f"Request failed: {data['message']}")
    elif kind == "result.saved" and data.get("interpretation"):
        key = "result_" + data["id"]
        row.update(role="assistant", result_id=data["id"], message=data["interpretation"]["summary"], job_id=data["job_id"])
    else:
        return None
    return row, key


def _archive_stamp(directory):
    try:
        info = directory.stat()
        return _json([info.st_ino, info.st_mtime_ns, info.st_ctime_ns])
    except FileNotFoundError:
        return "absent"


def refresh_archive(database, session_id):
    directory = database.history.session_path(session_id) / "events"
    # Striped locks bound bookkeeping; no filesystem read holds a DB transaction.
    with _locks[sum(session_id.encode()) % len(_locks)]:
        for _ in range(3):
            stamp = _archive_stamp(directory)
            with database._connect() as db:
                saved = db.execute("SELECT stamp FROM conversation_archive_state WHERE session_id=?", (session_id,)).fetchone()
                if saved and saved[0] == stamp:
                    return
                known = {row[0]: (row[1], row[2]) for row in db.execute("SELECT filename,mtime_ns,size FROM conversation_archive_files WHERE session_id=?", (session_id,))}
            existing, batch = set(), []
            def flush():
                with database._lock, database._connect() as db:
                    for filename, mtime, size, entry in batch:
                        db.execute("DELETE FROM conversation_entries WHERE session_id=? AND origin=?", (session_id, filename))
                        if entry:
                            row, key = entry
                            db.execute("INSERT OR REPLACE INTO conversation_entries VALUES (?,?,?,?,?,?,?,?,?)",
                                       (session_id, row["id"], row["created_at"], 1, 0, row.get("turn_id"), key, filename, _json(row)))
                        db.execute("INSERT OR REPLACE INTO conversation_archive_files VALUES (?,?,?,?)", (session_id, filename, mtime, size))
                batch.clear()
            for path in sorted(directory.glob("*.json")):
                info = path.stat(); existing.add(path.name)
                if known.get(path.name) == (info.st_mtime_ns, info.st_size):
                    continue
                value = json.loads(path.read_bytes())
                batch.append((path.name, info.st_mtime_ns, info.st_size, archive_entry(value)))
                if len(batch) >= 100:
                    flush()
            if batch:
                flush()
            with database._lock, database._connect() as db:
                for filename in known.keys() - existing:
                    db.execute("DELETE FROM conversation_entries WHERE session_id=? AND origin=?", (session_id, filename))
                    db.execute("DELETE FROM conversation_archive_files WHERE session_id=? AND filename=?", (session_id, filename))
                db.execute("INSERT OR REPLACE INTO conversation_archive_state VALUES (?,?)", (session_id, stamp))
            if _archive_stamp(directory) == stamp:
                return
        raise AnalyticsError("Conversation history changed while loading. Retry the page.", "history_changed", 409)


def _cursor(value):
    if not value:
        return None
    try:
        row = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if (not isinstance(row, list) or len(row) != 4 or not isinstance(row[0], str)
                or type(row[1]) is not int or row[1] not in (0, 1, 2, 3)
                or type(row[2]) is not int or not 0 <= row[2] <= 9223372036854775807 or not isinstance(row[3], str)):
            raise ValueError
        return row
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AnalyticsError("The conversation page cursor is invalid.", "invalid_cursor") from exc


def conversation_page(database, session_id, *, before=None, limit=30, analytics=None):
    database.get_session(session_id)  # Always authorize before inspecting archives.
    cursor = _cursor(before)
    refresh_archive(database, session_id)
    database.get_session(session_id)
    latest = """NOT EXISTS (SELECT 1 FROM conversation_entries newer WHERE newer.session_id=e.session_id
        AND newer.dedupe_key=e.dedupe_key AND (newer.created_at,newer.ordinal,newer.id)>(e.created_at,e.ordinal,e.id))"""
    # Legacy messages end where the public append-only transcript starts.
    boundary = "SELECT min(e.created_at) FROM conversation_entries e WHERE e.session_id=? AND e.lane=1 AND " + latest
    with database._connect() as db:
        db.execute("BEGIN")
        earliest = db.execute(boundary, (session_id,)).fetchone()[0]
        where, args = ["e.session_id=?", latest], [session_id]
        if earliest is not None:
            where.append("(e.lane!=0 OR e.created_at<?)"); args.append(earliest)
        if cursor:
            where.append("(e.created_at,e.lane,e.ordinal,e.id)<(?,?,?,?)"); args.extend(cursor)
        rows = db.execute("SELECT e.* FROM conversation_entries e WHERE " + " AND ".join(where)
                          + " ORDER BY e.created_at DESC,e.lane DESC,e.ordinal DESC,e.id DESC LIMIT ?", [*args, limit + 1]).fetchall()
        if analytics is not None:
            from .workflow_index import manual_page

            rows = sorted([*rows, *manual_page(analytics, session_id, cursor, limit + 1)],
                          key=lambda row: tuple(row[key] for key in ("created_at", "lane", "ordinal", "id")), reverse=True)
        has_more = len(rows) > limit; rows = rows[:limit]
        turn_ids = list({row["turn_id"] for row in rows if row["turn_id"]})
        event_ids = [row["ordinal"] for row in rows if row["lane"] == 2]
        events, numbers = {}, {}
        if turn_ids:
            marks = ",".join("?" for _ in turn_ids)
            # Completed reasoning contains the full text. Earlier delta chunks
            # are redundant for display, but remain in the source event ledger.
            for row in db.execute(f"""SELECT e.* FROM events e INDEXED BY events_turn WHERE e.session_id=? AND json_extract(e.payload,'$.turn_id') IN ({marks})
                AND (e.type!='workflow.reasoning.delta' OR (
                  json_extract(e.payload,'$.call_id') IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM events done WHERE done.session_id=e.session_id AND done.type='workflow.reasoning'
                      AND json_extract(done.payload,'$.turn_id')=json_extract(e.payload,'$.turn_id')
                      AND json_extract(done.payload,'$.call_id')=json_extract(e.payload,'$.call_id')))
                  OR (json_extract(e.payload,'$.call_id') IS NULL AND NOT EXISTS (
                  SELECT 1 FROM events answer WHERE answer.session_id=e.session_id AND answer.type='workflow.chat'
                    AND json_extract(answer.payload,'$.turn_id')=json_extract(e.payload,'$.turn_id') AND json_extract(answer.payload,'$.role')='assistant')
                  AND e.sequence>coalesce((SELECT max(done.sequence) FROM events done WHERE done.session_id=e.session_id
                    AND done.type='workflow.reasoning' AND json_extract(done.payload,'$.turn_id')=json_extract(e.payload,'$.turn_id')
                    AND json_extract(done.payload,'$.stage')=json_extract(e.payload,'$.stage')),0))) ORDER BY e.sequence""", [session_id, *turn_ids]):
                events[row["sequence"]] = dict(row)
            numbers = dict(db.execute(f"SELECT turn_id,number FROM conversation_turns WHERE session_id=? AND turn_id IN ({marks})", [session_id, *turn_ids]).fetchall())
        if event_ids:
            for row in db.execute(f"SELECT * FROM events WHERE session_id=? AND sequence IN ({','.join('?' for _ in event_ids)})", [session_id, *event_ids]):
                events[row["sequence"]] = dict(row)
        for item in rows:
            if item["lane"] != 3:
                continue
            record = json.loads(item["document"])
            row = db.execute("""SELECT * FROM events WHERE session_id=? AND type='workflow.answer'
                AND json_extract(payload,'$.workflow_id')=? AND json_extract(payload,'$.revision')=?
                ORDER BY sequence DESC LIMIT 1""", (session_id, record["id"], record["revision"])).fetchone()
            if row:
                events[row["sequence"]] = dict(row)
        event_cursor = db.execute("SELECT coalesce(max(sequence),0) FROM events WHERE session_id=?", (session_id,)).fetchone()[0]
    ordered = []
    for sequence in sorted(events):
        event = events[sequence]; event["payload"] = json.loads(event["payload"])
        if not event["payload"].get("evaluation_id"):
            ordered.append(event)
    next_cursor = None
    if rows and has_more:
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(_json([last[key] for key in ("created_at", "lane", "ordinal", "id")]).encode()).decode().rstrip("=")
    return {"messages": [json.loads(row["document"]) for row in reversed(rows) if row["lane"] in (0, 1)],
            "manual_workflow_ids": [json.loads(row["document"])["id"] for row in reversed(rows) if row["lane"] == 3],
            "events": ordered, "event_cursor": event_cursor, "turn_numbers": numbers,
            "next_cursor": next_cursor, "has_more": has_more, "limit": limit}
