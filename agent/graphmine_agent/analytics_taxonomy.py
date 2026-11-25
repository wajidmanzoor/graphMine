"""One family selection; executable problems go directly to routing."""
from copy import deepcopy
from ._families import FAMILIES

FAMILY_INSTRUCTION = (
    "Select the family whose deciding question best matches the person's main requested result. "
    "Do not choose problems, backends or parameters. preferred_family is a hint. "
    "For a workflow choose the family of the main result; routing resolves explicitly requested dependencies. "
    "For follow-ups retain their subject. If a family was rejected, select a remaining family. "
    "Return family_id and one short reason."
)


def family_context():
    return {row["id"]: {key: deepcopy(row[key]) for key in ("title", "description", "deciding_question")}
            for row in FAMILIES}


def family_schema(excluded=()):
    return {"type": "object", "properties": {
        "family_id": {"enum": [row["id"] for row in FAMILIES if row["id"] not in excluded]},
        "reason": {"type": "string", "minLength": 1, "maxLength": 600}},
        "required": ["family_id", "reason"], "additionalProperties": False}
