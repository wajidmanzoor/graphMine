#!/usr/bin/env python3
"""Validate the operation taxonomy and grep repository family references."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import html
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FAMILY_FIELDS = {"id", "title", "description", "deciding_question", "operations"}
IDENTIFIER = r"[a-z][a-z0-9_-]*"
LITERAL = rf"""["'](?P<family>{IDENTIFIER})["']"""
FAMILY_REFERENCES = tuple(re.compile(pattern) for pattern in (
    rf"\.\s*family\s*\(\s*{LITERAL}",
    rf"\blist_algorithms\s*\(\s*family\s*=\s*{LITERAL}",
    rf"""\b(?:family_id|preferred_family|data-family)\s*=\s*{LITERAL}""",
    rf"""["'](?:family_id|preferred_family)["']\s*:\s*{LITERAL}""",
    rf"""\b(?:family_id|preferred_family|family\.id|\w+\.family)\s*(?:===?|!==?)\s*{LITERAL}""",
    rf"""\b(?:card|operation|problem)\s*\[\s*["']family["']\s*\]\s*(?:===?|!==?)\s*{LITERAL}""",
    rf"""(?:#family/|--family[= ]+)["']?(?P<family>{IDENTIFIER})""",
))
TEXT_SUFFIXES = {
    ".py", ".cpp", ".hpp", ".h", ".c", ".cu", ".cuh", ".in", ".cmake",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".rst", ".txt", ".html", ".js", ".jsx", ".ts", ".tsx", ".mjs",
    ".sh",
}


def registry_cards(root: Path) -> list[tuple[str, str]]:
    """Read literal operation/problem IDs from native cards, without a build."""
    source = (root / "library/runtime/registry.cpp").read_text()
    cards = re.findall(
        rf'\bcard\s*\(\s*"({IDENTIFIER})"\s*,\s*"({IDENTIFIER})"', source
    )
    if not cards:
        raise ValueError("No native operation-card declarations found")
    return cards


def registry_operations(root: Path) -> list[str]:
    return [operation for operation, _problem in registry_cards(root)]


def validate_taxonomy(document: dict, registered: list[str]) -> list[str]:
    errors = []
    if not isinstance(document, dict) or set(document) != {"schema_version", "families"}:
        return ["Taxonomy must contain only schema_version and families; aliases are not allowed"]
    if document["schema_version"] != 1:
        errors.append("Unsupported taxonomy schema_version")
    families = document["families"]
    if not isinstance(families, list) or len(families) != 14:
        return errors + ["Expected 14 families in display order"]
    if len(registered) != 82 or len(set(registered)) != len(registered):
        errors.append("Expected 82 unique native registry operation IDs")
    identifiers, operations = [], []
    for index, family in enumerate(families):
        location = f"families[{index}]"
        if not isinstance(family, dict) or set(family) != FAMILY_FIELDS:
            errors.append(f"{location}: expected {sorted(FAMILY_FIELDS)}; aliases are not allowed")
            continue
        for field in FAMILY_FIELDS - {"operations"}:
            value = family[field]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{location}.{field}: expected nonempty text")
        identifier = family["id"]
        if not isinstance(identifier, str) or not re.fullmatch(IDENTIFIER, identifier):
            errors.append(f"{location}.id: invalid family identifier")
        else:
            identifiers.append(identifier)
        description, question = family["description"], family["deciding_question"]
        if isinstance(description, str) and isinstance(question, str) and question not in description:
            errors.append(f"{location}: description must include the deciding question")
        members = family["operations"]
        if not isinstance(members, list):
            errors.append(f"{location}.operations: expected an array")
            continue
        if not 2 <= len(members) <= 10:
            errors.append(f"{location}: expected between 2 and 10 operations, got {len(members)}")
        for operation in members:
            if not isinstance(operation, str) or not re.fullmatch(IDENTIFIER, operation):
                errors.append(f"{location}: invalid operation ID {operation!r}")
            else:
                operations.append(operation)
    duplicate_ids = sorted(key for key, count in Counter(identifiers).items() if count > 1)
    duplicates = sorted(key for key, count in Counter(operations).items() if count > 1)
    missing = sorted(set(registered) - set(operations))
    unknown = sorted(set(operations) - set(registered))
    for label, values in (
        ("Duplicate family IDs", duplicate_ids),
        ("Operations assigned more than once", duplicates),
        ("Missing registry operations", missing),
        ("Unknown operation IDs", unknown),
    ):
        if values:
            errors.append(f"{label}: {', '.join(values)}")
    return errors


def _declared_json_families(value, record_ids, pointer="$"):
    """Read taxonomy declarations and native cards, not graph-generator families."""
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and value["id"] in record_ids and isinstance(value.get("family"), str):
            yield f"{pointer}.family", value["family"]
        if (isinstance(value.get("problem_id"), str) and value["problem_id"] in record_ids
                and "graph_input" in value and isinstance(value.get("category"), str)):
            yield f"{pointer}.category", value["category"]
        for key, child in value.items():
            location = f"{pointer}.{key}"
            if key == "families" and isinstance(child, list):
                for index, family in enumerate(child):
                    identifier = family.get("id") if isinstance(family, dict) else None
                    if isinstance(family, str) and "term" in value:
                        identifier = family  # A vague-term routing declaration.
                    if isinstance(identifier, str):
                        yield f"{location}[{index}]", identifier
            yield from _declared_json_families(child, record_ids, location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _declared_json_families(child, record_ids, f"{pointer}[{index}]")


def _family_accessor(node):
    if isinstance(node, ast.Name):
        # A bare `family` can name a synthetic graph distribution instead.
        return node.id in {"family_id", "preferred_family"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"family", "family_id"}
    if isinstance(node, ast.Subscript):
        return (isinstance(node.value, ast.Name)
                and node.value.id in {"card", "operation", "problem"}
                and isinstance(node.slice, ast.Constant) and node.slice.value == "family")
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == "family")


def _declared_python_families(source, record_ids):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            for operator, right in zip(node.ops, node.comparators):
                if _family_accessor(left):
                    try:
                        value = ast.literal_eval(right)
                    except (ValueError, TypeError, SyntaxError):
                        value = None
                    values = value if isinstance(operator, (ast.In, ast.NotIn)) and isinstance(value, (list, tuple, set)) else [value]
                    for identifier in values:
                        if isinstance(identifier, str) and re.fullmatch(IDENTIFIER, identifier):
                            yield node.lineno, identifier
                left = right
        if isinstance(node, ast.Dict):
            fields = {
                key.value: value.value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
                and isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            if fields.get("id") in record_ids and "family" in fields:
                yield node.lineno, fields["family"]
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name)
                   and (target.id == "FAMILIES" or target.id.endswith("_FAMILIES"))
                   for target in targets):
            continue
        try:
            rows = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue  # A generated/imported taxonomy has no literal declarations.
        if not isinstance(rows, (tuple, list, set)):
            continue
        for row in rows:
            if isinstance(row, str):
                yield node.lineno, row
            elif isinstance(row, dict):
                if isinstance(row.get("id"), str):
                    yield node.lineno, row["id"]
            elif isinstance(row, (tuple, list)) and row and isinstance(row[0], str):
                yield node.lineno, row[0]
                # The former routing tuple also declared its library-family set.
                for field in row[1:]:
                    if isinstance(field, set):
                        for identifier in field:
                            if isinstance(identifier, str):
                                yield node.lineno, identifier


