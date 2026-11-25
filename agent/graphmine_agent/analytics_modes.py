"""Supported analysis modes and safe presentation of saved workflows."""

from typing import Literal

from .workflow_compat import saved_workflow


AnalysisMode = Literal["normal", "expert"]


def saved_mode(record):
    """Keep historical manual workflows reviewable without enabling old modes."""
    record = saved_workflow(record)
    if "mode" not in record or record["mode"] in {"normal", "expert"}:
        return record
    return {**record, "mode": "expert"}
