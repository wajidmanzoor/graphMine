#!/usr/bin/env python3
"""Prepare disposable paper inputs using the author's loaders and original data.

Never invent missing reference judgments or substitute a synthetic benchmark.
OpenFlights downloading is explicit and records its exact source revision.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/tento"


def execute(connection, script):
    value = connection.execute(script)
    for result in value if isinstance(value, list) else [value]:
        result.close()


def build(path, script):
    from graphmine_agent.semantic_engine import load_engine
    if path.exists():
        raise ValueError(f"Refusing to overwrite an existing paper database: {path}")
    engine = load_engine().module
    db = engine.Database(str(path), buffer_pool_size=256 * 1024 * 1024, max_num_threads=2, backend="pybind")
    connection = engine.Connection(db, num_threads=2)
    try:
        execute(connection, script)
    finally:
        connection.close(); db.close()


def export_flights(source, target):
    """Keep the author's route values, using the scorer's export column names."""
    with source.open(newline="") as incoming, target.open("w", newline="") as outgoing:
        writer = csv.DictWriter(outgoing, fieldnames=["src", "dst"])
        writer.writeheader()
        for row in csv.DictReader(incoming):
            writer.writerow({"src": row["from"], "dst": row["to"]})


def prepare(destination, download=False):
    destination.mkdir(parents=True, exist_ok=True)
    demo, export = destination / "demo", destination / "paper_eval/export"
    demo.mkdir(exist_ok=True); export.mkdir(parents=True, exist_ok=True)
    movies = destination / "semantic_movies"
    subprocess.run([sys.executable, str(SOURCE / "ladybug/scripts/llm/load_semantic_movies.py"),
                    "--source", str(SOURCE / "ipdb/benchmark/semantic_benchmark/data"), "--out", str(movies)], check=True)
    build(demo / "semantic_movies.lbdb", (movies / "load.cypher").read_text())
    for name in ("movie.csv", "person.csv"):
        shutil.copy2(movies / name, export / name)
    edges = {row["from"]: row["to"] for row in csv.DictReader((movies / "reviews.csv").open())}
    with (movies / "review.csv").open() as source, (export / "review.csv").open("w") as target:
        rows = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=[*rows.fieldnames, "movie_id"]); writer.writeheader()
        for row in rows: writer.writerow({**row, "movie_id": edges[row["id"]]})
    with (movies / "worked_on.csv").open() as source, (export / "worked_on.csv").open("w") as target:
        writer = csv.DictWriter(target, fieldnames=["person_id", "movie_id", "role", "note"]); writer.writeheader()
        for row in csv.DictReader(source):
            writer.writerow({"person_id": row["from"], "movie_id": row["to"], "role": row["role"], "note": row["note"]})
    # W19 asks llm_build_graph to design its own schema. Precreating the older
    # quickstart's Professor(field) table collides with generated properties.
    build(demo / "kg.lbdb", "RETURN 1;")
    origins = {"semantic_movies": {"repository_commit": subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip(), "loader": "load_semantic_movies.py"}}
    origins["kg"] = {"workload": "W19", "initial_state": "empty database; model designs the schema"}
    if download:
        revision = subprocess.check_output(["git", "ls-remote", "https://github.com/jpatokal/openflights.git", "HEAD"], text=True).split()[0]
        flights = destination / "openflights"; flights.mkdir(exist_ok=True)
        for name in ("airports.dat", "routes.dat"):
            url = f"https://raw.githubusercontent.com/jpatokal/openflights/{revision}/data/{name}"
            with urlopen(url, timeout=30) as response:
                content = response.read(20 * 1024 * 1024 + 1)
            if len(content) > 20 * 1024 * 1024: raise ValueError("OpenFlights input exceeds the download budget")
            (flights / name).write_bytes(content)
        subprocess.run([sys.executable, str(SOURCE / "ladybug/scripts/llm/load_openflights.py"),
                        "--source", str(flights), "--out", str(flights / "csv")], check=True)
        load = (flights / "csv/load.cypher").read_text()
        build(demo / "flights.lbdb", load)
        build(demo / "flights_country.lbdb", load + "\nCREATE NODE TABLE Country(name STRING PRIMARY KEY);\n"
              "MATCH (a:Airport) WHERE a.gt_country IS NOT NULL AND a.gt_country <> '' WITH DISTINCT a.gt_country AS name CREATE (:Country {name:name});")
        shutil.copy2(flights / "csv/airport.csv", export / "airport.csv")
        export_flights(flights / "csv/flight.csv", export / "flight.csv")
        codes = flights / "codes.csv"
        with codes.open("w") as target, (export / "airport.csv").open() as source:
            writer = csv.writer(target); writer.writerow(["code"])
            writer.writerows([row["code"]] for row in csv.DictReader(source))
        build(demo / "flights_code.lbdb", "CREATE NODE TABLE Airport(code STRING PRIMARY KEY);\n"
              "CREATE REL TABLE FLIGHT(FROM Airport TO Airport);\n"
              f"COPY Airport FROM '{codes}' (HEADER=true);\nCOPY FLIGHT FROM '{flights / 'csv/flight.csv'}' (HEADER=true);")
        origins["openflights"] = {"repository": "https://github.com/jpatokal/openflights", "commit": revision, "license": "ODbL"}
    report = {"origins": origins, "files": {str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(destination.rglob("*")) if path.is_file()},
              "unavailable": ["author's LDBC SF0.1 sample", "author's reference judgments", "SemBench sf500 image sample and vectors", "Visual Genome vg100 sample"]}
    if download:
        report["scorer_export_columns"] = {"flight.csv": {"src": "original from", "dst": "original to"}}
    (destination / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--download-openflights", action="store_true")
    args = parser.parse_args()
    report = prepare(args.data_root.resolve(), args.download_openflights)
    print(json.dumps({"origins": report["origins"], "files": len(report["files"]), "unavailable": report["unavailable"]}, indent=2))
