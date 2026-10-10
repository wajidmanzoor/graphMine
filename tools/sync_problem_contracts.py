#!/usr/bin/env python3
"""Refresh embedded formal problem definitions without changing capabilities.

This small Python command keeps catalog/manifest copies aligned with problem
sources. Executable operation/backend changes still use the catalog builder.
By default it checks; --write updates only embedded definitions and names.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def synchronize(*, write=False):
    changed = []
    for relative, collection in (
        ("graphmine_catalog.json", "problems"),
        ("library/manifests/graphmine_catalog.json", "problems"),
        ("graphmine_manifest.json", "included_problem_specs"),
        ("library/manifests/graphmine_manifest.json", "included_problem_specs"),
    ):
        path = ROOT / relative
        document = json.loads(path.read_text())
        stale = []
        for record in document[collection]:
            source = ROOT / record["source"]
            source.resolve().relative_to((ROOT / "problems").resolve())
            specification = json.loads(source.read_text())
            if record["spec"]["problem_id"] != specification["problem_id"]:
                raise ValueError(f"Problem ID mismatch at {source}")
            if record["spec"] != specification:
                stale.append(specification["problem_id"])
                record["spec"] = specification
            index = document.get("problem_index", {}).get(specification["problem_id"])
            if index is not None:
                for field in ("name", "category"):
                    if index[field] != specification[field]:
                        stale.append(specification["problem_id"])
                        index[field] = specification[field]
        if stale:
            changed.append({"path": relative, "problem_ids": sorted(set(stale))})
            if write:
                path.write_text(
                    json.dumps(document, indent=2, ensure_ascii=False) + "\n"
                )
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changes = synchronize(write=args.write)
    print(json.dumps({"updated" if args.write else "stale": changes}, indent=2))
    return 0 if args.write or not changes else 1


if __name__ == "__main__":
    raise SystemExit(main())
