"""Load the complete LDBC BI SF100 initial snapshot, preserving source columns."""

import concurrent.futures
import csv
import gzip
import json
import io
from pathlib import Path

from psycopg import sql

from benchmark_import import ROOT, LABELS, NAMES, ensure_catalog, postgres, publish_catalog, write_json

SLUG = "ldbc-snb"
DIRECTORY = ROOT / "imports" / SLUG
SOURCE = ROOT / "datasets" / SLUG / "extracted" / "bi-sf100-composite-projected-fk" / "graphs" / "csv" / "bi" / "composite-projected-fk" / "initial_snapshot"
NODE_LABELS = {
    "Organisation": ["Organisation"], "Place": ["Place"], "TagClass": ["TagClass"],
    "Tag": ["Tag"], "Person": ["Person"], "Forum": ["Forum"],
    "Comment": ["Message", "Comment"], "Post": ["Message", "Post"],
}
RELATIONSHIPS = {
    "isPartOf": "IS_PART_OF", "isSubclassOf": "IS_SUBCLASS_OF",
    "isLocatedIn": "IS_LOCATED_IN", "hasType": "HAS_TYPE",
    "hasCreator": "HAS_CREATOR", "replyOf": "REPLY_OF",
    "containerOf": "CONTAINER_OF", "hasMember": "HAS_MEMBER",
    "hasModerator": "HAS_MODERATOR", "hasTag": "HAS_TAG",
    "hasInterest": "HAS_INTEREST", "knows": "KNOWS", "likes": "LIKES",
    "studyAt": "STUDY_AT", "workAt": "WORK_AT",
}


def group(name):
    return {"Country": "Place", "City": "Place", "University": "Organisation", "Company": "Organisation"}.get(name, name)


def prepare(db):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    ensure_catalog(db)
    registered = db.execute("SELECT 1 FROM graphmine_catalog.datasets WHERE id=%s", (SLUG,)).fetchone()
    exists = db.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name='ldbc_snb'").fetchone()
    if exists and not registered:
        raise RuntimeError("Refusing to replace an existing ldbc_snb schema")
    db.execute("CREATE SCHEMA IF NOT EXISTS ldbc_snb")
    db.execute("GRANT USAGE ON SCHEMA ldbc_snb TO graphmine_reader")
    db.execute("""
        CREATE TABLE IF NOT EXISTS graphmine_catalog.imported_files (
            dataset_id text NOT NULL, table_name text NOT NULL, filename text NOT NULL,
            row_count bigint NOT NULL, source_size bigint NOT NULL,
            PRIMARY KEY(dataset_id,table_name,filename)
        )
    """)
    tables = []
    previous_path = DIRECTORY / "manifest.json"
    previous = {t["name"]: t for t in json.loads(previous_path.read_text()).get("tables", [])} if previous_path.exists() else {}
    for section in ["static", "dynamic"]:
        for directory in sorted((SOURCE / section).iterdir()):
            if not directory.is_dir():
                continue
            files = sorted(directory.glob("part-*.csv.gz"))
            if not files:
                continue
            with gzip.open(files[0], "rt") as stream:
                columns = next(csv.reader(stream, delimiter="|"))
            name = directory.name
            is_node = name in NODE_LABELS
            node_types = None if is_node else name.split("_")
            if not is_node and len(node_types) != 3:
                raise RuntimeError(f"Unknown LDBC relationship: {name}")
            ids = [i for i, c in enumerate(columns) if c.lower().endswith("id")]
            header, pg_columns = [], []
            for i, column in enumerate(columns):
                dtype = "bigint" if column.lower().endswith("id") or column in {"length", "classYear", "workFrom"} else "date" if column == "birthday" else "timestamptz" if column == "creationDate" else "text"
                pg_columns.append((column, dtype))
                if is_node and column == "id":
                    header.append(f"id:ID(ldbc_{name})")
                elif is_node and column == "type":
                    header.append(":LABEL")
                elif not is_node and i in ids:
                    index = ids.index(i)
                    kind = "START_ID" if index == 0 else "END_ID"
                    target = node_types[0 if index == 0 else 2]
                    header.append(f":{kind}(ldbc_{group(target)})")
                else:
                    neo_type = "long" if dtype == "bigint" else "date" if dtype == "date" else "datetime" if dtype == "timestamptz" else "string[]" if name == "Person" and column in {"language", "email"} else "string"
                    header.append(f"{column}:{neo_type}")
            target = DIRECTORY / name
            target.mkdir(exist_ok=True)
            header_file = target / "header.psv"
            stream = io.StringIO(newline="")
            csv.writer(stream, delimiter="|").writerow(header)
            if not header_file.exists() or header_file.read_bytes() != stream.getvalue().encode():
                header_file.write_bytes(stream.getvalue().encode())
            db.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
                sql.Identifier("ldbc_snb", name),
                sql.SQL(",").join(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)) for c, t in pg_columns),
            ))
            db.execute(sql.SQL("GRANT SELECT ON {} TO graphmine_reader").format(sql.Identifier("ldbc_snb", name)))
            tables.append({
                **previous.get(name, {}),
                "name": name, "rows": previous.get(name, {}).get("rows", 0), "columns": [{"name": c, "type": t} for c, t in pg_columns],
                "kind": "nodes" if is_node else "relationships",
                "labels": NODE_LABELS[name] + [LABELS[SLUG]] if is_node else [],
                "relationship_type": None if is_node else RELATIONSHIPS[node_types[1]],
                "header_file": str(header_file),
                "data_files": [str(target / (p.name.removesuffix(".gz") + ".psv")) for p in files],
                "source_files": [str(p) for p in files],
                "key": "id" if is_node else None,
            })
    if len(tables) != 31:
        raise RuntimeError(f"Expected all 31 LDBC table groups, found {len(tables)}")
    return tables


