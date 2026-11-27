#!/usr/bin/env python3
"""Discover IU databases with reads; optionally prepare a private source file.

This never wakes Neo4j, changes its configuration, or publishes the proposal.
Add the reported source IDs to GRAPHMINE_DATABASE_DATASET_ALLOWLIST when using
the curated picker. Retain its existing local entries for backend switching.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from graphmine_agent.database_sources import configured, neo4j_read, neo4j_session
from graphmine_agent.neo4j_backend import atomic_json
from graphmine_agent.neo4j_local import cli_settings

NAMES = {"amazon": "Amazon", "fars": "FARS", "fars20-22": "FARS 20–22",
         "ml32m": "MovieLens 32M", "mlgenome": "MovieLens Genome", "neo4j": "Neo4j",
         "ontime": "OnTime", "snb100": "LDBC SNB (snb100)", "stackof": "Stack Overflow", "yelp": "Yelp"}


def discover(source):
    if source.backend_id != "iu-remote" or not source._configured or not source.auth_disabled or source.sql_type:
        raise ValueError("Choose a configured IU connection without SQL mappings")
    system = source.model_copy(update={"neo4j_database": "system"})
    def read(tx):
        rows = list(tx.run("SHOW DATABASES YIELD name, type, currentStatus "
                           "RETURN name, type, currentStatus ORDER BY name LIMIT 101"))
        if len(rows) > 100:
            raise ValueError("IU database inventory exceeds the source limit")
        return sorted({r["name"] for r in rows if r["type"] == "standard" and r["currentStatus"] == "online" and r["name"] != "system"})
    with neo4j_session(system, wake=False) as session:
        return neo4j_read(session, system, read, timeout=10)


def proposal(settings, source_id="iu-remote"):
    sources = configured(settings)
    base = next(s for s in sources if s.id == source_id)
    names = discover(base)
    if not names:
        raise ValueError("No online IU data databases were discovered")
    by_database = {s.neo4j_database: s for s in sources if s.backend_id == "iu-remote"}
    by_id = {s.id: s for s in sources}
    selected = []
    for database in names:
        source = by_database.get(database)
        if source is None:
            slug = re.sub(r"[^a-z0-9_-]", "-", database.lower())
            identifier = "iu-" + (slug if slug == database and len(slug) <= 55 else slug[:45] + "-" + hashlib.sha256(database.encode()).hexdigest()[:8])
            if identifier in by_id:
                raise ValueError("A discovered source ID conflicts with retained configuration")
            source = base.model_copy(update={"id": identifier, "neo4j_database": database, "name": NAMES.get(database, database)})
            sources.append(source); by_id[identifier] = source
        elif source.id == base.id:
            source.name = NAMES.get(database, database)
        selected.append({"database": database, "source_id": source.id, "name": source.name})
    if len(sources) > 100:
        raise ValueError("Combined source inventory exceeds its limit")
    return [s.model_dump(exclude_none=True) for s in sources], selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="iu-remote")
    parser.add_argument("--output", type=Path, help="Write a mode-0600 proposed source file; retain all existing entries")
    args = parser.parse_args()
    try:
        settings = cli_settings(ROOT)
        if args.output and args.output.resolve() == settings.database_sources_file.resolve():
            raise ValueError("Use a separate proposal path")
        sources, selected = proposal(settings, args.source)
        if args.output:
            atomic_json(args.output, sources)
        print(json.dumps({"databases": selected, "proposal_written": bool(args.output)}, indent=2))
    except Exception:
        # Driver errors/configuration values may contain sensitive details.
        print("IU database discovery failed; check the tunnel and configured source.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
