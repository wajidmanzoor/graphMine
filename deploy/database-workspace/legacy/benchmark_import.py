"""Shared, resumable PostgreSQL and Neo4j preparation for published benchmarks.

Run in the import environment with duckdb and psycopg[binary] installed.
Credentials come from GRAPHMINE_DEMO_SQL_PASSWORD, never command arguments.
"""

import csv
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(os.environ.get("GRAPHMINE_LAB_DATA_ROOT", "/data/labdata/wajid/graphmine_data"))
NAMES = {
    "yelp": "Yelp", "movielens-32m": "MovieLens 32M",
    "movielens-genome": "MovieLens Tag Genome", "ontime": "OnTime",
    "stackoverflow": "Stack Overflow", "ldbc-snb": "LDBC SNB",
}
LABELS = {
    "yelp": "GM_Yelp", "movielens-32m": "GM_MovieLens32M",
    "movielens-genome": "GM_MovieLensGenome", "ontime": "GM_OnTime",
    "stackoverflow": "GM_StackOverflow", "ldbc-snb": "GM_LDBC",
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def ident(value):
    return '"' + str(value).replace('"', '""') + '"'


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def postgres():
    return psycopg.connect(
        host=os.environ.get("GRAPHMINE_IMPORT_SQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("GRAPHMINE_DEMO_SQL_PORT", 55432)),
        dbname=os.environ.get("GRAPHMINE_IMPORT_SQL_DATABASE", "graphmine_demo"),
        user=os.environ.get("GRAPHMINE_IMPORT_SQL_USER", "graphmine_admin"),
        password=os.environ["GRAPHMINE_DEMO_SQL_PASSWORD"], autocommit=True,
    )


def ensure_catalog(db):
    db.execute("CREATE SCHEMA IF NOT EXISTS graphmine_catalog")
    db.execute("""
        CREATE TABLE IF NOT EXISTS graphmine_catalog.datasets (
            id text PRIMARY KEY, name text NOT NULL, schema_name text NOT NULL,
            graph_label text NOT NULL, status text NOT NULL,
            manifest jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    db.execute("GRANT USAGE ON SCHEMA graphmine_catalog TO graphmine_reader")
    db.execute("GRANT SELECT ON graphmine_catalog.datasets TO graphmine_reader")
    db.execute("""
        CREATE TABLE IF NOT EXISTS graphmine_catalog.imported_tables (
            dataset_id text NOT NULL, table_name text NOT NULL, fingerprint text NOT NULL,
            record jsonb NOT NULL, PRIMARY KEY(dataset_id,table_name)
        )
    """)

def graph_signature(manifest):
    fields = ("name", "kind", "rows", "key", "labels", "relationship_type", "fingerprint", "columns")
    tables = [{k: t.get(k) for k in fields} for t in manifest.get("tables", [])
              if t["kind"] in {"nodes", "relationships"}]
    tables.sort(key=lambda t: t["name"])
    return hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()


def publish_catalog(db, slug, manifest, status, *, force_status=False):
    if status != "ready" and not force_status:
        previous = db.execute(
            "SELECT status,manifest FROM graphmine_catalog.datasets WHERE id=%s", (slug,)
        ).fetchone()
        if previous and previous[0] == "ready" and graph_signature(previous[1]) == graph_signature(manifest):
            status = "ready"
    db.execute("""
        INSERT INTO graphmine_catalog.datasets(id,name,schema_name,graph_label,status,manifest)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET manifest=excluded.manifest,
            status=excluded.status, updated_at=now()
    """, (slug, NAMES[slug], slug.replace("-", "_"), LABELS[slug], status, Jsonb(manifest)))


class Builder:
    def __init__(self, slug):
        self.slug, self.schema = slug, slug.replace("-", "_")
        self.raw = ROOT / "datasets" / slug / "raw"
        self.directory = ROOT / "imports" / slug
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.directory / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {
            "id": slug, "name": NAMES[slug], "graph_label": LABELS[slug], "tables": [],
            "default_query": f"MATCH p = (a:{LABELS[slug]})-[r]->(b:{LABELS[slug]})\nRETURN p\nLIMIT 1000",
        }
        self.db = duckdb.connect(str(self.directory / "preparation.duckdb"))
        self.db.execute("SET threads=6")
        self.db.execute("SET memory_limit=" + literal(os.environ.get("GRAPHMINE_IMPORT_MEMORY", "12GB")))
        self.db.execute("SET preserve_insertion_order=false")
        self.db.execute("SET temp_directory=" + literal(self.directory / "temp"))
        self.pg = postgres()
        ensure_catalog(self.pg)
        existing = self.pg.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (self.schema,)
        ).fetchone()
        registered = self.pg.execute(
            "SELECT 1 FROM graphmine_catalog.datasets WHERE id=%s", (slug,)
        ).fetchone()
        if existing and not registered:
            raise RuntimeError(f"Refusing to replace an existing schema: {self.schema}")
        self.pg.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
        self.pg.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO graphmine_reader").format(sql.Identifier(self.schema)))
        publish_catalog(self.pg, slug, self.manifest, "importing")

    def log(self, message):
        print(time.strftime("%H:%M:%S"), self.slug, message, flush=True)

    def source(self, filename):
        """Join byte-split originals before parsing; never insert line breaks."""
        direct = self.raw / filename
        if direct.exists():
            if not direct.with_name(direct.name + ".verified.json").exists():
                raise RuntimeError(f"Unverified source: {direct}")
            return direct
        parts = sorted(self.raw.glob(filename + "*part_*"))
        parts = [p for p in parts if not p.name.endswith((".json.verified.json", ".verified.json", ".partial"))]
        if not parts or any(not p.with_name(p.name + ".verified.json").exists() for p in parts):
            raise RuntimeError(f"Complete verified source required: {filename}")
        # Validate the part count against the publisher metadata, including files
        # that have not finished downloading yet.
        metadata = json.loads((self.raw.parent / "dataverse-metadata.json").read_text())
        expected = [
            row["dataFile"].get("originalFileName") or row["dataFile"]["filename"]
            for row in metadata["data"]["latestVersion"]["files"]
        ]
        expected = [name for name in expected if name.startswith(filename) and "part_" in name]
        if {p.name for p in parts} != set(expected):
            raise RuntimeError(f"Still downloading some parts of {filename}")
        joined = self.directory / "joined" / filename
        joined.parent.mkdir(exist_ok=True)
        size = sum(p.stat().st_size for p in parts)
        if not joined.exists() or joined.stat().st_size != size:
            self.log(f"Joining {filename}")
            temporary = joined.with_suffix(joined.suffix + ".partial")
            with temporary.open("wb") as output:
                for part in parts:
                    with part.open("rb") as stream:
                        shutil.copyfileobj(stream, output, 16 * 1024 * 1024)
            temporary.replace(joined)
        return joined

    def complete_csv(self, path):
        """Preserve a publisher-truncated final record separately, without inventing fields."""
        normalized = self.directory / "normalized" / path.name
        receipt = normalized.with_suffix(normalized.suffix + ".json")
        if receipt.exists():
            info = json.loads(receipt.read_text())
            if info["source_bytes"] == path.stat().st_size and normalized.exists() and normalized.stat().st_size == info["complete_bytes"]:
                return normalized
        quote_count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(16 * 1024 * 1024):
                quote_count += chunk.count(b'"')
        if quote_count % 2 == 0:
            return path
        size = path.stat().st_size
        with path.open("rb") as stream:
            start = max(0, size - 32 * 1024 * 1024)
            stream.seek(start)
            tail = stream.read()
        inside, right, boundary = True, len(tail), None
        while right:
            newline = tail.rfind(b"\n", 0, right)
            if newline < 0:
                break
            inside ^= bool(tail[newline + 1:right].count(b'"') % 2)
            if not inside:
                boundary = start + newline + 1
                break
            right = newline
        if boundary is None:
            raise RuntimeError(f"Cannot locate a complete CSV record before the truncated tail: {path}")
        fragment = tail[boundary - start:]
        normalized.parent.mkdir(exist_ok=True)
        with path.open("rb") as stream, normalized.open("wb") as output:
            remaining = boundary
            while remaining:
                chunk = stream.read(min(16 * 1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("Unexpected EOF while preserving complete source records")
                output.write(chunk)
                remaining -= len(chunk)
        quarantine = self.directory / "incomplete-source-records"
        quarantine.mkdir(exist_ok=True)
        (quarantine / (path.name + ".tail")).write_bytes(fragment)
        self.pg.execute("""
            CREATE TABLE IF NOT EXISTS graphmine_catalog.source_fragments (
                dataset_id text NOT NULL, filename text NOT NULL, source_bytes bigint NOT NULL,
                complete_bytes bigint NOT NULL, fragment bytea NOT NULL, reason text NOT NULL,
                PRIMARY KEY(dataset_id,filename)
            )
        """)
        reason = "Published CSV ends inside a quoted record; complete original records imported, incomplete tail preserved."
        self.pg.execute("""
            INSERT INTO graphmine_catalog.source_fragments VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(dataset_id,filename) DO NOTHING
        """, (self.slug, path.name, size, boundary, fragment, reason))
        self.pg.execute("GRANT SELECT ON graphmine_catalog.source_fragments TO graphmine_reader")
        info = {"filename": path.name, "source_bytes": size, "complete_bytes": boundary,
                "incomplete_tail_bytes": len(fragment), "note": reason}
        self.manifest.setdefault("source_notes", [])
        self.manifest["source_notes"] = [r for r in self.manifest["source_notes"] if r["filename"] != path.name] + [info]
        write_json(self.manifest_path, self.manifest)
        write_json(receipt, info)
        self.log(f"Preserved {len(fragment):,} bytes of an incomplete source record from {path.name}")
        return normalized

    def csv(self, filename, repair_truncated_tail=False, **options):
        path = self.source(filename)
        if repair_truncated_tail:
            path = self.complete_csv(path)
        opts = {"header": "true", "all_varchar": "true", "sample_size": "10000",
                "max_line_size": "16777216", **options}
        return f"read_csv({literal(path)}, " + ", ".join(f"{k}={v}" for k, v in opts.items()) + ")"

    def json(self, filename, columns=None):
        path = self.source(filename)
        options = ", maximum_depth=2, sample_size=50000, maximum_object_size=33554432"
        if columns:
            options = ", columns={" + ", ".join(f"{literal(k)}:{literal(v)}" for k, v in columns.items()) + "}, maximum_object_size=33554432"
        return f"read_json({literal(path)}, format='newline_delimited'{options})"

    def materialize(self, name, query):
        self.db.execute(f"CREATE OR REPLACE TABLE {ident(name)} AS {query}")

    def table(self, name, query, *, key=None, labels=None, relation=None, endpoints=None):
        """Persist one canonical table, plus a bulk-import file with the same rows."""
        fingerprint = hashlib.sha256(json.dumps([query, key, labels, relation, endpoints]).encode()).hexdigest()
        old = next((t for t in self.manifest["tables"] if t["name"] == name), None)
        # The receipt commits with COPY. Recover even if the process died before
        # writing its local manifest after a successful PostgreSQL commit.
        receipt = self.pg.execute(
            "SELECT fingerprint,record FROM graphmine_catalog.imported_tables WHERE dataset_id=%s AND table_name=%s",
            (self.slug, name),
        ).fetchone()
        if receipt:
            if receipt[0] != fingerprint:
                raise RuntimeError(f"{name} was already imported with a different definition")
            old = receipt[1]
            self.manifest["tables"] = [t for t in self.manifest["tables"] if t["name"] != name] + [old]
            write_json(self.manifest_path, self.manifest)
        if old and old.get("fingerprint") == fingerprint and old.get("sql_loaded"):
            if old["kind"] in {"nodes", "relationships"} and old.get("graph_export_version") != 2:
                self.reexport_graph(old)
            self.log(f"Already imported {name}: {old['rows']:,} rows")
            return
        if old and old.get("sql_loaded"):
            raise RuntimeError(f"{name} was already imported with a different definition")
        self.log(f"Preparing {name}")
        if key:
            query = f"SELECT row_number() OVER ()::BIGINT AS _gm_node_id, * FROM ({query})"
        self.materialize(name, query)
        columns = self.db.execute(f"DESCRIBE {ident(name)}").fetchall()
        count = self.db.execute(f"SELECT count(*) FROM {ident(name)}").fetchone()[0]
        if key:
            missing = self.db.execute(f"SELECT count(*) FROM {ident(name)} WHERE {ident(key)} IS NULL").fetchone()[0]
            if missing:
                raise RuntimeError(f"{name}: {missing} missing node identifiers")
        # DuckDB structural values become JSON text in both stores.
        projections, column_info = [], []
        for col, dtype, *_ in columns:
            structured = any(token in dtype for token in ("[]", "STRUCT", "MAP", "JSON", "UNION"))
            projections.append(f"to_json({ident(col)})::VARCHAR AS {ident(col)}" if structured else ident(col))
            column_info.append((col, "VARCHAR" if structured else dtype))
        selects = ", ".join(projections)
        raw_file = self.directory / f"{name}.psv"
        quoting = [ident(col) for col, dtype in column_info if dtype == "VARCHAR"]
        quote_option = ", FORCE_QUOTE (" + ",".join(quoting) + ")" if quoting else ""
        self.db.execute(f"COPY (SELECT {selects} FROM {ident(name)}) TO {literal(raw_file)} (FORMAT CSV, DELIMITER '|', HEADER false{quote_option})")
        types = []
        for col, dtype in column_info:
            pg_type = (
                "bigint" if dtype in {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT"}
                else "double precision" if dtype in {"DOUBLE", "FLOAT"} or dtype.startswith("DECIMAL")
                else "boolean" if dtype == "BOOLEAN"
                else "date" if dtype == "DATE"
                else "text"
            )
            types.append((col, pg_type))
        headers = []
        for col, dtype in column_info:
            if col == "_gm_node_id":
                headers.append(f":ID({self.slug}_{name})")
            elif col in {"_gm_start_id", "_gm_end_id"}:
                position = 0 if col == "_gm_start_id" else 1
                kind = "START_ID" if position == 0 else "END_ID"
                headers.append(f":{kind}({self.slug}_{endpoints[position]})")
            else:
                neo_type = "long" if dict(types)[col] == "bigint" else "double" if dict(types)[col] == "double precision" else "boolean" if dtype == "BOOLEAN" else "date" if dtype == "DATE" else "string"
                headers.append(f"{col}:{neo_type}")
        header_file = self.directory / f"{name}.header"
        with header_file.open("w") as stream:
            csv.writer(stream, delimiter="|").writerow(headers)
        record = {
            "name": name, "rows": count, "columns": [{"name": c, "type": t} for c, t in types],
            "kind": "nodes" if key else "relationships" if relation else "table",
            "labels": (labels or []) + ([LABELS[self.slug]] if key else []),
            "relationship_type": relation, "key": key,
            "data_file": str(raw_file), "header_file": str(header_file),
            "sql_loaded": True, "fingerprint": fingerprint,
            "graph_export_version": 2,
        }
        table = sql.Identifier(self.schema, name)
        self.log(f"Loading PostgreSQL {name}: {count:,} rows")
        line_count, carriage_returns = 0, False
        with self.pg.transaction():
            self.pg.execute(sql.SQL("CREATE TABLE {} ({})").format(
                table, sql.SQL(",").join(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)) for c, t in types),
            ))
            with self.pg.cursor() as cursor:
                with cursor.copy(sql.SQL("COPY {} FROM STDIN (FORMAT CSV, DELIMITER '|')").format(table)) as copy:
                    with raw_file.open("rb") as stream:
                        while chunk := stream.read(8 * 1024 * 1024):
                            copy.write(chunk)
                            line_count += chunk.count(b"\n")
                            carriage_returns |= b"\r" in chunk
                if cursor.rowcount != count:
                    raise RuntimeError(f"PostgreSQL copied {cursor.rowcount} instead of {count} rows")
            if key:
                self.pg.execute(sql.SQL("CREATE UNIQUE INDEX ON {} ({})").format(table, sql.Identifier(key)))
            self.pg.execute(sql.SQL("GRANT SELECT ON {} TO graphmine_reader").format(table))
            self.pg.execute(sql.SQL("ANALYZE {}").format(table))
            record["multiline"] = line_count > count or carriage_returns
            self.pg.execute(
                "INSERT INTO graphmine_catalog.imported_tables VALUES (%s,%s,%s,%s)",
                (self.slug, name, fingerprint, Jsonb(record)),
            )
        self.manifest["tables"] = [t for t in self.manifest["tables"] if t["name"] != name] + [record]
        write_json(self.manifest_path, self.manifest)
        publish_catalog(self.pg, self.slug, self.manifest, "importing")
        self.log(f"Imported {name}: {count:,} rows")

    def reexport_graph(self, record):
        """Change only CSV quoting; keep SQL rows and graph identifiers unchanged."""
        name = record["name"]
        columns = self.db.execute(f"DESCRIBE {ident(name)}").fetchall()
        projections, quoting = [], []
        for column, dtype, *_ in columns:
            structured = any(token in dtype for token in ("[]", "STRUCT", "MAP", "JSON", "UNION"))
            projections.append(f"to_json({ident(column)})::VARCHAR AS {ident(column)}" if structured else ident(column))
            if structured or dtype == "VARCHAR":
                quoting.append(ident(column))
        quote_option = ", FORCE_QUOTE (" + ",".join(quoting) + ")" if quoting else ""
        path = Path(record["data_file"])
        temporary = path.with_suffix(".reexport")
        self.manifest["prepared"] = False
        write_json(self.manifest_path, self.manifest)
        self.log(f"Preparing native graph CSV for {name}")
        self.db.execute(
            f"COPY (SELECT {','.join(projections)} FROM {ident(name)}) TO {literal(temporary)} "
            f"(FORMAT CSV, DELIMITER '|', HEADER false{quote_option})"
        )
        line_count, carriage_returns = 0, False
        with temporary.open("rb") as stream:
            while chunk := stream.read(16 * 1024 * 1024):
                line_count += chunk.count(b"\n")
                carriage_returns |= b"\r" in chunk
        temporary.replace(path)
        record.update(graph_export_version=2, multiline=line_count > record["rows"] or carriage_returns)
        write_json(self.manifest_path, self.manifest)
        publish_catalog(self.pg, self.slug, self.manifest, "preparing_graph")

    def relationship(self, name, query, source, target, source_key, target_key, kind):
        """Use the publisher's MATCH semantics: both endpoints must exist."""
        source_table, source_id = source
        target_table, target_id = target
        joined = (
            f"SELECT a._gm_node_id AS _gm_start_id, b._gm_node_id AS _gm_end_id, r.* "
            f"FROM ({query}) r JOIN {ident(source_table)} a ON cast(r.{ident(source_key)} AS VARCHAR)=cast(a.{ident(source_id)} AS VARCHAR) "
            f"JOIN {ident(target_table)} b ON cast(r.{ident(target_key)} AS VARCHAR)=cast(b.{ident(target_id)} AS VARCHAR)"
        )
        self.table(name, joined, relation=kind, endpoints=(source_table, target_table))

    def relational_only(self, name):
        """Retain a published variant as a SQL table without duplicate graph nodes."""
        record = next(t for t in self.manifest["tables"] if t["name"] == name)
        record.update(kind="table", labels=[])
        write_json(self.manifest_path, self.manifest)
        publish_catalog(self.pg, self.slug, self.manifest, "importing")

    def finish(self):
        self.manifest["node_count"] = sum(t["rows"] for t in self.manifest["tables"] if t["kind"] == "nodes")
        self.manifest["relationship_count"] = sum(t["rows"] for t in self.manifest["tables"] if t["kind"] == "relationships")
        self.manifest["row_count"] = sum(t["rows"] for t in self.manifest["tables"])
        self.manifest["prepared"] = True
        write_json(self.manifest_path, self.manifest)
        publish_catalog(self.pg, self.slug, self.manifest, "preparing_graph")
        self.db.execute("CHECKPOINT")
        self.db.close()
        self.pg.close()
        self.log("PostgreSQL import complete; graph files ready")
