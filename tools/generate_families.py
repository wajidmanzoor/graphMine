#!/usr/bin/env python3
"""Generate runnable-problem membership and non-executable topic hints."""
import argparse
import hashlib
import json
from pathlib import Path
import pprint
import subprocess
from family_catalog import problem_metadata, read_catalog, read_topics, taxonomy
from validate_families import registry_cards, registry_problems, validate_taxonomy
ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = (ROOT / "python/graphmine/graphmine/_families.py", ROOT / "agent/graphmine_agent/_families.py")


def read_taxonomy():
    raw = b"\n".join((ROOT / "catalog" / name).read_bytes() for name in ("family.json", "problems.json", "topics.json"))
    document = taxonomy(ROOT)
    failures = validate_taxonomy(document, registry_problems(ROOT))
    _, problems = read_catalog(ROOT)
    declared = {(identifier, metadata["topic"]) for group in problems.values() for identifier, metadata in group.items()}
    if declared != set(registry_cards(ROOT)):
        failures.append("Runnable problem and topic identities must match the native registry")
    if failures:
        raise ValueError("\n".join(failures))
    return raw, document


def problem_family_ids(document=None):
    return {p: f["id"] for f in (document or taxonomy(ROOT))["families"] for p in f["problems"]}


def generated_source():
    raw, document = read_taxonomy()
    _, problems = read_catalog(ROOT)
    return ('"""Generated runnable problems and documentation topics; do not edit."""\n\n'
            + f'SOURCE_SHA256 = "{hashlib.sha256(raw).hexdigest()}"\n'
            + "FAMILIES = " + pprint.pformat(document["families"], sort_dicts=False, width=110)
            + '\n\nPROBLEM_FAMILY = {p: f["id"] for f in FAMILIES for p in f["problems"]}\n'
            + "\nPROBLEMS = " + pprint.pformat(problems, sort_dicts=False, width=110)
            + "\n\nTOPICS = " + pprint.pformat(read_topics(ROOT), sort_dicts=False, width=110) + "\n")


def algorithm_catalog(binary):
    native = json.loads(subprocess.check_output([str(binary.resolve()), "catalog"], text=True))
    return json.dumps({card["id"]: {backend["id"]: {
        "title": card["title"] + " — " + backend["id"], "description": card["description"],
        "backend_id": backend["id"], "device": backend["device"]}
        for backend in card["backends"]} for card in native["problems"]}, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--native-json", type=Path)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    _, document = read_taxonomy()
    if args.native_json:
        args.native_json.write_text(json.dumps({**problem_metadata(ROOT), **document}, ensure_ascii=False))
        return
    content = generated_source()
    outputs = {path: content for path in OUTPUTS}
    outputs[ROOT / "library/manifests/problems.json"] = json.dumps(problem_metadata(ROOT), indent=2) + "\n"
    if args.binary:
        outputs[ROOT / "catalog/algo.json"] = algorithm_catalog(args.binary)
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text() != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(content)
    if stale:
        raise SystemExit("Regenerate family metadata: " + ", ".join(stale))
    print("Runnable problem catalog matches native registry" if args.check else "Generated runnable problems and topics")


if __name__ == "__main__":
    main()