def _markdown_family_columns(source):
    columns = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            columns = []
            continue
        cells = [cell.strip().strip(chr(96)) for cell in line.strip().strip("|").split("|")]
        headers = [index for index, cell in enumerate(cells)
                   if cell.casefold() in {"family", "family id", "problem family", "routing family"}]
        if headers:
            columns = headers
        else:
            for index in columns:
                if index < len(cells) and re.fullmatch(IDENTIFIER, cells[index]):
                    yield line_number, cells[index]


def source_family_references(path: Path, record_ids: set[str]):
    """Inspect family identifiers, leaving algorithm names and ordinary words alone.

    The allowlist comes solely from the new manifest. There is no retired-ID list
    or migration mapping to keep alive after the old taxonomy is removed.
    """
    source = path.read_text()
    if not re.search(r"\b(?:(?:\w*_)?famil(?:y|ies)|family_id|preferred_family|category)\b", source, re.IGNORECASE):
        return
    text = html.unescape(source) if path.suffix == ".html" else source
    for pattern in FAMILY_REFERENCES:
        for match in pattern.finditer(text):
            yield str(text.count("\n", 0, match.start()) + 1), match["family"]
    if path.suffix == ".json":
        yield from _declared_json_families(json.loads(source), record_ids)
    elif path.suffix == ".py":
        for line, family in _declared_python_families(source, record_ids):
            yield str(line), family
    elif path.suffix == ".md":
        for line, family in _markdown_family_columns(source):
            yield str(line), family
    elif path.suffix in {".html", ".cpp", ".hpp", ".h", ".cu", ".c"}:
        if path.suffix == ".html":
            text = re.sub(r"<[^>]*>", "", text)
        pattern = (rf"""["']family["']\s*:\s*{LITERAL}""" if path.suffix == ".html"
                   else rf"""\{{\s*["']family["']\s*,\s*{LITERAL}""")
        for match in re.finditer(pattern, text):
            yield str(text.count("\n", 0, match.start()) + 1), match["family"]
    elif path.suffix in {".js", ".mjs", ".ts"}:
        # Literal label maps indexed by a family ID are taxonomy declarations.
        for mapping in re.finditer(r"\(\s*\{(?P<body>.*?)\}\s*\)\s*\[\s*family\.id\s*\]", text, re.DOTALL):
            for key in re.finditer(rf"""(?:^|,)\s*["']?(?P<family>{IDENTIFIER})["']?\s*:""", mapping["body"]):
                offset = mapping.start("body") + key.start()
                yield str(text.count("\n", 0, offset) + 1), key["family"]


