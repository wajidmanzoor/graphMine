"""Generate private local-demo credentials and a source mapping; starts no services."""

import argparse
import json
import os
import secrets
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
from graphmine_agent.neo4j_backend import local_uri


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".database-workspace"))
    parser.add_argument(
        "--user",
        action="append",
        help="Allowed GraphMine username; default is all local users",
    )
    parser.add_argument("--sql-port", type=int, default=55432)
    parser.add_argument("--bolt-port", type=int, default=17687)
    parser.add_argument("--neo4j-http-port", type=int, default=17474)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    config, envfile = directory / "sources.json", directory / "demo.env"
    if config.exists() or envfile.exists():
        parser.error(
            "Demo files already exist; keep the existing credentials or choose a new directory."
        )
    sql_password, reader_password, neo4j_password = [
        secrets.token_urlsafe(24) for _ in range(3)
    ]
    source = {
        "id": "local-transfers",
        "name": "Local transfers demo",
        "users": args.user or ["*"],
        "sql_type": "postgres",
        "sql_dsn_env": "GRAPHMINE_DEMO_SQL_DSN",
        "neo4j_uri": local_uri(args.bolt_port),
        "neo4j_password_env": "GRAPHMINE_DEMO_NEO4J_PASSWORD",
        "entities": [
            {
                "id": "accounts",
                "table": "accounts",
                "key": ["id"],
                "label": "Account",
                "attributes": ["name", "country", "risk_score", "segment"],
                "graph_attributes": ["name"],
                "display": "name",
            }
        ],
        "relationships": [
            {
                "id": "transfers",
                "table": "transfers",
                "key": ["id"],
                "label": "TRANSFER",
                "source_entity": "accounts",
                "target_entity": "accounts",
                "source_columns": ["sender"],
                "target_columns": ["receiver"],
                "attributes": ["amount", "reason", "occurred_at"],
                "graph_attributes": ["amount"],
                "weight": "amount",
                "timestamp": "occurred_at",
            }
        ],
    }
    env = {
        "GRAPHMINE_DATABASE_SOURCES_FILE": str(config),
        "GRAPHMINE_DEMO_SQL_PASSWORD": sql_password,
        "GRAPHMINE_DEMO_READER_PASSWORD": reader_password,
        "GRAPHMINE_DEMO_NEO4J_PASSWORD": neo4j_password,
        "GRAPHMINE_DEMO_SQL_DSN": f"postgresql://graphmine_reader:{reader_password}@127.0.0.1:{args.sql_port}/graphmine_demo",
        "GRAPHMINE_DEMO_SQL_PORT": str(args.sql_port),
        "GRAPHMINE_DEMO_BOLT_PORT": str(args.bolt_port),
        "GRAPHMINE_DEMO_NEO4J_HTTP_PORT": str(args.neo4j_http_port),
    }
    for path, text in (
        (config, json.dumps([source], indent=2) + "\n"),
        (envfile, "".join(f"{k}={shlex.quote(v)}\n" for k, v in env.items())),
    ):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
    print(
        f"Created private configuration in {directory}. No database has been started or changed."
    )


if __name__ == "__main__":
    main()
