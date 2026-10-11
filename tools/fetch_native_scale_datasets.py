#!/usr/bin/env python3
"""Download pinned public reference archives used by validate_native_scale.py."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = json.loads(
        (ROOT / "validation/native_final/scale-sources.json").read_text()
    )
    records = []
    for row in sources:
        path = args.output / row["filename"]
        if not path.exists():
            request = urllib.request.Request(
                row["url"], headers={"User-Agent": "GraphMine reference validation"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            assert len(raw) <= 8 * 1024 * 1024, (
                "Reference archive exceeds pinned download limit"
            )
            assert hashlib.sha256(raw).hexdigest() == row["sha256"], path
            path.write_bytes(raw)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], path
        if path.name.endswith(".tar.zst"):
            data = subprocess.check_output(["zstd", "-dc", str(path)])
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
                archive.extractall(args.output, filter="data")
        records.append(
            {
                "url": row["url"],
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": row["sha256"],
            }
        )
    (args.output / "sources.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Verified {len(records)} pinned archives in {args.output}")


if __name__ == "__main__":
    main()
