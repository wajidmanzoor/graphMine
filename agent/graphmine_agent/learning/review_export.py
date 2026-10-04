"""Export only semantically reviewed, replayed, oracle-checked paraphrases.

This creates local routing candidates, not a training job or an upload. Every
gate is recomputed from saved evidence; review flags alone are insufficient.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import RouteDecision, utc_now
from .corpus import digest
from .inference import ModelProfile
from .meaning import (
    MeaningExtraction,
    evidence_issues,
    expected_meaning,
    meaning_differences,
    wording_issues,
)
from .oracles import verify_output
from .pipeline import check_agent_outcome, training_route_payload
from .review import (
    calibrated_profile,
    distinct_reviewer,
    load_proposals,
    replay_contract_sha256,
    reviewer_contract_sha256,
    verified_artifact,
    verify_extraction_call,
)


def export_reviewed(
    settings: Settings,
    *,
    corpus: Path,
    candidates: Path,
    review: Path,
    calibration: Path | None,
    audit: Path,
    destination: Path,
) -> dict:
    manifest, graphs, proposals = load_proposals(corpus, candidates)
    reviewed = json.loads(review.read_text())
    native = json.loads(audit.read_text())
    if (
        reviewed.get("mode") != "semantic_candidate_review"
        or not reviewed.get("finished_at")
        or reviewed.get("corpus_sha256")
        != HistoryStore.digest(corpus / "manifest.json")
        or reviewed.get("proposals_sha256") != HistoryStore.digest(candidates)
        or reviewed.get("reviewer_contract_sha256") != reviewer_contract_sha256()
        or reviewed.get("replay_contract_sha256") != replay_contract_sha256()
        or reviewed.get("student_model") != settings.llm_model
        or reviewed.get("calibration_sha256")
        != (HistoryStore.digest(calibration) if calibration else None)
    ):
        raise ValueError(
            "Review is stale, incomplete, or belongs to different inputs/model"
        )
    if (
        native.get("mode") != "native_oracle"
        or not native.get("finished_at")
        or native.get("corpus_sha256") != HistoryStore.digest(corpus / "manifest.json")
        or native.get("checker_sha256")
        != HistoryStore.digest(Path(__file__).with_name("oracles.py"))
    ):
        raise ValueError("A current independent native-oracle audit is required")
    profile_data = reviewed["reviewer"]
    profile = ModelProfile(
        provider=profile_data["provider"],
        model=profile_data["model"],
        base_url=profile_data["base_url"]
        if profile_data["provider"] == "local"
        else None,
        max_output_tokens=profile_data["max_output_tokens"],
    )
    if profile.public() != profile_data:
        raise ValueError("Invalid reviewer profile")
    calibrated = calibrated_profile(corpus, manifest, calibration, profile)
    distinct = distinct_reviewer(
        proposals, profile, settings.llm_model, settings.llm_base_url
    )
    checks = {row["id"]: row for row in native["examples"]}
    reviews = {row["id"]: row for row in reviewed["candidates"]}
    if len(checks) != len(native["examples"]) or len(reviews) != len(
        reviewed["candidates"]
    ):
        raise ValueError("Duplicate example IDs in the audit or review")
    if set(reviews) != {row["id"] for row in proposals["candidates"]}:
        raise ValueError("Review must account for every proposal exactly once")
    if destination.exists():
        raise ValueError("Export destination already exists")
    examples = {row["id"]: row for row in manifest["examples"]}
    catalog = Catalog(settings)
    lines, accepted, quarantine = [], [], []
    for proposal in proposals["candidates"]:
        example = examples[proposal["example_id"]]
        graph, task = graphs[example["graph_id"]], example["task"]
        row = reviews[proposal["id"]]
        issues = []
        if not calibrated:
            issues.append("Reviewer has not passed the current semantic calibration")
        if not distinct:
            issues.append(
                "Generating/student model or same-server alias cannot approve candidates"
            )
        if (
            row.get("proposal_sha256") != digest(proposal)
            or row.get("example_id") != example["id"]
            or row.get("query") != proposal["query"]
        ):
            issues.append("Reviewed proposal changed")
        if row.get("training_eligible") is not True:
            issues.append("Review did not approve this candidate")
        reference = expected_meaning(task)
        issues.extend(wording_issues(proposal["query"], reference))
        try:
            extraction = MeaningExtraction.model_validate(row["extracted"])
            issues.extend(meaning_differences(reference, extraction.meaning))
            issues.extend(evidence_issues(proposal["query"], extraction))
            saved = verified_artifact(review.parent, row["call"], row["call_sha256"])
            verify_extraction_call(
                saved, profile, graph, proposal["query"], row["extracted"]
            )
        except (KeyError, OSError, TypeError, ValueError) as error:
            issues.append(f"Missing or invalid semantic evidence: {error}")
        try:
            replay = verified_artifact(
                review.parent, row["replay"], row["replay_sha256"]
            )
            if (
                replay.get("query") != proposal["query"]
                or replay.get("proposal_sha256") != digest(proposal)
                or replay.get("example_id") != example["id"]
            ):
                issues.append("Replay belongs to another question")
            issues.extend(check_agent_outcome(graph, task, replay["outcome"]))
        except (KeyError, OSError, TypeError, ValueError) as error:
            issues.append(f"Missing or invalid live replay: {error}")
        check = checks.get(example["id"])
        if (
            not check
            or check.get("passed") is not True
            or check.get("example_sha256") != digest(example)
        ):
            issues.append("Missing, failed or stale native audit")
        elif task["behavior"] == "execute":
            payload = check.get("payload", {})
            if payload.get("ok") is not True:
                issues.append("Native audit output was not successful")
            issues.extend(verify_output(graph, task, payload.get("output", {})))
        if issues:
            quarantine.append({"id": proposal["id"], "issues": issues})
            continue
        # The label's mathematical contract stays source-derived. Never copy a
        # reviewer's free-form answer into a gold label or leak its reasoning.
        label = copy.deepcopy(example["gold_route"])
        label["intent"]["objective"] = proposal["query"]
        RouteDecision.model_validate(label)
        payload = training_route_payload(
            catalog, example, graph, query=proposal["query"]
        )
        line = {
            "messages": [
                {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(label, ensure_ascii=False)},
            ]
        }
        lines.append(line)
        accepted.append(
            {
                "id": proposal["id"],
                "example_id": example["id"],
                "split": "train",
                "family": example["family"],
                "row_sha256": digest(line),
                "generator_model": proposal["teacher_model"],
                "reviewer": profile.public(),
                "label_source": "source_semantic_template_with_blind_review_and_oracle_checked_replay",
                "review_state": "automatic_candidate_not_human_reviewed",
                "stage": "RouteDecision",
            }
        )
    destination.mkdir(parents=True, mode=0o700)
    target = destination / "train.jsonl"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        for line in lines:
            stream.write(json.dumps(line, ensure_ascii=False) + "\n")
    metadata = {
        "schema_version": "1.0.0",
        "created_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "proposals_sha256": HistoryStore.digest(candidates),
        "review_sha256": HistoryStore.digest(review),
        "calibration_sha256": HistoryStore.digest(calibration) if calibration else None,
        "audit_sha256": HistoryStore.digest(audit),
        "exporter_sha256": HistoryStore.digest(Path(__file__)),
        "training_started": False,
        "rows": accepted,
        "quarantine": quarantine,
        "files": {"train": HistoryStore.digest(target)},
        "scope": "Automatically screened routing candidates only; no fine-tuning, uploads, or human-review claim. Validation/test families excluded. Small controls and distinct model identifiers do not establish universal semantic accuracy or independent model lineage.",
    }
    HistoryStore.write(destination / "provenance.json", metadata)
    return metadata
