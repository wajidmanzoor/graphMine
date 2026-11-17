"""Read the family/problem catalog without importing the execution runtime."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate catalog key: {key}")
        result[key] = value
    return result


def read_catalog(root=ROOT):
    """Membership lives only in problems.json; family.json contains descriptions."""
    families, problems = (
        json.loads((root / "catalog" / name).read_text(), object_pairs_hook=_unique_object)
        for name in ("family.json", "problems.json")
    )
    if not isinstance(families, dict) or not isinstance(problems, dict):
        raise ValueError("Family and problem catalogs must be objects keyed by ID")
    if set(families) != set(problems):
        raise ValueError("Problem catalog family IDs must match family.json")
    seen = set()
    for identifier, family in families.items():
        if set(family) != {"title", "description", "deciding_question"}:
            raise ValueError(f"Family {identifier}: expected title, description and deciding_question only")
        if not isinstance(problems[identifier], dict) or not problems[identifier]:
            raise ValueError(f"Family {identifier} must contain problems")
        for problem_id, problem in problems[identifier].items():
            if problem_id in seen:
                raise ValueError(f"Problem {problem_id} belongs to multiple families")
            seen.add(problem_id)
            if set(problem) != {"title", "description", "operation_ids", "contract"}:
                raise ValueError(f"Problem {problem_id}: unexpected or missing fields")
            if not all(isinstance(problem[field], str) and problem[field].strip()
                       for field in ("title", "description")):
                raise ValueError(f"Problem {problem_id} needs a title and description")
            if not isinstance(problem["operation_ids"], list) or not problem["operation_ids"]:
                raise ValueError(f"Problem {problem_id} must declare operation IDs")
            if problem["contract"] is not None:
                path = (root / problem["contract"]).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    raise ValueError(f"Problem {problem_id} has an invalid contract path")
                if json.loads(path.read_text())["problem_id"] != problem_id:
                    raise ValueError(f"Problem {problem_id} does not match its contract")
    return families, problems


def taxonomy(root=ROOT):
    families, problems = read_catalog(root)
    return {"schema_version": 1, "families": [
        {"id": identifier, **family,
         "operations": [operation for problem in problems[identifier].values()
                        for operation in problem["operation_ids"]]}
        for identifier, family in families.items()
    ]}


def problem_metadata(root=ROOT):
    families, problems = read_catalog(root)
    return {"schema_version": 1,
            "scope": "Generated from catalog/family.json and catalog/problems.json; do not edit.",
            "problems": [{"id": identifier, "name": problem["title"], "contract": problem["contract"]}
                         for family in families for identifier, problem in problems[family].items()]}
