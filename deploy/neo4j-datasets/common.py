"""Host paths and invariants shared by the isolated Neo4j deployment tools."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

from source_pages import DATASETS, audit


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "agent"))
from graphmine_agent.neo4j_backend import deployment_settings, get_active_neo4j, local_uri
SOURCE_ROOT = Path(__file__).resolve().parent
LAB_ROOT = Path(os.environ.get("GRAPHMINE_LAB_DATA_ROOT", "/data/labdata/wajid/graphmine_data"))
INSTANCE_ROOT = LAB_ROOT / "neo4j-instances"
PASSWORD_FILE = REPOSITORY / ".database-workspace/demo.env"
NEO4J_HOME = REPOSITORY / ".database-workspace/neo4j-community-5.26.32"
JAVA_HOME = REPOSITORY.parent / "validation/outer_integrations/deps/jdk/usr/lib/jvm/java-17-openjdk-amd64"
ORDER = ("yelp", "movielens-32m", "movielens-genome", "stackoverflow", "ontime", "ldbc-snb")
PAGE_CACHE_GIB = dict(zip(ORDER, (12, 8, 8, 40, 12, 56)))
HEAP_GIB = {slug: 16 if slug == "ontime" else 4 for slug in ORDER}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def definition(slug):
    if slug not in ORDER:
        raise ValueError("Unknown dataset")
    index = ORDER.index(slug) + 1
    return {"id": slug, "name": DATASETS[slug][0], "bolt_uri": local_uri(17700 + index),
            "http_port": 17400 + index, "bolt_port": 17700 + index,
            "password_env": "GRAPHMINE_NEO4J_" + slug.upper().replace("-", "_") + "_PASSWORD",
            "workload_url": f"https://pgraphbenchweb.vercel.app/workloads/{DATASETS[slug][1]}-neo4j.html",
            "default_query": "MATCH p = (a)-[r]->(b) RETURN p LIMIT 1000",
            "memory": {"heap_gib": HEAP_GIB[slug], "page_cache_gib": PAGE_CACHE_GIB[slug],
                       "maximum_gib": PAGE_CACHE_GIB[slug] + HEAP_GIB[slug] + 2}}


def read_env(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            raise ValueError("Invalid assignment in private environment file")
        key, raw = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("Invalid environment variable name")
        parsed = shlex.split(raw, comments=True)
        if len(parsed) > 1:
            raise ValueError(f"Quote the value of {key} in the private environment file")
        if key in values:
            raise ValueError(f"Duplicate private environment variable: {key}")
        values[key] = parsed[0] if parsed else ""
    return values


def password(slug, *, create=False):
    import secrets

    name = definition(slug)["password_env"]
    if create:
        PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT if create else os.O_RDONLY
    fd = os.open(PASSWORD_FILE, flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+" if create else "r") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if create else fcntl.LOCK_SH)
        stat = os.fstat(stream.fileno())
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError("Passwords must be in the owner's mode-600 demo.env")
        contents = stream.read()
        values = read_env(contents)
        value = values.get(name)
        if not value and create:
            value = secrets.token_urlsafe(36)
            stream.write(("\n" if contents and not contents.endswith("\n") else "") + name + "=" + value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if not value:
            raise ValueError(f"Missing {name} in .database-workspace/demo.env")
        return value


def process_environment(slug):
    env = dict(os.environ)
    env.update(NEO4J_HOME=str(NEO4J_HOME), NEO4J_CONF=str(INSTANCE_ROOT / slug / "conf"), JAVA_HOME=str(JAVA_HOME))
    return env


def verify_inputs(slug, *, content=True):
    source = audit(slug)
    instance = INSTANCE_ROOT / slug
    proof = json.loads((instance / "import-receipt.json").read_text())
    if proof.get("source_page_sha256") != source["page_sha256"] or not proof.get("content_hashes_checked"):
        raise ValueError("Import preparation has not passed its source/content checks")
    root = instance / "import"
    records = proof.get("files", []) if slug != "ldbc-snb" else proof["bulk"]["partitions"]
    if slug != "ldbc-snb" and {r["import_path"] for r in records} != set(source["required_files"]):
        raise ValueError("The prepared import paths differ from the published scripts")
    for record in records:
        path = root / record["import_path"]
        size = record.get("size_bytes", record.get("output_bytes"))
        expected = record.get("sha256", record.get("output_sha256"))
        if not path.is_file() or path.stat().st_size != size or (content and sha256(path) != expected):
            raise ValueError(f"Prepared import file failed verification: {path}")
    if slug == "ldbc-snb":
        for group in proof["bulk"]["plan"]["groups"]:
            path = root / "headers" / group["subdirectory"] / (group["entity"] + ".csv")
            if sha256(path) != group["header_sha256"]:
                raise ValueError(f"Prepared Neo4j header changed: {path}")
    return proof


def driver(slug, *, secret=None, connection_timeout=10):
    from neo4j import GraphDatabase

    endpoint = get_active_neo4j(deployment_settings(REPOSITORY, password_file=PASSWORD_FILE),
        target="local", local_record=definition(slug),
        credentials=("neo4j", secret or password(slug))).connection
    return GraphDatabase.driver(endpoint.uri, auth=endpoint.auth,
                                connection_timeout=connection_timeout, max_connection_pool_size=4)


def graph_counts(session):
    def escaped(name):
        return "`" + name.replace("`", "``") + "`"

    labels = [row["label"] for row in session.run("CALL db.labels() YIELD label RETURN label")]
    types = [row["relationshipType"] for row in session.run(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")]
    return {
        "nodes": {label: session.run(f"MATCH (n:{escaped(label)}) RETURN count(n) AS n").single()["n"]
                  for label in sorted(labels)},
        "relationships": {kind: session.run(f"MATCH ()-[r:{escaped(kind)}]->() RETURN count(r) AS n").single()["n"]
                          for kind in sorted(types)},
        "total_nodes": session.run("MATCH (n) RETURN count(n) AS n").single()["n"],
        "total_relationships": session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"],
    }


def require_empty(session):
    nodes = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    edges = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
    if nodes or edges:
        raise ValueError(f"Refusing to load a non-empty database: {nodes} nodes, {edges} relationships")


def load_hashes(slug):
    manifest = audit(slug)
    paths = [item["file"] for item in manifest["load_order"] + manifest["reference_scripts"]]
    if slug == "ldbc-snb":
        paths += [str(path.relative_to(SOURCE_ROOT / slug))
                  for path in sorted((SOURCE_ROOT / slug / "reference/headers").glob("*/*.csv"))]
    result = {path: sha256(SOURCE_ROOT / slug / path) for path in paths}
    if slug == "ldbc-snb":
        result["@adapter/ldbc_bulk.py"] = sha256(SOURCE_ROOT / "ldbc_bulk.py")
    return result


def status(slug, record):
    write_json(INSTANCE_ROOT / slug / "status.json", {"id": slug, **record, "updated_at": now()})
