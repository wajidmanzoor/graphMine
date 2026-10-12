"""Finish a user-limited teacher collection without starting any trainer."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from ..history import HistoryStore
from ..models import utc_now
from . import dual_teacher
from .data_selection import FILENAME, VERSION, effective_split
from .dual_review import VALIDATION_ERRORS, verified_target
from .reusable_data import package, verify_package

STAGES = {"PlanDraft", "RouteDecision", "TurnDecision"}


def inventory(root, adapter=None):
    result = []
    for path in sorted((root / "teacher-inputs").glob("*.json")):
        job = json.loads(path.read_text())
        if adapter is None or job["adapter"] == adapter:
            result.append(job)
    return result


def binding(root, job):
    target = root / "teacher-targets" / (job["id"] + ".json")
    artifact = json.loads(target.read_text())
    return {
        "input_sha256": job["sha256"],
        "teacher_sha256": HistoryStore.digest(target),
        "original_status": artifact["status"],
    }


def make_selection(root, jobs, policy):
    records = {
        job["id"]: binding(root, job)
        for job in jobs
        if (root / "teacher-targets" / (job["id"] + ".json")).exists()
    }
    return {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
        "policy_sha256": HistoryStore.digest(root / "collection-policy.json"),
        "holdout_lineages": policy["holdout_lineages"],
        "records": records,
        "scope": "User-limited data-only collection. Remaining requests and flagged responses are deferred; no training is authorized.",
    }


def snapshot_analyst(settings, root, policy):
    destination = root / "analyst-data-v1"
    if destination.exists():
        return verify_package(destination)
    jobs = inventory(root, "analyst")
    saved = make_selection(root, jobs, policy)
    if saved["records"] != policy["analyst_frozen_records"]:
        raise ValueError("Analyst collection changed after the requested cutoff")
    with tempfile.TemporaryDirectory(
        prefix=".analyst-snapshot-", dir=root
    ) as temporary:
        source = Path(temporary) / "source"
        files = [root / "corpus.json"]
        files += sorted(root.glob("business-question-teacher*.json"))
        files += [
            root / name
            for name in (
                "question-input-manifest.json",
                "conversation-input-manifest.json",
            )
            if (root / name).exists()
        ]
        for folder in ("references/cases", "references/question-derivatives"):
            files += sorted((root / folder).glob("*.json"))
        for job in jobs:
            files.append(root / "teacher-inputs" / (job["id"] + ".json"))
            if job["id"] in saved["records"]:
                files.append(root / "teacher-targets" / (job["id"] + ".json"))
        for original in files:
            linked = source / original.relative_to(root)
            linked.parent.mkdir(parents=True, exist_ok=True)
            os.link(original, linked)
        HistoryStore.write(source / FILENAME, saved)
        package(settings, source, destination, require_complete=True)
    return verify_package(destination)


def planner_progress(settings, root, jobs, policy, cache):
    counts = Counter()
    stages = {"train": set(), "validation": set()}
    for job in jobs:
        path = root / "teacher-targets" / (job["id"] + ".json")
        if not path.exists():
            continue
        artifact = json.loads(path.read_text())
        if artifact["status"] != "accepted":
            continue
        fingerprint = HistoryStore.digest(path)
        if cache.get(job["id"], (None,))[0] != fingerprint:
            try:
                verified_target(settings, root, job, artifact)
                cache[job["id"]] = (fingerprint, True)
            except VALIDATION_ERRORS:
                cache[job["id"]] = (fingerprint, False)
        if cache[job["id"]][1]:
            split = effective_split(policy, job)
            counts[split] += 1
            stages[split].add(job["schema"])
    return dict(counts), {key: sorted(values) for key, values in stages.items()}


def next_batch(root, jobs, policy, counts, stages):
    """Only request missing planner rows; never retry the saved review queue."""
    for desired in ("train", "validation"):
        target = policy["planner_accepted_targets"][desired]
        deficit = target - counts.get(desired, 0)
        if deficit <= 0 and STAGES <= set(stages[desired]):
            continue
        candidates = [job for job in jobs if job["split"] == desired]
        missing_stages = STAGES - set(stages[desired])
        offsets = [
            index
            for index, job in enumerate(candidates)
            if effective_split(policy, job) == desired
            and not (root / "teacher-targets" / (job["id"] + ".json")).exists()
        ]
        if deficit <= 0:
            offsets = [
                index
                for index in offsets
                if candidates[index]["schema"] in missing_stages
            ]
        if not offsets:
            raise ValueError(
                "Planner inputs exhausted before the accepted target: " + desired
            )
        offset = offsets[0]
        limit = min(50, max(1, deficit), len(candidates) - offset)
        return desired, offset, limit
    return None


async def wait_for_initial_batch(root, policy, status):
    unit = policy.get("initial_planner_unit")
    if not unit:
        return
    status(root, "waiting_for_initial_planner_batch", unit=unit)
    while True:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
                "-p",
                "ExecMainStatus",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            await asyncio.sleep(30)
            continue
        fields = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        if (
            fields.get("ActiveState") == "active"
            and int(fields.get("MainPID", "0")) > 0
        ):
            await asyncio.sleep(30)
            continue
        report_path = root / "teacher-run-planner-train-0.json"
        if not report_path.exists():
            raise RuntimeError(
                "Initial planner batch stopped before publishing its result; saved data is preserved"
            )
        report = json.loads(report_path.read_text())
        if report["selected"] != 200 or report["outcomes"].get("not_started"):
            raise RuntimeError(
                "Initial planner batch did not finish its requested calls"
            )
        return


def write_summary(root, manifest, policy):
    counts = manifest["counts"]
    rows = [
        json.loads(line)
        for line in (root / "reusable-dataset-v1/teacher-responses.jsonl")
        .read_text()
        .splitlines()
    ]
    by_adapter = {}
    for adapter in ("analyst", "planner"):
        subset = [row for row in rows if row["adapter"] == adapter]
        by_adapter[adapter] = {
            "saved_responses": len(subset),
            "accepted_training_rows": counts.get(f"sft/{adapter}/train.jsonl", 0),
            "accepted_validation_rows": counts.get(
                f"sft/{adapter}/validation.jsonl", 0
            ),
            "review_later": sum(row["status"] != "accepted" for row in subset),
            "stages": dict(Counter(row["schema"] for row in subset)),
        }
    report = {
        "created_at": utc_now().isoformat(),
        "training_started": False,
        "automatic_training": False,
        "adapters": by_adapter,
        "deferred_requests": len(manifest["deferred_teacher_calls"]),
        "teacher": policy["teacher"],
        "generation_method": "Frozen production prompts and schemas, native graph results plus independent reference checks, ChatGPT final structured responses, automatic schema/grounding/chart checks, and a fresh validation pass before SFT export. Flagged responses are retained separately and never auto-repaired in this run.",
        "holdout_lineages": policy["holdout_lineages"],
        "human_review": False,
        "files": manifest["files"],
    }
    HistoryStore.write(root / "data-generation-summary.json", report)
    lines = [
        "# Data generation summary",
        "",
        "Data collection only. No fine-tuning, model evaluation, or deployment was started.",
        "",
        "| Adapter | Saved responses | Accepted train | Accepted validation | Review later |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for adapter, values in by_adapter.items():
        lines.append(
            f"| {adapter} | {values['saved_responses']} | {values['accepted_training_rows']} | {values['accepted_validation_rows']} | {values['review_later']} |"
        )
    lines += [
        "",
        "The teacher was `gpt-6.1-sol` through the existing ChatGPT account, with maximum reasoning effort, tools disabled, and four concurrent requests. Only final responses are included in the portable dataset.",
        "",
        report["generation_method"],
        "",
        "The data includes graph planning/routing and conversation decisions, grounded result explanations, and custom-chart requests. Source graphs include public graph samples and synthetic families. Business-question and clarification proposals are preserved with their original prompts and model provenance.",
        "",
        "Original input and response bytes were retained. For this release, the whole `synthetic:directed_cycle_chords` training family is reserved for validation across both adapters; the original collection labels remain in the provenance. Reserved test cases were not used to generate training targets. This analyst validation subset is limited to one source family; it is not a broad quality evaluation.",
        "",
        f"{report['deferred_requests']} remaining requests are saved in `reusable-dataset-v1/deferred-inputs.jsonl` for the next collection run. Flagged responses are in `review-later.jsonl`, excluded from SFT. No human review is claimed.",
        "",
        "See `reusable-dataset-v1/README.md` for file formats and `manifest.json` for SHA-256 hashes, source splits, counts, and the explicit current-run selection.",
    ]
    (root / "DATA_GENERATION_SUMMARY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


async def collect(settings, root, status):
    policy = json.loads((root / "collection-policy.json").read_text())
    if policy["mode"] != "data_only" or policy["automatic_training"]:
        raise ValueError("This controller requires an explicit data-only policy")
    status(root, "saving_frozen_analyst_data", training_authorized=False)
    analyst = await asyncio.to_thread(snapshot_analyst, settings, root, policy)
    status(
        root, "analyst_data_saved", archive="analyst-data-v1", counts=analyst["counts"]
    )
    await wait_for_initial_batch(root, policy, status)
    jobs = inventory(root, "planner")
    cache = {}
    while True:
        counts, stages = await asyncio.to_thread(
            planner_progress, settings, root, jobs, policy, cache
        )
        batch = next_batch(root, jobs, policy, counts, stages)
        if batch is None:
            break
        split, offset, limit = batch
        status(
            root,
            "generating_planner_data",
            accepted=counts,
            stages=stages,
            targets=policy["planner_accepted_targets"],
            split=split,
            offset=offset,
            limit=limit,
            analyst_collection="frozen",
            training_authorized=False,
        )
        result = await dual_teacher.generate(
            settings,
            root,
            adapter="planner",
            split=split,
            offset=offset,
            limit=limit,
            concurrency=4,
        )
        if result["outcomes"].get("not_started"):
            raise RuntimeError(
                "Teacher allowance interrupted planner collection; saved outputs are preserved"
            )
    all_jobs = inventory(root)
    selection = make_selection(root, all_jobs, policy)
    if {
        key: value
        for key, value in selection["records"].items()
        if key in policy["analyst_frozen_records"]
    } != policy["analyst_frozen_records"]:
        raise ValueError("Frozen analyst evidence changed")
    for job in inventory(root, "analyst"):
        if (
            job["id"] in selection["records"]
            and job["id"] not in policy["analyst_frozen_records"]
        ):
            raise ValueError("Unexpected analyst collection after the cutoff")
    selection_path = root / FILENAME
    if selection_path.exists():
        previous = json.loads(selection_path.read_text())
        if (
            previous["records"] != selection["records"]
            or previous["holdout_lineages"] != selection["holdout_lineages"]
        ):
            raise ValueError("Published current-run selection changed")
    else:
        HistoryStore.write(selection_path, selection)
    destination = root / "reusable-dataset-v1"
    status(
        root, "exporting_data_only_release", accepted=counts, training_authorized=False
    )
    if not destination.exists():
        with tempfile.TemporaryDirectory(
            prefix=".data-only-release-", dir=root
        ) as temporary:
            release = Path(temporary) / "release"
            manifest = await asyncio.to_thread(
                package, settings, root, release, require_complete=True
            )
            for split, target in policy["planner_accepted_targets"].items():
                if manifest["counts"].get(f"sft/planner/{split}.jsonl", 0) < target:
                    raise ValueError(
                        "Final planner validation fell below the requested collection target"
                    )
            release.rename(destination)
    checked = verify_package(destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    summary = write_summary(root, manifest, policy)
    status(
        root,
        "data_collection_complete_training_not_started",
        reusable_dataset=str(destination),
        verification=checked,
        summary=summary["adapters"],
        training_authorized=False,
    )
    return summary
