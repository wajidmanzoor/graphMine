"""Bounded family and problem selection, separate from execution contracts."""

from copy import deepcopy

from ._families import FAMILIES, PROBLEMS


FAMILY_INSTRUCTION = (
    "Select the one family whose deciding question best matches the person's goal. "
    "The catalog contains only family descriptions. Do not select a problem, operation, "
    "algorithm, backend or parameters. A preferred_family is a hint, not a restriction. "
    "For a workflow, choose the family of its main requested result; required preparation "
    "steps are resolved later. For a follow-up or conceptual question choose its closest "
    "subject family; the later intent stage handles answers and display changes. "
    "Return its family_id and one short reason. If a previous family was rejected, "
    "choose the best remaining family using the supplied failure reason."
)
PROBLEM_INSTRUCTION = (
    "Select up to two distinct problems from this selected family's catalog, ranked "
    "by relevance to the person's question. Give a short reason for each. Select one "
    "when only one is relevant; never pad the list with an unrelated problem. These "
    "are alternatives, not instructions to execute both. Do not choose algorithms, "
    "backends or parameters. Set requires_cross_family_steps only when the question "
    "explicitly needs a dependency or additional result outside this family's problems; "
    "do not use it for uncertainty about the main objective. Missing input data or "
    "parameters are handled later. If no problem fits this family's subject, request "
    "reroute. If the goal remains ambiguous, return needs_information with one short "
    "deciding question. For conceptual questions or saved-result follow-ups select "
    "the relevant subject problem; the later intent stage handles answering or display."
)


def family_context():
    """Exactly the metadata in family.json: no problem or operation details."""
    return {row["id"]: {key: deepcopy(row[key])
                         for key in ("title", "description", "deciding_question")}
            for row in FAMILIES}


def problem_context(family_id):
    return deepcopy(PROBLEMS[family_id])


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def family_schema(excluded=()):
    return _object({"family_id": {"enum": [row["id"] for row in FAMILIES if row["id"] not in excluded]},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 600}})


def problem_schema(family_id):
    message = {"type": "string", "minLength": 1, "maxLength": 600}
    return {"oneOf": [
        _object({"status": {"const": "selected"},
                 "candidates": {"type": "array", "minItems": 1, "maxItems": min(2, len(PROBLEMS[family_id])),
                                "items": _object({"problem_id": {"enum": list(PROBLEMS[family_id])},
                                                  "reason": message})},
                 "requires_cross_family_steps": {"type": "boolean"}, "message": message}),
        *[_object({"status": {"const": status}, "message": message})
          for status in ("reroute", "needs_information", "unsupported")],
    ]}


def candidate_operations(family_id, decision):
    identifiers = [row["problem_id"] for row in decision["candidates"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Problem candidates must be distinct")
    return [operation for identifier in identifiers
            for operation in PROBLEMS[family_id][identifier]["operation_ids"]]
