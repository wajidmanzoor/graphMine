#!/usr/bin/env python3
"""Generate packaged family metadata and problem categories from one taxonomy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pprint
import re
import subprocess

from family_catalog import problem_metadata, read_catalog, taxonomy
from sync_problem_contracts import synchronize
from validate_families import registry_cards, registry_operations, validate_taxonomy

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = (
    ROOT / "python/graphmine/graphmine/_families.py",
    ROOT / "agent/graphmine_agent/_families.py",
)


def read_taxonomy():
    raw = b"\n".join((ROOT / "catalog" / name).read_bytes()
                     for name in ("family.json", "problems.json"))
    document = taxonomy(ROOT)
    failures = validate_taxonomy(document, registry_operations(ROOT))
    _families, problems = read_catalog(ROOT)
    declared = {(operation, identifier) for group in problems.values()
                for identifier, problem in group.items() for operation in problem["operation_ids"]}
    if declared != set(registry_cards(ROOT)):
        failures.append("Problem operation IDs must match the native registry's operation/problem identities")
    if failures:
        raise ValueError("\n".join(failures))
    return raw, document


def problem_family_ids(document=None):
    """Derive problem categories through the registry's operation/problem IDs."""
    if document is None:
        _raw, document = read_taxonomy()
    operation_families = {
        operation: family["id"]
        for family in document["families"]
        for operation in family["operations"]
    }
    result = {}
    for operation, problem in registry_cards(ROOT):
        family = operation_families[operation]
        if problem in result and result[problem] != family:
            raise ValueError(f"Problem {problem!r} has operations in different families")
        result[problem] = family
    return result


def problem_category_outputs():
    families = problem_family_ids()
    outputs, seen = {}, set()
    for path in sorted((ROOT / "problems").glob("*/problem.json")):
        source = path.read_text()
        specification = json.loads(source)
        problem = specification["problem_id"]
        if problem in seen:
            raise ValueError(f"Duplicate problem ID {problem!r}")
        seen.add(problem)
        if problem not in families:
            raise ValueError(f"Problem {problem!r} has no registered operation family")
        if not isinstance(specification.get("category"), str):
            raise ValueError(f"Problem {problem!r} must declare a category")
        # Replace only this field; retain all contract content and formatting.
        content, count = re.subn(
            r'(?m)^(\s*"category"\s*:\s*)"(?:\\.|[^"\\])*"',
            lambda match: match[1] + json.dumps(families[problem]),
            source,
        )
        if count != 1:
            raise ValueError(f"Expected one category field in {path}")
        outputs[path] = content
    return outputs


def generated_source():
    raw, document = read_taxonomy()
    _families, problems = read_catalog(ROOT)
    return (
        '"""Generated from catalog/family.json and catalog/problems.json; do not edit."""\n\n'
        f'SOURCE_SHA256 = "{hashlib.sha256(raw).hexdigest()}"\n'
        # The validated rows contain only strings and lists, also valid Python.
        + "FAMILIES = " + json.dumps(document["families"], ensure_ascii=False, indent=2)
        + "\n\nOPERATION_FAMILY = {\n"
        + '    operation: family["id"]\n'
        + "    for family in FAMILIES\n"
        + '    for operation in family["operations"]\n'
        + "}\n"
        + "\nPROBLEMS = " + pprint.pformat(problems, sort_dicts=False, width=110) + "\n"
    )


def algorithm_catalog(binary):
    """Describe existing implementation profiles, without deciding admission."""
    native = json.loads(subprocess.check_output([str(binary.resolve()), "catalog"], text=True))
    _families, problems = read_catalog(ROOT)
    operations = {card["id"]: card for card in native["operations"]}
    result = {}
    for group in problems.values():
        for identifier, problem in group.items():
            implementations = {}
            for operation in problem["operation_ids"]:
                card = operations[operation]
                if card["problem_id"] != identifier:
                    raise ValueError(f"Rebuild native catalog: {operation} has a different problem ID")
                for backend in card["backends"]:
                    # Backend IDs such as cpp recur within multi-operation problems.
                    key = operation + "/" + backend["id"]
                    implementations[key] = {
                        "title": card["title"] + " — " + backend["id"],
                        "description": backend.get("execution", card["description"]),
                        "operation_id": operation,
                        "backend_id": backend["id"],
                        "device": backend["device"],
                    }
            result[identifier] = implementations
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if family metadata or problem categories are stale")
    parser.add_argument("--native-json", type=Path, help="Write the derived catalog for native embedding only")
    parser.add_argument("--binary", type=Path, help="Also generate/check algo.json from existing native profiles")
    args = parser.parse_args()
    if args.native_json:
        _raw, document = read_taxonomy()
        args.native_json.write_text(json.dumps({**problem_metadata(ROOT), **document}, ensure_ascii=False))
        return
    content = generated_source()
    outputs = {path: content for path in OUTPUTS}
    outputs[ROOT / "library/manifests/problems.json"] = json.dumps(problem_metadata(ROOT), indent=2) + "\n"
    if args.binary:
        outputs[ROOT / "catalog/algo.json"] = algorithm_catalog(args.binary)
    outputs.update(problem_category_outputs())
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text() != content:
                stale.append(str(path.relative_to(ROOT)))
        elif not path.is_file() or path.read_text() != content:
            path.write_text(content)
    # Keep the installed and repository catalogs' embedded specs/indexes aligned.
    stale.extend(change["path"] for change in synchronize(write=not args.check, category_only=True))
    if args.check and stale:
        raise SystemExit("Regenerate family metadata with tools/generate_families.py: " + ", ".join(stale))
    print("Family metadata and problem categories match the family/problem catalogs" if args.check
          else "Generated family metadata, problem categories and embedded contract copies")


if __name__ == "__main__":
    main()
