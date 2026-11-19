from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def append(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n").encode())
    finally:
        os.close(fd)


def write_json(path, value, *, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600 if private else 0o644)
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            # A truncated log is evidence of an interrupted run, not a zero.
            rows.append(json.loads(line))
    return rows


def percentile(values, p):
    values = sorted(x for x in values if isinstance(x, (int, float)) and math.isfinite(x))
    return values[max(0, math.ceil(len(values) * p / 100) - 1)] if values else None


def mean(values):
    values = [x for x in values if isinstance(x, (int, float)) and math.isfinite(x)]
    return sum(values) / len(values) if values else None


def slug(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", value):
        raise ValueError("Use a label of 1–80 letters, digits, dots, underscores or hyphens")
    return value


def seconds(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
