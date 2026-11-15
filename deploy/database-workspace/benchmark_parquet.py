"""Typed, lossless native-import files without CSV multiline boundary inference."""

import csv
import hashlib
import json
import re
from pathlib import Path

from benchmark_import import ident, literal


def headers(table):
    return next(csv.reader([Path(table["header_file"]).read_text().strip()], delimiter="|"))


def column_type(header):
    if re.search(r":(?:START_|END_)?ID\(", header) or header.endswith((":long", ":int")):
        return "BIGINT"
    if header.endswith(":double"):
        return "DOUBLE"
    if header.endswith(":boolean"):
        return "BOOLEAN"
    return "VARCHAR"


def source_signature(table):
    paths = table.get("data_files", [table.get("data_file")])
    return hashlib.sha256(json.dumps([
        table["rows"], Path(table["header_file"]).read_text(),
        [(p, Path(p).stat().st_size, Path(p).stat().st_mtime_ns) for p in paths],
    ]).encode()).hexdigest()


def csv_query(files, names):
    columns = ",".join(f"{literal(name)}:'VARCHAR'" for name in names)
    return (
        f"read_csv([{','.join(literal(p) for p in files)}], header=false, delim='|', "
        f"columns={{{columns}}}, quote='\"', escape='\"', nullstr='', "
        "max_line_size=67108864, strict_mode=true)"
    )


def write_parquet(db, table, destination, *, materialized=False, rows=None):
    names = headers(table)
    if rows is not None:
        types = [column_type(h) for h in names]
        db.execute("CREATE OR REPLACE TEMP TABLE parquet_sample(" + ",".join(
            ident(name) + " " + dtype for name, dtype in zip(names, types)
        ) + ")")
        values = [
            [None if value == "" else int(value) if dtype == "BIGINT"
             else float(value) if dtype == "DOUBLE"
             else value.lower() == "true" if dtype == "BOOLEAN" else value
             for value, dtype in zip(row, types)]
            for row in rows
        ]
        db.executemany("INSERT INTO parquet_sample VALUES (" + ",".join("?" for _ in names) + ")", values)
        query = "SELECT * FROM parquet_sample"
    else:
        if materialized:
            columns = db.execute(f"DESCRIBE {ident(table['name'])}").fetchall()
            expressions = []
            for (column, dtype, *_), name in zip(columns, names, strict=True):
                value = f"to_json({ident(column)})" if any(
                    token in dtype for token in ("[]", "STRUCT", "MAP", "JSON", "UNION")
                ) else ident(column)
                target = column_type(name)
                cast = f"CAST({value} AS {target})"
                if target == "VARCHAR":
                    cast = f"nullif({cast},'')"
                expressions.append(f"{cast} AS {ident(name)}")
            query = f"SELECT {','.join(expressions)} FROM {ident(table['name'])}"
        else:
            source = csv_query(table.get("data_files", [table.get("data_file")]), names)
            query = "SELECT " + ",".join(
                f"CAST({ident(name)} AS {column_type(name)}) AS {ident(name)}" for name in names
            ) + " FROM " + source
    temporary = destination.with_suffix(".partial.parquet")
    db.execute(f"COPY ({query}) TO {literal(temporary)} (FORMAT PARQUET, COMPRESSION SNAPPY, ROW_GROUP_SIZE 65536)")
    expected = len(rows) if rows is not None else table["rows"]
    actual = db.execute("SELECT count(*) FROM read_parquet(?)", [str(temporary)]).fetchone()[0]
    if actual != expected:
        raise RuntimeError(f"Parquet row count differs for {table['name']}: {actual} != {expected}")
    temporary.replace(destination)
