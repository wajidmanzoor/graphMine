"""Prepare and verify native Parquet input for one imported benchmark."""

import argparse
import json
import os
import time

import duckdb

from benchmark_import import ROOT, NAMES, literal, postgres, publish_catalog, write_json
from benchmark_parquet import source_signature, write_parquet


def main(slug):
    directory = ROOT / "imports" / slug
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get("prepared"):
        raise RuntimeError("Complete the PostgreSQL preparation first")
    materialized = slug != "ldbc-snb"
    db = duckdb.connect(str(directory / "preparation.duckdb"), read_only=True) if materialized else duckdb.connect()
    db.execute("SET threads=8")
    db.execute("SET memory_limit=" + literal(os.environ.get("GRAPHMINE_IMPORT_MEMORY", "24GB")))
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=" + literal(directory / "parquet-temp"))
    with postgres() as pg:
        for table in manifest["tables"]:
            if table["kind"] not in {"nodes", "relationships"}:
                continue
            destination = directory / (table["name"] + ".parquet")
            signature = source_signature(table)
            if (table.get("parquet_signature") == signature and destination.is_file()
                    and destination.stat().st_size == table.get("parquet_bytes")):
                continue
            print(time.strftime("%H:%M:%S"), slug, table["name"], f"{table['rows']:,} rows", flush=True)
            write_parquet(db, table, destination, materialized=materialized)
            table.update(parquet_file=str(destination), parquet_signature=signature,
                         parquet_bytes=destination.stat().st_size)
            write_json(manifest_path, manifest)
            publish_catalog(pg, slug, manifest, "preparing_graph")
    db.close()
    print(time.strftime("%H:%M:%S"), slug, "Parquet inputs verified", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=list(NAMES))
    main(parser.parse_args().dataset)
