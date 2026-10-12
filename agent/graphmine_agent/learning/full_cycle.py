"""Resumable orchestration for the larger, explicitly authorized teacher cycle."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path

from ..config import Settings
from ..history import HistoryStore
from ..models import utc_now
from . import (
    dual_conversations,
    dual_questions,
    dual_recovery,
    dual_review,
    dual_teacher,
)
from .dual_finetune import export
from .reusable_data import add_chart_curriculum, package, verify_package


def status(root, phase, **details):
    record = {
        "phase": phase,
        "pid": os.getpid(),
        "updated_at": utc_now().isoformat(),
        **details,
    }
    HistoryStore.write(root / "data-cycle-status.json", record)
    print(json.dumps(record), flush=True)


def select_question_cases(root, corpus):
    selected = []
    for split, count in (("train", 2), ("validation", 1)):
        operations = sorted(
            {
                c["task"]["operation_id"]
                for c in corpus["cases"]
                if c["task"]["operation_id"]
            }
        )
        for operation in operations:
            eligible = []
            for case in corpus["cases"]:
                if (
                    case["split"] != split
                    or case["task"]["operation_id"] != operation
                    or case["task"]["expected_status"] != "ready"
                ):
                    continue
                reference = json.loads(
                    (root / "references/cases" / (case["id"] + ".json")).read_text()
                )
                if reference["status"] == "verified":
                    eligible.append(case)
            eligible.sort(key=lambda c: (len(c["graph"]["vertices"]), c["id"]))
            if eligible:
                selected.append(eligible[0])
                if count == 2 and len(eligible) > 1:
                    selected.append(eligible[-1])
    return selected


def input_counts(root, *, adapter, split, variant=None):
    rows = [
        json.loads(path.read_text())
        for path in (root / "teacher-inputs").glob("*.json")
    ]
    return sum(
        row["adapter"] == adapter
        and row["split"] == split
        and (variant is None or row.get("variant") == variant)
        for row in rows
    )


async def generate_batches(settings, root, *, variant=None, retry_transport=False):
    for adapter in ("analyst", "planner"):
        for split in ("train", "validation"):
            count = input_counts(root, adapter=adapter, split=split, variant=variant)
            for offset in range(0, count, 200):
                status(
                    root,
                    "generating_teacher_targets",
                    adapter=adapter,
                    split=split,
                    offset=offset,
                    total=count,
                    variant=variant,
                    retry_transport=retry_transport,
                )
                report = await dual_teacher.generate(
                    settings,
                    root,
                    adapter=adapter,
                    split=split,
                    limit=min(200, count - offset),
                    offset=offset,
                    concurrency=4,
                    variant=variant,
                    retry_transport=retry_transport,
                )
                if report["outcomes"].get("not_started"):
                    raise RuntimeError(
                        "Teacher allowance interrupted this batch; existing responses are preserved"
                    )


async def prepare_data(settings, root):
    policy_path = root / "collection-policy.json"
    if (
        policy_path.exists()
        and json.loads(policy_path.read_text()).get("mode") == "data_only"
    ):
        from .collection_only import collect

        return await collect(settings, root, status)
    corpus = json.loads((root / "corpus.json").read_text())
    references = json.loads((root / "references/verification.json").read_text())
    if references["total"] != len(corpus["cases"]):
        raise ValueError("Reference verification did not cover the frozen corpus")
    from .catalog_suite import digest

    if references["corpus_sha256"] != digest(corpus):
        raise ValueError("Reference verification belongs to another corpus")
    status(
        root,
        "capturing_production_inputs",
        verified=references["verified"],
        total=references["total"],
    )
    if not (root / "teacher-input-manifest.json").exists():
        await dual_teacher.capture(settings, root, resume=True)
    if not (root / "question-input-manifest.json").exists():
        selected = select_question_cases(root, corpus)
        status(
            root,
            "generating_business_questions",
            scenarios=len(selected),
            teacher="gpt-6.1-sol",
            effort="max",
        )
        await dual_questions.run(settings, root, selected_cases=selected)
    if not (root / "conversation-input-manifest.json").exists():
        status(root, "capturing_conversations")
        await dual_conversations.augment(
            settings, root, train_count=64, validation_count=16
        )
    if not (root / "recovery-input-manifest.json").exists():
        status(root, "capturing_recovery")
        await dual_recovery.capture_recovery(
            settings,
            root,
            selected_cases=[
                case
                for case in corpus["cases"]
                if case["split"] in {"train", "validation"}
                and case["task"]["operation_id"] == "k-cliques"
                and case["task"]["expected_status"] == "ready"
            ],
        )
    add_chart_curriculum(root)
    status(
        root,
        "inputs_frozen",
        counts={
            adapter: {
                split: input_counts(root, adapter=adapter, split=split)
                for split in ("train", "validation")
            }
            for adapter in ("planner", "analyst")
        },
    )
    await generate_batches(settings, root)
    status(root, "reviewing_and_preparing_repairs")
    dual_review.review(settings, root, prepare_repairs=True)
    await generate_batches(settings, root, variant="repair")
    # Transport retries are bounded by the existing per-record retry receipt.
    await generate_batches(settings, root, retry_transport=True)
    reviewed = dual_review.review(settings, root)
    status(root, "exporting_reusable_data", review=reviewed)
    destination = root / "reusable-dataset-v1"
    if not destination.exists():
        package(settings, root, destination, require_complete=True)
    portable = verify_package(destination)
    if not portable["complete"]:
        raise ValueError("Reusable dataset is incomplete")
    exports = {}
    minimum = json.loads((root / "plan.json").read_text())[
        "minimum_accepted_training_rows"
    ]
    for adapter in ("planner", "analyst"):
        dataset = root / (adapter + "-dataset-v1")
        if dataset.exists():
            from .dual_finetune import read_export

            _, rows = read_export(dataset)
            exports[adapter] = {
                "rows": {split: len(values) for split, values in rows.items()}
            }
        else:
            exports[adapter] = export(settings, root, dataset, adapter)
        if exports[adapter]["rows"]["train"] < minimum[adapter]:
            raise ValueError(
                f"{adapter} needs more accepted training examples before this full run"
            )
    status(
        root,
        "data_ready_for_training",
        exports=exports,
        reusable_dataset=str(destination),
        review=reviewed,
    )
    return exports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    with (root / ".data-cycle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            result = asyncio.run(prepare_data(Settings.from_env(), root))
        except Exception as error:
            status(root, "failed", error_type=type(error).__name__, error=str(error))
            raise
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
