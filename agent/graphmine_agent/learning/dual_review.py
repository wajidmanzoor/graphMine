"""Recheck saved teacher outputs and prepare bounded analyst repair examples."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from ..analysis import CHART_REPAIR_GUIDANCE
from ..config import Settings
from ..history import HistoryStore
from ..llm import runtime_messages, runtime_schema
from ..models import LLMMode
from .catalog_suite import digest
from .codex import parse_stream
from .dual_teacher import SCHEMAS, check_target

VALIDATION_ERRORS = (
    ValueError,
    RuntimeError,
    OSError,
    KeyError,
    TypeError,
    AssertionError,
    SchemaValidationError,
)


def verified_target(settings, root, job, artifact):
    """Saved pass flags are ignored; the response, schema and checks are replayed."""
    if artifact["input_sha256"] != job["sha256"]:
        raise ValueError("Teacher input hash mismatch")
    profile = artifact["profile"]
    if profile["provider"] != "codex" or profile["reasoning_effort"] not in {
        "max",
        "high",
        "xhigh",
    }:
        raise ValueError("Expected the requested high/max-effort ChatGPT teacher")
    if (
        artifact["codex_cli"]["reasoning_effort"] != profile["reasoning_effort"]
        or artifact["codex_cli"]["exit_code"] != 0
    ):
        raise ValueError("Teacher CLI provenance does not match the requested profile")
    text, _ = parse_stream(artifact["raw_response"], profile["max_output_tokens"])
    raw = json.loads(text)
    Draft202012Validator(job["output_schema"]).validate(raw)
    target = SCHEMAS[job["schema"]].model_validate(raw)
    if target.model_dump(mode="json") != artifact["target"]:
        raise ValueError("Stored target differs from the actual teacher response")
    check_target(settings, root, job, target)
    return target


def review(settings, root, *, prepare_repairs=False):
    results = []
    for path in sorted((root / "teacher-targets").glob("*.json")):
        artifact = json.loads(path.read_text())
        job_path = root / "teacher-inputs" / path.name
        job = json.loads(job_path.read_text())
        record = {
            "id": job["id"],
            "input_sha256": job["sha256"],
            "teacher_sha256": HistoryStore.digest(path),
            "original_status": artifact["status"],
            "human_review": "unreviewed",
            "rules_sha256": HistoryStore.digest(
                Path(__file__).with_name("dual_teacher.py")
            ),
        }
        try:
            verified_target(settings, root, job, artifact)
            record["status"] = "accepted"
        except VALIDATION_ERRORS as error:
            record.update(
                status="quarantined", error=f"{type(error).__name__}: {error}"
            )
        if (
            prepare_repairs
            and record["status"] == "quarantined"
            and job["schema"] == "GroundedNarrative"
            and artifact.get("target")
            and job.get("variant") != "repair"
        ):
            repair = copy.deepcopy(job)
            repair.pop("sha256")
            repair["id"] += "-repair"
            repair["variant"] = "repair"
            repair["parent_teacher_sha256"] = HistoryStore.digest(path)
            repair["user_payload"].update(
                validation_feedback=record["error"].removeprefix("ValueError: "),
                previous_draft=artifact["target"],
                repair_guidance=CHART_REPAIR_GUIDANCE,
            )
            repair["messages"] = runtime_messages(
                mode=LLMMode.analyst,
                schema=SCHEMAS[repair["schema"]],
                user_payload=repair["user_payload"],
                conversation=repair["conversation"],
            )
            repair["output_schema"] = runtime_schema(
                SCHEMAS[repair["schema"]], repair["user_payload"]
            )
            repair["sha256"] = digest(repair)
            destination = root / "teacher-inputs" / (repair["id"] + ".json")
            if not destination.exists():
                HistoryStore.write(destination, repair)
            record["repair_input"] = str(destination.relative_to(root))
        HistoryStore.write(root / "teacher-reviews" / path.name, record)
        results.append(record)
    report = {
        "reviewed": len(results),
        "counts": dict(Counter(row["status"] for row in results)),
        "recovered_from_initial_quarantine": sum(
            row["original_status"] == "quarantined" and row["status"] == "accepted"
            for row in results
        ),
        "repair_inputs": sum("repair_input" in row for row in results),
        "human_review": "unreviewed",
        "scope": "Recomputed automatic checks, including raw teacher response binding. No claims of human preference or semantic perfection.",
    }
    HistoryStore.write(root / "teacher-review-summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare-repairs", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            review(Settings.from_env(), args.root, prepare_repairs=args.prepare_repairs)
        )
    )


if __name__ == "__main__":
    main()
