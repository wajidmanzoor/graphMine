"""Approved 5.26 Community adaptation of PropGBench's LDBC bulk importer.

The archived shell script is never executed. Its labels, types, typed headers,
delimiters, integer IDs and strict bad-entry policy are preserved exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

import common


def arguments(root, proof):
    groups = proof["bulk"]["plan"]["groups"]
    if len(groups) != 31 or sum(group["kind"] == "nodes" for group in groups) != 8:
        raise ValueError("Expected the published eight node and 23 relationship groups")
    args = [str(common.NEO4J_HOME / "bin/neo4j-admin"), "database", "import", "full", "neo4j",
            "--id-type=INTEGER", "--ignore-empty-strings=true", "--bad-tolerance=0",
            "--delimiter=|", "--array-delimiter=;", "--threads=16", "--max-off-heap-memory=24g",
            "--report-file=" + str(root / "bulk-bad-entries.txt"), "--verbose"]
    for group in groups:
        relative = Path(group["subdirectory"]) / group["entity"]
        header = root / "import/headers" / relative.with_suffix(".csv")
        parts = sorted((root / "import/csv/initial_snapshot" / relative).glob("part-*.csv"))
        if len(parts) != len(group["parts"]) or not header.is_file() or not all(p.is_file() for p in parts):
            raise ValueError(f"Prepared bulk input group is incomplete: {relative}")
        flag = "nodes" if group["kind"] == "nodes" else "relationships"
        args.append(f"--{flag}={group['labels_or_type']}=" + ",".join(map(str, [header, *parts])))
    return args


def bootstrap_paths(root):
    # Restrict all moves to this newly-created instance's default user store.
    # The system database, other instances and old shared store are untouched.
    if root.is_symlink() or root.resolve() != (common.INSTANCE_ROOT / "ldbc-snb").resolve():
        raise ValueError("LDBC instance root is not the dedicated deployment path")
    configuration = dict(line.split("=", 1) for line in (root / "conf/neo4j.conf").read_text().splitlines()
                         if line.strip() and not line.startswith("#") and "=" in line)
    expected = {"server.directories.data": root / "data", "server.directories.transaction.logs.root": root / "transactions"}
    for setting, path in expected.items():
        if Path(configuration.get(setting, "/invalid")).resolve() != path.resolve() or path.is_symlink():
            raise ValueError("LDBC data/transaction configuration does not point to its dedicated directory")
    return {"database": root / "data/databases/neo4j", "transactions": root / "transactions/neo4j"}


def wait_running(seconds=180):
    deadline = time.monotonic() + seconds
    last = "not connected"
    while time.monotonic() < deadline:
        try:
            with common.driver("ldbc-snb") as driver:
                driver.verify_connectivity()
                with driver.session(database="neo4j") as session:
                    session.run("RETURN 1").consume()
                return
        except Exception as error:
            last = str(error).replace(common.password("ldbc-snb"), "<redacted>")
            time.sleep(2)
    raise RuntimeError("LDBC instance did not restart: " + last)


def import_snapshot(proof, state):
    root = common.INSTANCE_ROOT / "ldbc-snb"
    registry = json.loads((common.SOURCE_ROOT / "registry.json").read_text())
    # The user approved overlapping LDBC with the running OnTime import.
    # Publication still requires each dataset's own complete verification.
    required = {"yelp", "movielens-32m", "movielens-genome"}
    if not required.issubset({item["id"] for item in registry["datasets"]}):
        raise ValueError("LDBC requires Yelp and both MovieLens datasets to pass verification first")
    for slug in required:
        if json.loads((common.INSTANCE_ROOT / slug / "status.json").read_text()).get("status") != "ready":
            raise ValueError(f"Earlier dataset is not ready: {slug}")
    with common.driver("ldbc-snb") as driver, driver.session(database="neo4j") as session:
        common.require_empty(session)
    paths = bootstrap_paths(root)
    backup = root / "empty-bootstrap-before-bulk"
    if backup.exists() or (root / "bulk-result.json").exists():
        raise ValueError("A previous bulk attempt exists; inspect it instead of replacing stores")
    command = arguments(root, proof)
    unit = "graphmine-neo4j-ldbc-snb.service"
    subprocess.run(["systemctl", "--user", "stop", unit], check=True)
    backup.mkdir(mode=0o700)
    moved = {}
    imported = False
    started = time.monotonic()
    try:
        for name, path in paths.items():
            if path.exists():
                path.rename(backup / name)
                moved[name] = path
        state.update(phase="bulk_importing")
        common.status("ldbc-snb", state)
        common.write_json(root / "bulk-command.json", {"argv": command, "started_at": common.now(),
                          "memory_max_gib": 40, "max_off_heap_gib": 24, "threads": 16,
                          "note": "Default database of this dedicated instance only; no overwrite flag, no global service problem, published schema follows through the driver."})
        with (root / "bulk-import.log").open("w") as log:
            result = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=40G", *command],
                                    env=common.process_environment("ldbc-snb"), cwd=root, stdout=log, stderr=subprocess.STDOUT)
        common.write_json(root / "bulk-result.json", {"exit_code": result.returncode,
                          "seconds": round(time.monotonic()-started, 3), "finished_at": common.now()})
        if result.returncode:
            raise RuntimeError(f"LDBC bulk import failed ({result.returncode}); see bulk-import.log")
        imported = True
    finally:
        if not imported:
            # Preserve the failed attempt and restore the known-empty bootstrap.
            failed = root / "failed-bulk-store"
            failed.mkdir(exist_ok=True, mode=0o700)
            for name, path in moved.items():
                if path.exists():
                    path.rename(failed / name)
                (backup / name).rename(path)
        subprocess.run(["systemctl", "--user", "start", unit], check=True)
        wait_running()
    print("LDBC offline import completed; instance restarted; applying the unchanged published schema next", flush=True)
