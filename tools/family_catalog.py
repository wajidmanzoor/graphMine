"""Canonical Family -> Runnable Problem -> Backend membership."""
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


def read_topics(root=ROOT):
    topics = json.loads((root / "catalog/topics.json").read_text(), object_pairs_hook=_unique_object)
    for identifier, topic in topics.items():
        if set(topic) != {"title", "description"} or not all(isinstance(v, str) and v.strip() for v in topic.values()):
            raise ValueError(f"Topic {identifier} must contain only documentation text")
    return topics


def read_catalog(root=ROOT):
    families, problems = (json.loads((root / "catalog" / name).read_text(), object_pairs_hook=_unique_object)
                          for name in ("family.json", "problems.json"))
    topics = read_topics(root)
    if not isinstance(families, dict) or not isinstance(problems, dict) or set(families) != set(problems):
        raise ValueError("Runnable problem families must match family.json")
    seen = set()
    for family, metadata in families.items():
        if set(metadata) != {"title", "description", "deciding_question"}:
            raise ValueError(f"Invalid family metadata: {family}")
        if not isinstance(problems[family], dict) or not problems[family]:
            raise ValueError(f"Family {family} must contain runnable problems")
        for identifier, problem in problems[family].items():
            if identifier in seen:
                raise ValueError(f"Problem {identifier} belongs to multiple families")
            seen.add(identifier)
            if set(problem) != {"title", "description", "topic"}:
                raise ValueError(f"Problem {identifier}: unexpected or missing fields")
            if not all(isinstance(v, str) and v.strip() for v in problem.values()) or problem["topic"] not in topics:
                raise ValueError(f"Invalid runnable problem metadata: {identifier}")
    return families, problems


def taxonomy(root=ROOT):
    families, problems = read_catalog(root)
    return {"schema_version": 1, "families": [
        {"id": identifier, **family, "problems": list(problems[identifier])}
        for identifier, family in families.items()]}


def problem_metadata(root=ROOT):
    return {"schema_version": 1, "scope": "Generated documentation topics; no executable contracts.",
            "topics": [{"id": identifier, **metadata} for identifier, metadata in read_topics(root).items()]}
