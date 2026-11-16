#!/usr/bin/env python3
"""Create an isolated, authenticated Neo4j 5.26 Community dataset instance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import common


APOC_VERSION = "5.26.32"
APOC_URL = "https://github.com/neo4j/apoc/releases/download/5.26.32/apoc-5.26.32-core.jar"
APOC_SIZE = 3077005


def apoc_jar():
    directory = common.INSTANCE_ROOT / "_distribution"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"apoc-{APOC_VERSION}-core.jar"
    receipt = path.with_suffix(".json")
    if path.exists():
        proof = json.loads(receipt.read_text())
        if proof.get("url") != APOC_URL or common.sha256(path) != proof.get("sha256"):
            raise ValueError("Cached APOC JAR does not match its recorded download")
        return path, proof
    temporary = path.with_suffix(".partial")
    bundled = common.NEO4J_HOME / "labs" / path.name
    if bundled.is_file():
        shutil.copy2(bundled, temporary)
    else:
        with urllib.request.urlopen(APOC_URL, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
    if temporary.stat().st_size != APOC_SIZE:
        raise ValueError("APOC asset size differs from the official release metadata")
    with zipfile.ZipFile(temporary) as archive:
        if not any(name.startswith("apoc/") and name.endswith(".class") for name in archive.namelist()):
            raise ValueError("Downloaded file is not the APOC plugin JAR")
    temporary.replace(path)
    proof = {"url": APOC_URL, "version": APOC_VERSION, "sha256": common.sha256(path),
             "bytes": path.stat().st_size, "copied_at": common.now(),
             "source": str(bundled) if bundled.is_file() else APOC_URL,
             "compatibility_note": "5.26.0 failed startup with ObjectUtils.getIfNull NoSuchMethodError; use the matching bundled build, as permitted by the specification."}
    common.write_json(receipt, proof)
    return path, proof


def reserve_ports(definition):
    sockets = []
    try:
        for port in (definition["bolt_port"], definition["http_port"]):
            sock = socket.socket()
            sockets.append(sock)
            sock.bind(("127.0.0.1", port))
    finally:
        for sock in sockets:
            sock.close()


def validate_memory_budget():
    memory = next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:"))
    gib = int(memory.split()[1]) / 1024 / 1024
    reservation = sum(common.definition(slug)["memory"]["maximum_gib"] for slug in common.ORDER)
    if reservation + 64 > gib:
        raise ValueError("The six-instance memory plan must leave at least 64 GiB for existing services")


def wait_ready(slug, secret, seconds=120):
    from neo4j import GraphDatabase

    definition = common.definition(slug)
    deadline = time.monotonic() + seconds
    last = "not started"
    while time.monotonic() < deadline:
        try:
            with GraphDatabase.driver(definition["bolt_uri"], auth=("neo4j", secret), connection_timeout=3) as driver:
                with driver.session(database="neo4j") as session:
                    nodes = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
                    relationships = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
                    if nodes or relationships:
                        raise ValueError("New instance is not empty; refusing to continue")
                    apoc = session.run("RETURN apoc.version() AS version").single()["version"]
                    config = session.run("CALL dbms.listConfig('server.directories.import') YIELD value RETURN value").single()
                    expected = common.INSTANCE_ROOT / slug / "import"
                    if config is None or Path(config["value"]).resolve() != expected.resolve():
                        raise ValueError("Neo4j resolved the wrong import directory")
                    return {"nodes": nodes, "relationships": relationships, "apoc_version": apoc,
                            "import_directory": str(expected), "checked_at": common.now()}
        except ValueError:
            raise
        except Exception as error:
            last = str(error).replace(secret, "<redacted>")
            time.sleep(1)
    raise RuntimeError("Instance startup checks did not pass: " + last)


def create(slug):
    definition = common.definition(slug)
    root = common.INSTANCE_ROOT / slug
    # Input preparation is the required prior gate for this dataset.
    common.verify_inputs(slug)
    if (root / "data").exists() and any((root / "data").iterdir()):
        raise ValueError("Refusing to overwrite an instance that already has data")
    if (root / "conf/neo4j.conf").exists():
        raise ValueError("Instance configuration already exists; inspect it instead of overwriting it")
    validate_memory_budget()
    reserve_ports(definition)
    env = common.process_environment(slug)
    version = subprocess.run([str(common.NEO4J_HOME / "bin/neo4j"), "--version"],
                             env=env, capture_output=True, text=True)
    if version.returncode or "5.26.32" not in version.stdout:
        raise ValueError("The existing distribution must be Neo4j 5.26.32")
    jar, apoc = apoc_jar()
    secret = common.password(slug, create=True)
    for name in ("conf", "data", "logs", "import", "plugins", "run", "transactions"):
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "plugins" / jar.name).symlink_to(jar)
    memory = definition["memory"]
    settings = {
        "server.default_listen_address": "127.0.0.1",
        "server.default_advertised_address": "127.0.0.1",
        "server.bolt.enabled": "true", "server.http.enabled": "true", "server.https.enabled": "false",
        "server.bolt.listen_address": f"127.0.0.1:{definition['bolt_port']}",
        "server.bolt.advertised_address": f"127.0.0.1:{definition['bolt_port']}",
        "server.http.listen_address": f"127.0.0.1:{definition['http_port']}",
        "server.http.advertised_address": f"127.0.0.1:{definition['http_port']}",
        "dbms.security.auth_enabled": "true",
        "dbms.security.procedures.unrestricted": "apoc.*",
        "dbms.security.procedures.allowlist": "apoc.*",
        "server.memory.heap.initial_size": f"{memory['heap_gib']}g",
        "server.memory.heap.max_size": f"{memory['heap_gib']}g",
        "server.memory.pagecache.size": f"{memory['page_cache_gib']}g",
        "server.directories.data": root / "data", "server.directories.logs": root / "logs",
        "server.directories.import": root / "import", "server.directories.plugins": root / "plugins",
        "server.directories.run": root / "run", "server.directories.transaction.logs.root": root / "transactions",
        # Retain a bounded recovery log after checkpoints, as on the existing host.
        "db.tx_log.rotation.retention_policy": "2 days 2G",
    }
    (root / "conf/neo4j.conf").write_text("\n".join(f"{key}={value}" for key, value in settings.items()) + "\n")
    (root / "conf/apoc.conf").write_text("apoc.import.file.enabled=true\napoc.import.file.use_neo4j_config=true\n")
    for source in (common.NEO4J_HOME / "conf").glob("*.xml"):
        shutil.copy2(source, root / "conf" / source.name)
    validation = subprocess.run([str(common.NEO4J_HOME / "bin/neo4j-admin"), "server", "validate-config"],
                                env=env, text=True, capture_output=True)
    if validation.returncode:
        raise ValueError("Neo4j configuration validation failed: " + validation.stdout + validation.stderr)
    result = subprocess.run([str(common.NEO4J_HOME / "bin/neo4j-admin"), "dbms", "set-initial-password", secret],
                            env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Password initialization failed: " + (result.stdout + result.stderr).replace(secret, "<redacted>"))
    unit = f"graphmine-neo4j-{slug}.service"
    unit_path = Path.home() / ".config/systemd/user" / unit
    if unit_path.exists():
        raise ValueError("Refusing to overwrite an existing systemd unit")
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(f'''[Unit]
Description=GraphMine PropGBench Neo4j - {definition['name']}
After=network.target

[Service]
Type=simple
WorkingDirectory={root}
Environment=NEO4J_HOME={common.NEO4J_HOME}
Environment=NEO4J_CONF={root / 'conf'}
Environment=JAVA_HOME={common.JAVA_HOME}
ExecStart={common.NEO4J_HOME / 'bin/neo4j'} console
Restart=on-failure
RestartSec=5
TimeoutStopSec=300
UMask=0077
LimitNOFILE=65536
MemoryMax={memory['maximum_gib']}G

[Install]
WantedBy=default.target
''')
    common.write_json(root / "instance.json", {**definition, "created_at": common.now(),
                                               "neo4j_version": "5.26.32", "apoc": apoc, "unit": unit})
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "start", unit], check=True)
    try:
        checked = wait_ready(slug, secret)
    except Exception:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False)
        raise
    common.write_json(root / "instance-check.json", checked)
    subprocess.run(["systemctl", "--user", "enable", unit], check=True, capture_output=True)
    print(slug + ": isolated instance is empty; APOC and import-directory checks passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=common.ORDER)
    args = parser.parse_args()
    create(args.dataset)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
