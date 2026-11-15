"""Build all prepared benchmark graphs in a separate store, then install it.

The running graph stays available during the bulk build. Installation retains
the previous store and restores it if the new store cannot be verified.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from neo4j import GraphDatabase

from benchmark_import import ROOT, NAMES, postgres, publish_catalog, write_json, graph_signature
from benchmark_parquet import source_signature, write_parquet

BRANCH = Path(__file__).resolve().parents[2]
NEO_HOME = Path(os.environ.get("GRAPHMINE_NEO4J_HOME", BRANCH / ".database-workspace" / "neo4j-community-5.26.32"))
NEO_ROOT = Path(os.environ.get("GRAPHMINE_NEO4J_ROOT", ROOT / "databases" / "neo4j"))
STAGING = NEO_ROOT / "benchmark-build"
JAVA = os.environ.get("JAVA_HOME", "/home/wajid/projects/graphDatabaseAgent/validation/outer_integrations/deps/jdk/usr/lib/jvm/java-17-openjdk-amd64")
SERVICE = os.environ.get("GRAPHMINE_NEO4J_SERVICE", "graphmine-neo4j")


def restore_installed_catalog(receipt):
    """Repair readiness after interrupted preparation without reinstalling."""
    manifests = [json.loads((ROOT / "imports" / slug / "manifest.json").read_text()) for slug in NAMES]
    signatures = {m["id"]: graph_signature(m) for m in manifests}
    if "graph_signatures" not in receipt:
        build = json.loads((STAGING / "build-complete.json").read_text())
        digest = hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest()
        if build["manifests"] != digest:
            raise RuntimeError("Legacy installation inputs changed; verify the installed store before restoring readiness")
    elif receipt["graph_signatures"] != signatures:
        raise RuntimeError("Prepared graph inputs changed since installation")
    with driver() as graph, graph.session() as session:
        nodes = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
        edges = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
        if (nodes, edges) != (receipt["nodes"], receipt["relationships"]):
            raise RuntimeError("The installed graph differs from its installation receipt")
        for manifest in manifests:
            label = manifest["graph_label"]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
                raise RuntimeError("Invalid dataset label")
            count = session.run(f"MATCH (n:{label}) RETURN count(n) AS count").single()["count"]
            if count != manifest["node_count"]:
                raise RuntimeError(f"Installed node count differs for {manifest['id']}")
    with postgres() as db, db.transaction():
        for manifest in manifests:
            publish_catalog(db, manifest["id"], manifest, "ready")


def driver():
    return GraphDatabase.driver(
        f"bolt://127.0.0.1:{os.environ.get('GRAPHMINE_DEMO_BOLT_PORT', '17687')}",
        auth=("neo4j", os.environ["GRAPHMINE_DEMO_NEO4J_PASSWORD"]),
    )


def save_demo():
    directory = ROOT / "imports" / "existing-graph"
    directory.mkdir(exist_ok=True)
    with driver() as graph, graph.session() as session:
        nodes = list(session.run("MATCH (n) RETURN id(n) AS key, labels(n) AS labels, properties(n) AS props LIMIT 100001"))
        edges = list(session.run("MATCH (a)-[r]->(b) RETURN id(a) AS source,id(b) AS target,type(r) AS kind,properties(r) AS props LIMIT 100001"))
        schema = [row["createStatement"] for row in session.run(
            "SHOW CONSTRAINTS YIELD createStatement RETURN createStatement"
        )] + [row["createStatement"] for row in session.run(
            "SHOW INDEXES YIELD type,owningConstraint,createStatement "
            "WHERE type <> 'LOOKUP' AND owningConstraint IS NULL RETURN createStatement"
        )]
        schema.sort()
    if len(nodes) > 100000 or len(edges) > 100000:
        raise RuntimeError("Existing graph is larger than the migration snapshot budget")
    nodes.sort(key=lambda row: row["key"])
    edges.sort(key=lambda row: (row["source"], row["target"], row["kind"],
                               json.dumps(row["props"], sort_keys=True, default=str)))
    groups = []
    for kind, rows in [("nodes", nodes), ("relationships", edges)]:
        names = sorted({key for row in rows for key in row["props"]})
        types = {}
        for name in names:
            value = next((row["props"][name] for row in rows if row["props"].get(name) is not None), "")
            types[name] = "boolean" if type(value) is bool else "long" if type(value) is int else "double" if type(value) is float else "string"
        header = [":ID(existing)", ":LABEL"] if kind == "nodes" else [":START_ID(existing)", ":END_ID(existing)", ":TYPE"]
        header += [f"{name}:{types[name]}" for name in names]
        data_path, header_path = directory / f"{kind}.psv", directory / f"{kind}.header"
        with header_path.open("w") as stream:
            csv.writer(stream, delimiter="|").writerow(header)
        with data_path.open("w") as stream:
            writer = csv.writer(stream, delimiter="|", quoting=csv.QUOTE_ALL)
            for row in rows:
                prefix = [row["key"], ";".join(row["labels"])] if kind == "nodes" else [row["source"], row["target"], row["kind"]]
                values = [row["props"].get(name, "") for name in names]
                writer.writerow(prefix + [str(v).lower() if type(v) is bool else v for v in values])
        parquet_path = directory / f"{kind}.parquet"
        with duckdb.connect() as db:
            write_parquet(db, {"name": "existing_" + kind, "rows": len(rows),
                              "header_file": str(header_path), "data_file": str(data_path)},
                          parquet_path)
        groups.append(f"--{kind}={parquet_path}")
    digest = hashlib.sha256()
    write_json(directory / "schema.json", schema)
    digest.update(json.dumps(schema).encode())
    for kind in ["nodes", "relationships"]:
        digest.update((directory / f"{kind}.psv").read_bytes())
        digest.update((directory / f"{kind}.header").read_bytes())
    return groups, len(nodes), len(edges), schema, digest.hexdigest()


def validate_input_formats(manifests):
    """Exercise every table's actual values and header through the native parser."""
    csv.field_size_limit(64 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix="format-check-", dir=STAGING) as temporary:
        directory = Path(temporary)
        groups, ids = [], {}
        tables = [table for manifest in manifests for table in manifest["tables"]
                  if table["kind"] in {"nodes", "relationships"}]
        tables.sort(key=lambda table: table["kind"] != "nodes")
        for index, table in enumerate(tables):
            header = next(csv.reader([Path(table["header_file"]).read_text().strip()], delimiter="|"))
            rows = []
            for path in table.get("data_files", [table.get("data_file")]):
                with open(path, newline="") as stream:
                    for row in csv.reader(stream, delimiter="|"):
                        rows.append(row)
                        if len(rows) == 5:
                            break
                if len(rows) == 5:
                    break
            if not rows:
                continue
            for position, field in enumerate(header):
                if match := re.search(r":ID\(([^)]+)\)", field):
                    ids[match[1]] = rows[0][position]
                elif match := re.search(r":(?:START|END)_ID\(([^)]+)\)", field):
                    # The small parser check uses known endpoints; the full
                    # import below validates every original endpoint.
                    for row in rows:
                        row[position] = ids[match[1]]
            data = directory / f"{index}.parquet"
            with duckdb.connect() as db:
                write_parquet(db, table, data, rows=rows)
            labels = ":".join(table["labels"]) if table["kind"] == "nodes" else table["relationship_type"]
            groups.append(f"--{table['kind']}={labels}={data}")
        config = directory / "import.conf"
        config.write_text(
            f"server.directories.data={directory}/data\nserver.directories.logs={directory}/logs\n"
            "server.memory.heap.initial_size=512m\nserver.memory.heap.max_size=1g\n"
            "server.memory.pagecache.size=128m\n"
        )
        with (STAGING / "format-check.log").open("w") as log:
            subprocess.run([
                str(NEO_HOME / "bin/neo4j-admin"), "database", "import", "full", "neo4j",
                f"--additional-config={config}", "--input-type=parquet", "--id-type=INTEGER",
                "--array-delimiter=;", "--bad-tolerance=0", "--ignore-empty-strings=true",
                "--threads=2", "--max-off-heap-memory=1g",
                f"--report-file={directory}/report.txt", *groups,
            ], env={**os.environ, "JAVA_HOME": JAVA}, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(f"Native parser check passed for {len(groups)} graph tables", flush=True)


def main():
    if (STAGING / "installation-complete.json").exists():
        restore_installed_catalog(json.loads((STAGING / "installation-complete.json").read_text()))
        print("The installed graph was verified and dataset readiness restored.", flush=True)
        return
    manifests = []
    for slug in NAMES:
        path = ROOT / "imports" / slug / "manifest.json"
        if not path.exists():
            raise RuntimeError(f"Dataset preparation has not finished: {slug}")
        manifest = json.loads(path.read_text())
        if not manifest.get("prepared"):
            raise RuntimeError(f"Dataset preparation has not finished: {slug}")
        for table in manifest["tables"]:
            if table["kind"] not in {"nodes", "relationships"}:
                continue
            path = Path(table.get("parquet_file", ""))
            if (not path.is_file() or path.stat().st_size != table.get("parquet_bytes")
                    or table.get("parquet_signature") != source_signature(table)):
                raise RuntimeError(f"Native Parquet export needs preparing: {slug}/{table['name']}")
        manifests.append(manifest)
    marker = STAGING / ".graphmine-import"
    if STAGING.exists() and not marker.exists():
        raise RuntimeError("Refusing to overwrite an unrecognized staging directory")
    STAGING.mkdir(exist_ok=True)
    marker.write_text("GraphMine benchmark bulk import staging\n")
    receipt = STAGING / "build-complete.json"
    args, old_nodes, old_edges, old_schema, demo_digest = save_demo()
    expected_nodes = old_nodes + sum(m["node_count"] for m in manifests)
    expected_edges = old_edges + sum(m["relationship_count"] for m in manifests)
    build_identity = {
        "nodes": expected_nodes, "relationships": expected_edges, "existing_graph": demo_digest,
        "manifests": hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest(),
    }
    if receipt.exists() and json.loads(receipt.read_text()) != build_identity:
        raise RuntimeError("The saved build belongs to different inputs; refusing to install a stale graph")
    for manifest in manifests:
        for table in manifest["tables"]:
            kind = table["kind"]
            if kind not in {"nodes", "relationships"}:
                continue
            labels = ":".join(table["labels"]) if kind == "nodes" else table["relationship_type"]
            args.append(f"--{kind}={labels}=" + table["parquet_file"])
    config = STAGING / "import.conf"
    config.write_text(
        f"server.directories.data={STAGING}/data\nserver.directories.logs={STAGING}/logs\n"
        "server.memory.heap.initial_size=1g\n"
        f"server.memory.heap.max_size={os.environ.get('GRAPHMINE_IMPORT_HEAP', '24g')}\n"
        "server.memory.pagecache.size=1g\n"
        # Parquet decompression uses direct buffers outside the importer's
        # off-heap budget. Allow the JVM to reclaim those buffers under pressure.
        "server.jvm.additional=-XX:-DisableExplicitGC\n"
        f"server.jvm.additional=-XX:MaxDirectMemorySize={os.environ.get('GRAPHMINE_IMPORT_DIRECT_MEMORY', '64g')}\n"
    )
    command = [
        str(NEO_HOME / "bin/neo4j-admin"), "database", "import", "full", "neo4j",
        f"--additional-config={config}", "--input-type=parquet", "--id-type=INTEGER",
        "--array-delimiter=;", "--bad-tolerance=0", "--skip-bad-relationships=false",
        "--skip-duplicate-nodes=false", "--strict=true", "--ignore-empty-strings=true",
        f"--threads={os.environ.get('GRAPHMINE_IMPORT_THREADS', '48')}",
        f"--max-off-heap-memory={os.environ.get('GRAPHMINE_IMPORT_OFF_HEAP', '96g')}",
        f"--report-file={STAGING}/import-report.txt", "--overwrite-destination=true",
        "--verbose", *args,
    ]
    if not receipt.exists():
        validate_input_formats(manifests)
        print(f"Building {expected_nodes:,} nodes and {expected_edges:,} relationships in a separate store", flush=True)
        result = subprocess.run(command, env={**os.environ, "JAVA_HOME": JAVA})
        if result.returncode:
            raise RuntimeError(f"Neo4j import failed with exit code {result.returncode}; see the importer output above")
        write_json(receipt, build_identity)
    if save_demo()[-1] != demo_digest:
        raise RuntimeError("The existing graph changed during the build; it has been left running unchanged")
    previous = NEO_ROOT / ("before-benchmarks-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    active = NEO_ROOT / "data"
    print("Bulk build complete. Installing the verified store; old store will be retained.", flush=True)
    subprocess.run(["systemctl", "--user", "stop", SERVICE], check=True)
    installed = False
    old_moved = False
    try:
        # Retain the system registry and authentication database, while replacing
        # only the graph store that was explicitly rebuilt.
        for relative in ["databases/system", "transactions/system", "dbms"]:
            source = active / relative
            if source.exists():
                shutil.copytree(source, STAGING / "data" / relative, dirs_exist_ok=True)
        if (active / "server_id").exists():
            shutil.copy2(active / "server_id", STAGING / "data/server_id")
        active.rename(previous)
        old_moved = True
        (STAGING / "data").rename(active)
        installed = True
        subprocess.run(["systemctl", "--user", "start", SERVICE], check=True)
        error = None
        for attempt in range(60):
            try:
                with driver() as graph, graph.session() as session:
                    actual_nodes = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
                    actual_edges = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
                    if (actual_nodes, actual_edges) != (expected_nodes, expected_edges):
                        raise RuntimeError(f"Imported counts differ: {actual_nodes}, {actual_edges}")
                    for manifest in manifests:
                        label = manifest["graph_label"]
                        count = session.run(f"MATCH (n:{label}) RETURN count(n) AS count").single()["count"]
                        if count != manifest["node_count"]:
                            raise RuntimeError(f"Node count mismatch for {manifest['id']}: {count}")
                        count = session.run(
                            f"MATCH (:{label})-[r]->() RETURN count(r) AS count"
                        ).single()["count"]
                        if count != manifest["relationship_count"]:
                            raise RuntimeError(f"Relationship count mismatch for {manifest['id']}: {count}")
                error = None
                break
            except Exception as exc:
                error = exc
                time.sleep(2)
        if error:
            raise error
        with driver() as graph, graph.session() as session:
            for statement in old_schema:
                session.run(statement).consume()
        with postgres() as db:
            with db.transaction():
                for manifest in manifests:
                    publish_catalog(db, manifest["id"], manifest, "ready")
        write_json(STAGING / "installation-complete.json", {
            "nodes": expected_nodes, "relationships": expected_edges,
            "previous_store": str(previous), "active_store": str(active),
            "graph_signatures": {m["id"]: graph_signature(m) for m in manifests},
        })
        print(f"All six datasets ready: {expected_nodes:,} nodes, {expected_edges:,} relationships", flush=True)
    except BaseException:
        if installed:
            subprocess.run(["systemctl", "--user", "stop", SERVICE], check=False)
            active.rename(STAGING / "failed-installation")
        if old_moved:
            previous.rename(active)
        subprocess.run(["systemctl", "--user", "start", SERVICE], check=False)
        if installed:
            with postgres() as db:
                with db.transaction():
                    for manifest in manifests:
                        publish_catalog(db, manifest["id"], manifest, "preparing_graph", force_status=True)
            (STAGING / "installation-complete.json").unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
