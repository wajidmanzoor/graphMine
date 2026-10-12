"""Bind an explicitly limited collection without rewriting teacher evidence."""

from __future__ import annotations

import json

from ..history import HistoryStore

FILENAME = "current-run-selection.json"
VERSION = "graphmine-current-run-selection-v1"


def source_splits(corpus):
    result = {}
    for case in corpus["cases"]:
        prior = result.setdefault(case["lineage"], case["split"])
        if prior != case["split"]:
            raise ValueError("A source lineage occurs in multiple splits")
    return result


def load_selection(root, corpus):
    path = root / FILENAME
    if not path.exists():
        return None
    selection = json.loads(path.read_text())
    if selection.get("version") != VERSION or selection.get(
        "corpus_sha256"
    ) != HistoryStore.digest(root / "corpus.json"):
        raise ValueError("Current-run selection does not bind the source corpus")
    original = source_splits(corpus)
    held_out = selection["holdout_lineages"]
    if len(set(held_out)) != len(held_out) or any(
        original.get(lineage) != "train" for lineage in held_out
    ):
        raise ValueError("Only whole training source lineages may become validation")
    inputs = {p.stem: p for p in (root / "teacher-inputs").glob("*.json")}
    if not selection["records"] or not set(selection["records"]) <= set(inputs):
        raise ValueError("Current-run selection contains missing or unknown inputs")
    for identifier, binding in selection["records"].items():
        job = json.loads(inputs[identifier].read_text())
        target = root / "teacher-targets" / (identifier + ".json")
        if (
            job["id"] != identifier
            or job["split"] not in {"train", "validation"}
            or original.get(job["lineage"]) != job["split"]
            or job["sha256"] != binding["input_sha256"]
            or not target.is_file()
            or HistoryStore.digest(target) != binding["teacher_sha256"]
            or json.loads(target.read_text())["status"] != binding["original_status"]
        ):
            raise ValueError("Current-run teacher binding changed: " + identifier)
    return selection


def selected(selection, job):
    return selection is None or job["id"] in selection["records"]


def effective_split(selection, job):
    if selection and job["lineage"] in selection["holdout_lineages"]:
        if job["split"] != "train":
            raise ValueError(
                "Only training inputs may enter the new validation holdout"
            )
        return "validation"
    return job["split"]


def effective_sources(selection, original):
    return {
        lineage: (
            "validation"
            if selection and lineage in selection["holdout_lineages"]
            else split
        )
        for lineage, split in original.items()
    }


def require_eligible_for_training(selection, job):
    if selection and selection["records"][job["id"]]["original_status"] != "accepted":
        raise ValueError("Saved for later review; excluded from this training run")