def transfer(job):
    table, source, destination = job
    source, destination = Path(source), Path(destination)
    with postgres() as db:
        receipt = db.execute("""
            SELECT row_count,source_size FROM graphmine_catalog.imported_files
            WHERE dataset_id=%s AND table_name=%s AND filename=%s
        """, (SLUG, table, source.name)).fetchone()
        if receipt and receipt[1] != source.stat().st_size:
            raise RuntimeError(f"Source changed after import: {source}")
        if receipt and destination.exists():
            return table, receipt[0]
        temporary = destination.with_suffix(".partial")
        with gzip.open(source, "rb") as stream, temporary.open("wb") as output:
            stream.readline()  # Every published part has its own column header.
            if receipt:
                import shutil
                shutil.copyfileobj(stream, output, 8 * 1024 * 1024)
                rows = receipt[0]
            else:
                with db.transaction():
                    with db.cursor() as cursor:
                        with cursor.copy(sql.SQL("COPY {} FROM STDIN (FORMAT CSV, DELIMITER '|')").format(sql.Identifier("ldbc_snb", table))) as copy:
                            while chunk := stream.read(4 * 1024 * 1024):
                                copy.write(chunk)
                                output.write(chunk)
                        rows = cursor.rowcount
                    db.execute("""
                        INSERT INTO graphmine_catalog.imported_files VALUES (%s,%s,%s,%s,%s)
                    """, (SLUG, table, source.name, rows, source.stat().st_size))
        temporary.replace(destination)
        return table, rows


def main():
    with postgres() as db:
        tables = prepare(db)
        manifest = {
            "id": SLUG, "name": NAMES[SLUG], "graph_label": LABELS[SLUG], "tables": tables,
            "edition": "BI SF100 initial snapshot; insert/delete streams retained in the source archive",
            "default_query": "MATCH p = (a:GM_LDBC:Person)-[:KNOWS]->(b:GM_LDBC:Person)\nRETURN p\nLIMIT 1000",
        }
        publish_catalog(db, SLUG, manifest, "importing")
        jobs = [(table["name"], source, destination) for table in tables for source, destination in zip(table["source_files"], table["data_files"])]
        totals = {table["name"]: 0 for table in tables}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            pending = [pool.submit(transfer, job) for job in sorted(jobs, key=lambda j: Path(j[1]).stat().st_size, reverse=True)]
            for completed, future in enumerate(concurrent.futures.as_completed(pending), 1):
                name, rows = future.result()
                totals[name] += rows
                if completed % 25 == 0 or completed == len(jobs):
                    print(f"Imported {completed}/{len(jobs)} LDBC parts; {sum(totals.values()):,} rows", flush=True)
        for table in tables:
            table["rows"] = totals[table["name"]]
            table["sql_loaded"] = True
            db.execute(sql.SQL("ANALYZE {}").format(sql.Identifier("ldbc_snb", table["name"])))
        manifest["node_count"] = sum(t["rows"] for t in tables if t["kind"] == "nodes")
        manifest["relationship_count"] = sum(t["rows"] for t in tables if t["kind"] == "relationships")
        manifest["row_count"] = sum(totals.values())
        manifest["prepared"] = True
        write_json(DIRECTORY / "manifest.json", manifest)
        publish_catalog(db, SLUG, manifest, "preparing_graph")
        print("LDBC PostgreSQL import complete:", manifest["row_count"], "rows", flush=True)


if __name__ == "__main__":
    main()
