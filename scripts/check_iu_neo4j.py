#!/usr/bin/env python3
"""Check IU route, Bolt on 7689 and RETURN 1; SSH requires explicit --wake."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from graphmine_agent.neo4j_backend import get_active_neo4j
from graphmine_agent.neo4j_local import cli_settings
from graphmine_agent.remote_neo4j import RemoteNeo4j


def check(settings, *, wake=False, remote=None):
    remote = remote or RemoteNeo4j(settings)
    endpoint = get_active_neo4j(settings, target="iu-remote").connection
    report = {"endpoint": endpoint.uri, "authentication": "none", "wake_requested": wake,
              "tunnel_reachable": remote.reachable(), "bolt_connectivity": False, "return_1": None}
    if not report["tunnel_reachable"]:
        return {**report, "error": "VPN tunnel is down"}
    try:
        if wake:
            remote.ensure_awake()
        report["bolt_connectivity"] = remote.is_up(refresh=True)
        if not report["bolt_connectivity"]:
            return {**report, "error": "Bolt is unavailable on port 7689"}
        from neo4j import GraphDatabase, READ_ACCESS, unit_of_work
        @unit_of_work(timeout=5)
        def read(transaction):
            return transaction.run("RETURN 1 AS connected").single(strict=True)["connected"]
        with GraphDatabase.driver(endpoint.uri, auth=endpoint.auth, connection_timeout=3,
                                  connection_acquisition_timeout=5, max_transaction_retry_time=0) as driver:
            with driver.session(database=endpoint.database, default_access_mode=READ_ACCESS) as session:
                report["return_1"] = session.execute_read(read)
        if report["return_1"] != 1:
            report["error"] = "The read-only query did not return 1"
    except Exception:
        # Never print a driver/SSH exception, remote output or environment value.
        report["error"] = "IU database verification failed; check the tunnel and configured wake policy"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wake", action="store_true", help="Request wake under the configured AUTOWAKE policy")
    args = parser.parse_args(argv)
    report = check(cli_settings(ROOT), wake=args.wake)
    print(json.dumps(report, indent=2))
    return int("error" in report)


if __name__ == "__main__":
    raise SystemExit(main())
