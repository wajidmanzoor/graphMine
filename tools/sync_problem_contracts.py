#!/usr/bin/env python3
"""Refresh embedded formal topic definitions without changing capabilities.

This small Python command keeps catalog/manifest copies aligned with topic
sources. Executable problem/backend changes still use the catalog builder.
By default it checks; --write updates only embedded definitions and names.
--category-only restricts the sync to the generated category fields.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def synchronize(*, write=False, category_only=False):
    changed = []
    for relative, collection in (
        ("graphmine_catalog.json", "topics"),
        ("library/manifests/graphmine_catalog.json", "topics"),
        ("graphmine_manifest.json", "included_topic_specs"),
        ("library/manifests/graphmine_manifest.json", "included_topic_specs"),
    ):
        path = ROOT / relative
        document = json.loads(path.read_text())
        stale = []
        for record in document[collection]:
            source = ROOT / record["source"]
            source.resolve().relative_to((ROOT / "problems").resolve())
            specification = json.loads(source.read_text())
            if record["spec"]["topic_id"] != specification["topic_id"]:
                raise ValueError(f"Topic ID mismatch at {source}")
            embedded = (
                {**record["spec"], "category": specification["category"]}
                if category_only else specification
            )
            if record["spec"] != embedded:
                stale.append(specification["topic_id"])
                record["spec"] = embedded
            index = document.get("topic_index", {}).get(specification["topic_id"])
            if index is not None:
                for field in (("category",) if category_only else ("name", "category")):
                    if index[field] != specification[field]:
                        stale.append(specification["topic_id"])
                        index[field] = specification[field]
        if stale:
            changed.append({"path": relative, "topic_ids": sorted(set(stale))})
            if write:
                path.write_text(
                    json.dumps(document, indent=2, ensure_ascii=False) + "\n"
                )
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--category-only", action="store_true")
    args = parser.parse_args()
    changes = synchronize(write=args.write, category_only=args.category_only)
    print(json.dumps({"updated" if args.write else "stale": changes}, indent=2))
    return 0 if args.write or not changes else 1


if __name__ == "__main__":
    raise SystemExit(main())