def invalid_family_references(root: Path, valid: set[str]) -> list[str]:
    # Include source, configs, docs, tests, UI and recorded JSON. Ignore build
    # products and vendored research inputs, which are not this repository's API.
    registry_root = root if (root / "library/runtime/registry.cpp").is_file() else ROOT
    record_ids = {identifier for card in registry_cards(registry_root) for identifier in card}
    command = [
        "rg", "--files", "--hidden", "--null",
        "-g", "!.git/**", "-g", "!**/.pytest_cache/**", "-g", "!**/__pycache__/**",
        "-g", "!**/node_modules/**", "-g", "!**/.venv*/**", "-g", "!**/build/**",
        "-g", "!problems/_sources/**", "-g", "!problems/*/papers/**",
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode())
    errors = set()
    for name in result.stdout.decode().split("\0"):
        if not name:
            continue
        path = root / name
        if path.suffix not in TEXT_SUFFIXES and path.name != "CMakeLists.txt":
            continue
        for location, family in source_family_references(path, record_ids):
            if family not in valid:
                errors.add(f"{name}:{location}: unknown family identifier {family!r}")
    return sorted(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-only", action="store_true",
                        help="Check manifest coverage without the repository migration gate")
    parser.add_argument("--report", type=Path, help="Write every validation error as JSON")
    args = parser.parse_args()
    from family_catalog import taxonomy
    document = taxonomy(ROOT)
    registered = registry_operations(ROOT)
    errors = validate_taxonomy(document, registered)
    if not errors and not args.taxonomy_only:
        errors = invalid_family_references(ROOT, {row["id"] for row in document["families"]})
    if args.report:
        args.report.write_text(json.dumps({"errors": errors}, indent=2) + "\n")
    if errors:
        for error in errors[:60]:
            print(error)
        if len(errors) > 60:
            print(f"... and {len(errors) - 60} more; use --report for the complete list")
        print(f"FAIL: {len(errors)} taxonomy/reference errors")
        return 1
    print(f"PASS: {len(document['families'])} families cover {len(registered)} operations exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
