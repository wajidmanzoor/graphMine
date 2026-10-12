"""Offline, no-overwrite backup/verify/staged-restore commands."""

import argparse
import json
from pathlib import Path

from graphmine_agent.backup import restore_snapshot, snapshot_store, verify_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="API must be stopped first")
    snapshot.add_argument("--data-root", type=Path, required=True)
    snapshot.add_argument("--history-root", type=Path)
    snapshot.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = commands.add_parser(
        "restore", help="new staging directory; never resumes pending jobs"
    )
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "snapshot":
        report = snapshot_store(
            args.data_root, args.output, history_root=args.history_root
        )
    elif args.command == "verify":
        report = verify_snapshot(args.snapshot)
    else:
        report = restore_snapshot(args.snapshot, args.output)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "files"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
