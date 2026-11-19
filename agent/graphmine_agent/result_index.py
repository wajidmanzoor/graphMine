"""Rebuildable SQLite indexes for immutable JSON result artifacts.

Only the first read parses the source. Subsequent pages decode selected rows;
exact filters, typed memberships and stable sort ranks have persistent indexes.
Free-text substring searches scan normalized text, not Python result objects.
"""

import hashlib
import json
import os
import re
import sqlite3
from . import perf
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from threading import RLock

from .analytics import AnalyticsError, _json, _key, _sort_key
from .database import RecordNotFound

VERSION = 2
_locks = [RLock() for _ in range(32)]


def file_stamp(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def is_workflow_index(path):
    """Recognize only service-generated sidecars, never uploaded source files."""
    return (path.parent.parent.parent.name == "analytics"
            and re.fullmatch(r"revision-[0-9]+", path.parent.name) is not None
            and re.fullmatch(r"(?:result|step-.+)\.rows\.sqlite3(?:\..+\.tmp(?:-journal)?)?", path.name) is not None)


def table_index_path(database, identifier):
    # IDs are untrusted route parameters; never use them as filesystem paths.
    return database.path.parent / "table-indexes" / (hashlib.sha256(identifier.encode()).hexdigest() + ".sqlite3")


@contextmanager
def open_index(path, stamp, build):
    """Publish a complete index atomically; one builder per lock stripe.

    stamp must be cheap and must recheck source availability/authorization.
    A changed or corrupt derived index is rebuilt from the original artifact.
    """
    path = Path(path).absolute()
    lock = _locks[int.from_bytes(hashlib.sha256(str(path).encode()).digest()[:2], "big") % len(_locks)]
    with lock:
        for _ in range(3):
            expected = _json([VERSION, stamp()])
            connection = None
            try:
                connection = perf.connect(f"{path.as_uri()}?mode=ro", uri=True)
                found = connection.execute("SELECT value FROM meta WHERE key='stamp'").fetchone()
                if found and found[0] == expected:
                    break
            except sqlite3.DatabaseError:
                pass
            if connection is not None:
                connection.close()
                connection = None
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
            os.close(fd)  # mkstemp creates private 0600 files.
            try:
                with closing(perf.connect(temporary)) as db, db:
                    db.executescript("""
                        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                        CREATE TABLE ports(name TEXT PRIMARY KEY,metadata TEXT NOT NULL,total INTEGER NOT NULL,is_list INTEGER NOT NULL);
                        CREATE TABLE items(port TEXT NOT NULL,position INTEGER NOT NULL,raw TEXT NOT NULL,search TEXT NOT NULL,size INTEGER,
                          PRIMARY KEY(port,position));
                        CREATE TABLE fields(port TEXT NOT NULL,name TEXT NOT NULL,position INTEGER NOT NULL,exact TEXT NOT NULL,rank INTEGER,
                          PRIMARY KEY(port,name,position));
                        CREATE TABLE members(port TEXT NOT NULL,vertex TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(port,vertex,position));
                    """)
                    header = build(db)
                    db.executescript("""
                        CREATE INDEX field_exact ON fields(port,name,exact,position);
                        CREATE INDEX field_asc ON fields(port,name,rank,position) WHERE rank IS NOT NULL;
                        CREATE INDEX field_desc ON fields(port,name,rank DESC,position) WHERE rank IS NOT NULL;
                        CREATE INDEX group_size ON items(port,size,position);
                    """)
                    db.executemany("INSERT INTO meta VALUES (?,?)", [("stamp", expected), ("header", _json(header))])
                if _json([VERSION, stamp()]) != expected:
                    continue
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        else:
            raise AnalyticsError("The result changed while its index was being prepared. Retry the read.", "revision_conflict", 409)
        # Hold a read connection to this inode even if a later request replaces it.
    try:
        yield RowIndex(connection)
        if _json([VERSION, stamp()]) != expected:
            raise AnalyticsError("The result changed during the read. Retry the read.", "revision_conflict", 409)
    finally:
        connection.close()


def add_port(db, name, port, *, sort_key=_sort_key):
    value = port.get("value")
    metadata = {k: v for k, v in port.items() if k != "value"}
    if port.get("type") in {"motif_instances", "graphlet_instances"} and isinstance(value, dict):
        from .result_views import view_items

        value = view_items(port)
        metadata["presentation_only"] = True
    is_list = isinstance(value, list)
    rows = value if is_list else [value]
    group = port.get("type") == "vertex_groups"
    names = set()
    for position, row in enumerate(rows):
        members = {_key(v) for v in row.get("vertices", [])} if group else set()
        db.execute("INSERT INTO items VALUES (?,?,?,?,?)", (name, position, _json(row), json.dumps(row, ensure_ascii=False).casefold(), len(members) if group else None))
        if group:
            db.executemany("INSERT INTO members VALUES (?,?,?)", ((name, vertex, position) for vertex in members))
        if isinstance(row, dict):
            names.update(row)
    # Rank with Python's exact integer/float comparisons. SQLite REAL would lose
    # integer identity above 2**53; INTEGER cannot hold every supported JSON ID.
    for field in sorted(names):
        present = [(sort_key(row[field]), position) for position, row in enumerate(rows) if isinstance(row, dict) and row.get(field) is not None]
        present.sort(key=lambda item: item[0])
        ranks, rank, previous = {}, -1, None
        for key, position in present:
            if key != previous:
                rank += 1
                previous = key
            ranks[position] = rank
        db.executemany("INSERT INTO fields VALUES (?,?,?,?,?)", ((name, field, position, _key(row[field]), ranks.get(position)) for position, row in enumerate(rows) if isinstance(row, dict) and field in row))
    if group:
        counts = db.execute("SELECT count(*),coalesce(sum(n>1),0) FROM (SELECT count(*) n FROM members WHERE port=? GROUP BY vertex)", (name,)).fetchone()
        sizes = db.execute("SELECT coalesce(min(size),0),coalesce(max(size),0) FROM items WHERE port=?", (name,)).fetchone()
        metadata["group_summary"] = {"groups": len(rows), "unique_members": counts[0], "shared_members": counts[1], "smallest": sizes[0], "largest": sizes[1]}
    db.execute("INSERT INTO ports VALUES (?,?,?,?)", (name, _json(metadata), len(rows), is_list))


def build_workflow(db, saved):
    def step_index(step, prefix):
        result = step.get("result")
        if not result:
            return step
        for name, port in (result.get("ports") or {}).items():
            add_port(db, _json([prefix, name]), port)
        header = {**result, "ports": list((result.get("ports") or {}))}
        # Native payloads duplicate the port collections in result.result.
        # Keep bounded scalar metadata here; full values remain in the artifact
        # and indexed ports. Never hide a second, unpaged copy in the header.
        if "result" in header:
            raw = header["result"]
            header["result"] = {
                key: value for key, value in list(raw.items())[:64]
                if value is None or isinstance(value, (bool, int, float))
                or isinstance(value, str) and len(value) <= 1024
            } if isinstance(raw, dict) else {}
            if header["result"] != raw:
                header["raw_result_truncated"] = True
        return {**step, "result": header}

    if "steps" in saved:
        return {**saved, "steps": {name: step_index(step, name) for name, step in saved["steps"].items()}}
    return step_index(saved, "")


class RowIndex:
    def __init__(self, db):
        self.db = db

    def metadata(self, name):
        port = self.db.execute("SELECT metadata,total,is_list FROM ports WHERE name=?", (name,)).fetchone()
        if port is None:
            raise RecordNotFound("No such output port")
        return json.loads(port[0]), port[1], bool(port[2])

    def rows(self, name, *, sort=None, descending=False):
        """Iterate a complete port without offsets or a full Python row list."""
        self.metadata(name)
        if sort:
            query = """SELECT i.raw FROM fields f JOIN items i ON i.port=f.port AND i.position=f.position
                WHERE f.port=? AND f.name=? AND f.rank IS NOT NULL ORDER BY f.rank """
            query += "DESC,f.position" if descending else "ASC,f.position"
            for row in self.db.execute(query, (name, sort)):
                yield json.loads(row[0])
            query = """SELECT i.raw FROM items i WHERE i.port=? AND NOT EXISTS
                (SELECT 1 FROM fields f WHERE f.port=i.port AND f.name=? AND f.position=i.position AND f.rank IS NOT NULL)
                ORDER BY i.position"""
            args = (name, sort)
        else:
            query, args = "SELECT raw FROM items WHERE port=? ORDER BY position", (name,)
        for row in self.db.execute(query, args):
            yield json.loads(row[0])

    def summary(self, limit):
        saved = json.loads(self.db.execute("SELECT value FROM meta WHERE key='header'").fetchone()[0])
        for step, value in saved.get("steps", {}).items():
            if not value.get("result"):
                continue
            ports = {}
            for name in value["result"]["ports"]:
                key = _json([step, name])
                metadata, total, is_list = self.metadata(key)
                rows = self.db.execute("SELECT raw FROM items WHERE port=? ORDER BY position LIMIT ?", (key, limit if is_list else 1))
                items = [json.loads(row[0]) for row in rows]
                ports[name] = {**metadata, "value": items if is_list else items[0]}
                if is_list and total > limit:
                    ports[name].update(value_truncated=True, total_items=total)
            value["result"]["ports"] = ports
        return saved

    def memberships(self, name, vertices):
        metadata, total, _ = self.metadata(name)
        if metadata.get("type") != "vertex_groups":
            raise AnalyticsError("Membership counts require a group output", "invalid_selection")
        return {"scope": "retained_groups", "total_groups": total, "complete": metadata.get("complete", False),
                "memberships": [{"vertex": vertex, "groups": self.db.execute("SELECT count(*) FROM members WHERE port=? AND vertex=?", (name, key)).fetchone()[0]} for key, vertex in {_key(v): v for v in vertices}.items()]}

    def page(self, name, offset, limit, *, search=None, sort=None, descending=False, min_size=None, max_size=None, member=None):
        metadata, total, _ = self.metadata(name)
        where, args = ["i.port=?"], [name]
        if min_size is not None or max_size is not None or member is not None:
            if metadata.get("type") != "vertex_groups":
                raise AnalyticsError("Group filters require a group output", "invalid_filter")
            if min_size is not None and max_size is not None and min_size > max_size:
                raise AnalyticsError("Minimum size must not exceed maximum size", "invalid_filter")
            for value, operator in ((min_size, ">="), (max_size, "<=")):
                if value is not None:
                    where.append(f"i.size{operator}?"); args.append(value)
            if member is not None:
                try:
                    vertex = json.loads(member)
                except ValueError:
                    vertex = member
                if type(vertex) not in (int, str):
                    raise AnalyticsError("A member ID must be an integer or text", "invalid_filter")
                where.append("i.position IN (SELECT position FROM members WHERE port=? AND vertex=?)")
                args.extend((name, _key(vertex)))
        if search:
            scoped = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*):(.*)", search.strip(), re.DOTALL)
            if scoped:
                try:
                    value = json.loads(scoped.group(2).strip())
                except ValueError:
                    value = scoped.group(2).strip()
                where.append("i.position IN (SELECT position FROM fields WHERE port=? AND name=? AND exact=?)")
                args.extend((name, scoped.group(1), _key(value)))
            else:
                where.append("instr(i.search,?)>0"); args.append(search.strip().casefold())
        condition = " AND ".join(where)
        matched = total if len(where) == 1 else self.db.execute("SELECT count(*) FROM items i WHERE " + condition, args).fetchone()[0]
        rows = []
        if sort:
            join = " FROM fields f JOIN items i ON i.port=f.port AND i.position=f.position WHERE f.port=? AND f.name=? AND f.rank IS NOT NULL AND " + condition
            params = [name, sort, *args]
            present = (self.db.execute("SELECT count(*) FROM fields WHERE port=? AND name=? AND rank IS NOT NULL", (name, sort)).fetchone()[0]
                       if len(where) == 1 else self.db.execute("SELECT count(*)" + join, params).fetchone()[0])
            if offset < present:
                rows = self.db.execute("SELECT i.position,i.raw" + join + (" ORDER BY f.rank DESC,f.position" if descending else " ORDER BY f.rank,f.position") + " LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            if len(rows) < limit and offset + len(rows) < matched:
                rows += self.db.execute("SELECT i.position,i.raw FROM items i WHERE " + condition + " AND NOT EXISTS (SELECT 1 FROM fields f WHERE f.port=i.port AND f.name=? AND f.position=i.position AND f.rank IS NOT NULL) ORDER BY i.position LIMIT ? OFFSET ?", [*args, sort, limit-len(rows), max(0, offset-present)]).fetchall()
        else:
            rows = self.db.execute("SELECT i.position,i.raw FROM items i WHERE " + condition + " ORDER BY i.position LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {**metadata, "offset": offset, "limit": limit, "total_items": total, "matched_items": matched,
                "has_more": offset + limit < matched, "items": [json.loads(row[1]) for row in rows], "positions": [row[0] for row in rows]}
