from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import list_algorithms, list_families, run
from .exceptions import GraphMineError


def main():
    parser = argparse.ArgumentParser(
        description="Validated graph algorithm inputs and explicit CPU/GPU dispatch"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("families")
    execute = commands.add_parser("run")
    execute.add_argument("operation")
    execute.add_argument("graph", type=Path)
    execute.add_argument(
        "--parameters",
        type=Path,
        help="JSON object containing the exact operation parameters",
    )
    execute.add_argument("--device", choices=("auto", "cpu", "gpu"), default="auto")
    execute.add_argument("--backend", default="auto")
    execute.add_argument("--gpu-device", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list_algorithms()
        elif args.command == "families":
            result = list_families()
        else:
            result = run(
                args.operation,
                json.loads(args.graph.read_text()),
                parameters=json.loads(args.parameters.read_text())
                if args.parameters
                else {},
                device=args.device,
                backend=args.backend,
                gpu_device=args.gpu_device,
            )
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (GraphMineError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": getattr(exc, "code", "invalid_input"),
                        "message": str(exc),
                    }
                }
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
