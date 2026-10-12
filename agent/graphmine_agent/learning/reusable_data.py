"""Portable, hash-verified JSONL archives of teacher data and SFT messages."""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from collections import Counter
from pathlib import Path

from ..config import Settings
from ..history import HistoryStore
from ..llm import runtime_messages
from ..models import GroundedNarrative, LLMMode, utc_now
from .catalog_suite import digest
from .codex import parse_stream
from .data_selection import (
    effective_sources,
    effective_split,
    load_selection,
    require_eligible_for_training,
    selected,
)
from .dual_review import VALIDATION_ERRORS, verified_target


def add_chart_curriculum(root, *, evaluation_only=False):
    """Capture explicit chart requests for each verified nonempty result."""
    created = []
    prompts = (
        "Explain these results and create one custom comparison chart using the supplied analysis datasets. Give the chart a clear title and readable entity labels. Cite the facts behind your explanation and retain the sample limitations.",
        "Make a compact visual report from these results. Include a custom chart that makes the most useful comparison easy to see, with a tooltip for details. Explain only what the supplied evidence supports.",
        "Create a custom chart to help me explore these computed results. Use a linked selection where the available fields support it, and explain what selecting an item does. Keep all numeric claims tied to cited facts.",
    )
    folder = root / ("final-test-inputs" if evaluation_only else "teacher-inputs")
    paths = sorted(folder.glob("*.json"))
    for index, path in enumerate(paths):
        job = json.loads(path.read_text())
        if job["schema"] != "GroundedNarrative" or job.get("variant"):
            continue
        datasets = job["user_payload"]["analysis_context"]["datasets"]
        if not any(table.get("sample_rows") for table in datasets.values()):
            continue
        job = copy.deepcopy(job)
        job.pop("sha256")
        job["id"] += "-custom-chart"
        job["variant"] = "custom_chart"
        job["required_custom_charts"] = 1
        job["user_payload"]["user_message"] = prompts[index % len(prompts)]
        job["messages"] = runtime_messages(
            mode=LLMMode.analyst,
            schema=GroundedNarrative,
            user_payload=job["user_payload"],
            conversation=job["conversation"],
        )
        job["sha256"] = digest(job)
        target = folder / (job["id"] + ".json")
        if target.exists():
            if json.loads(target.read_text())["sha256"] != job["sha256"]:
                raise ValueError("Existing custom chart input changed")
        else:
            HistoryStore.write(target, job)
        created.append(job["id"])
    manifest = (
        "final-test-chart-inputs.json"
        if evaluation_only
        else "chart-input-manifest.json"
    )
    HistoryStore.write(root / manifest, {"ids": created, "count": len(created)})
    return len(created)


def package(settings, root, destination, *, require_complete=False):
    """Publish a complete archive atomically; failed exports leave no release."""
    if destination.exists():
        raise ValueError("Dataset releases are immutable; use a new destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="." + destination.name + "-", dir=destination.parent
    ) as temporary:
        staged = Path(temporary) / "release"
        manifest = _write_package(
            settings, root, staged, require_complete=require_complete
        )
        verify_package(staged)
        if destination.exists():
            raise ValueError("Dataset release appeared while exporting")
        staged.rename(destination)
    return manifest


def scenario_records(root, corpus):
    """Include question/conversation derivatives with their inherited splits."""
    cases = {case["id"]: case for case in corpus["cases"]}
    lineages = {case["lineage"]: case["split"] for case in corpus["cases"]}
    for name in ("question-input-manifest.json", "conversation-input-manifest.json"):
        path = root / name
        if not path.exists():
            continue
        manifest = json.loads(path.read_text())
        for case in manifest.get("additional_scenarios", []):
            if (
                case["split"] not in {"train", "validation"}
                or lineages.get(case["lineage"]) != case["split"]
                or digest({k: v for k, v in case.items() if k != "sha256"})
                != case["sha256"]
                or (case["id"] in cases and cases[case["id"]] != case)
            ):
                raise ValueError("Modified, unbound or held-out derivative scenario")
            cases[case["id"]] = case
    return cases


def question_records(root, cases):
    """Preserve teacher-generated questions and exact final responses, not reasoning."""
    from .dual_questions import QuestionBatch

    for path in sorted(root.glob("business-question-teacher*.json")):
        artifact = json.loads(path.read_text())
        profile = artifact["profile"]
        if (
            artifact["status"] != "completed"
            or artifact["codex_cli"]["exit_code"] != 0
            or profile["provider"] != "codex"
            or artifact["codex_cli"]["reasoning_effort"] != profile["reasoning_effort"]
        ):
            raise ValueError("Question teacher did not complete successfully")
        response, _ = parse_stream(
            artifact["raw_response"], profile["max_output_tokens"]
        )
        parsed = QuestionBatch.model_validate_json(response).model_dump(mode="json")
        if parsed != artifact["parsed"]:
            raise ValueError(
                "Question proposal differs from the actual teacher response"
            )
        requested = [
            item["case_id"] for item in artifact["request"]["input"]["scenarios"]
        ]
        returned = [item["case_id"] for item in parsed["questions"]]
        if sorted(requested) != sorted(returned) or len(set(returned)) != len(returned):
            raise ValueError("Question response did not cover its requested scenarios")
        teacher = {
            key: profile[key] for key in ("provider", "model", "reasoning_effort")
        }
        fingerprint = HistoryStore.digest(path)
        yield (
            "question-teacher-responses.jsonl",
            {
                "id": path.stem,
                "teacher": teacher,
                "messages": [
                    {"role": "system", "content": artifact["request"]["instructions"]},
                    {
                        "role": "user",
                        "content": json.dumps(
                            artifact["request"]["input"], ensure_ascii=False
                        ),
                    },
                ],
                "output_schema": artifact["request"]["output_schema"],
                "response_text": response,
                "target": parsed,
                "artifact_sha256": fingerprint,
                "usage": artifact.get("usage"),
                "started_at": artifact.get("started_at"),
                "human_review": "unreviewed",
            },
        )
        for proposal in parsed["questions"]:
            case = cases.get(proposal["case_id"])
            if not case or case["split"] not in {"train", "validation"}:
                raise ValueError(
                    "Question proposal references an unbound or held-out case"
                )
            yield (
                "question-proposals.jsonl",
                {
                    **proposal,
                    "split": case["split"],
                    "lineage": case["lineage"],
                    "case_sha256": case["sha256"],
                    "teacher_response_id": path.stem,
                    "teacher_artifact_sha256": fingerprint,
                    "human_review": "unreviewed",
                },
            )


def _write_package(settings, root, destination, *, require_complete=False):
    """Export all final teacher responses; only freshly verified rows enter SFT.

    Source datasets and final model messages are included, without credentials,
    machine-specific paths or private reasoning streams. Original raw transport
    receipts stay in the immutable local run archive and are bound by hashes.
    """
    if destination.exists():
        raise ValueError("Dataset releases are immutable; use a new destination")
    corpus = json.loads((root / "corpus.json").read_text())
    lineages = {}
    for case in corpus["cases"]:
        previous = lineages.setdefault(case["lineage"], case["split"])
        if previous != case["split"]:
            raise ValueError("Source lineage leaked across splits")
    cases = scenario_records(root, corpus)
    selection = load_selection(root, corpus)
    inputs = sorted((root / "teacher-inputs").glob("*.json"))
    for path in inputs:
        job = json.loads(path.read_text())
        if (
            job["split"] not in {"train", "validation"}
            or lineages.get(job["lineage"]) != job["split"]
        ):
            raise ValueError("Held-out or unbound source in teacher training inputs")
        if digest({k: v for k, v in job.items() if k != "sha256"}) != job["sha256"]:
            raise ValueError("Teacher input content changed")
    deferred = [p for p in inputs if not selected(selection, json.loads(p.read_text()))]
    inputs = [p for p in inputs if p not in deferred]
    missing = [
        p.name for p in inputs if not (root / "teacher-targets" / p.name).exists()
    ]
    if require_complete and missing:
        raise ValueError(f"{len(missing)} teacher calls have not finished")
    destination.mkdir(parents=True, mode=0o700)
    streams = {}
    counts = Counter()

    def emit(name, record):
        if name not in streams:
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            streams[name] = path.open("x", encoding="utf-8")
        streams[name].write(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        )

    try:
        for path in deferred:
            emit("deferred-inputs.jsonl", json.loads(path.read_text()))
        for case in cases.values():
            emit("cases.jsonl", case)
        for name, record in question_records(root, cases):
            emit(name, record)
            counts[name] += 1
        reference_paths = sorted((root / "references/cases").glob("*.json"))
        reference_paths += sorted(
            (root / "references/question-derivatives").glob("*.json")
        )
        for path in reference_paths:
            record = json.loads(path.read_text())
            # Execution commands/absolute workspace paths stay in local audit records.
            emit(
                "references.jsonl",
                {
                    key: record[key]
                    for key in (
                        "id",
                        "case_sha256",
                        "split",
                        "lineage",
                        "status",
                        "error",
                        "payload",
                        "numerical_validation",
                        "answer",
                        "native_binary_sha256",
                        "parent_execution_sha256",
                        "reuse_scope",
                    )
                    if key in record
                },
            )
        for path in inputs:
            job = json.loads(path.read_text())
            if (
                job["split"] not in {"train", "validation"}
                or lineages.get(job["lineage"]) != job["split"]
            ):
                raise ValueError(
                    "Held-out or unbound source in teacher training inputs"
                )
            if digest({k: v for k, v in job.items() if k != "sha256"}) != job["sha256"]:
                raise ValueError("Teacher input content changed")
            target_path = root / "teacher-targets" / path.name
            if not target_path.exists():
                continue
            artifact = json.loads(target_path.read_text())
            record = {
                key: job[key]
                for key in (
                    "id",
                    "case_id",
                    "case_sha256",
                    "split",
                    "lineage",
                    "adapter",
                    "schema",
                    "messages",
                    "output_schema",
                    "user_payload",
                    "conversation",
                    "reference_contract",
                )
            }
            record.update(
                schema_version="graphmine-reusable-teacher-v1",
                variant=job.get("variant", "initial"),
                teacher={
                    key: artifact["profile"][key]
                    for key in ("provider", "model", "reasoning_effort")
                },
                input_sha256=job["sha256"],
                teacher_artifact_sha256=HistoryStore.digest(target_path),
                started_at=artifact.get("started_at"),
                usage=artifact.get("usage"),
                human_review="unreviewed",
                original_status=artifact["status"],
                training_split=effective_split(selection, job),
            )
            try:
                record["response_text"], _ = parse_stream(
                    artifact.get("raw_response", ""),
                    artifact["profile"]["max_output_tokens"],
                )
            except (ValueError, TypeError, KeyError):
                record["response_text"] = None
            try:
                require_eligible_for_training(selection, job)
                target = verified_target(settings, root, job, artifact)
                record.update(
                    status="accepted",
                    target=target.model_dump(mode="json"),
                    validation_error=None,
                )
                messages = job["messages"] + [
                    {"role": "assistant", "content": target.model_dump_json()}
                ]
                name = f"sft/{job['adapter']}/{effective_split(selection, job)}.jsonl"
                emit(name, {"messages": messages})
                emit(
                    "sft-index.jsonl",
                    {
                        "id": job["id"],
                        "file": name,
                        "row": counts[name],
                        "row_sha256": digest({"messages": messages}),
                        "source": job["lineage"],
                    },
                )
                counts[name] += 1
            except VALIDATION_ERRORS as error:
                record.update(
                    status="quarantined",
                    target=artifact.get("target"),
                    validation_error=f"{type(error).__name__}: {error}",
                )
            counts[record["status"]] += 1
            emit("teacher-responses.jsonl", record)
            if record["status"] == "quarantined":
                emit("review-later.jsonl", record)
    finally:
        for stream in streams.values():
            stream.close()
    manifest = {
        "schema_version": "graphmine-reusable-dataset-v1",
        "created_at": utc_now().isoformat(),
        "complete": not missing,
        "original_collection_complete": not missing and not deferred,
        "collection_selection": selection,
        "deferred_teacher_calls": [p.name for p in deferred],
        "missing_teacher_calls": missing,
        "counts": dict(counts),
        "scenarios": len(cases),
        "source_splits": effective_sources(selection, lineages),
        "original_source_splits": lineages,
        "source_registry": corpus["source_registry"],
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
        "files": {
            name: {
                "sha256": HistoryStore.digest(destination / name),
                "bytes": (destination / name).stat().st_size,
            }
            for name in streams
        },
        "scope": "Portable UTF-8 JSON Lines. Only accepted train rows may update weights; validation is for model selection. Test cases are held out and have no teacher training targets. Automatic checks do not imply human review. References for community detection establish partition/score consistency, not optimality.",
    }
    HistoryStore.write(destination / "manifest.json", manifest)
    (destination / "README.md").write_text(
        "# Reusable GraphMine teacher dataset\n\n"
        "Every `.jsonl` line is one UTF-8 JSON object. `manifest.json` records SHA-256 fingerprints, counts, source attribution and split assignments.\n\n"
        "- `teacher-responses.jsonl`: original teacher prompts, final response text, parsed targets, validation outcomes and teacher model/effort. Rejected responses are retained and excluded from SFT.\n"
        "- `question-teacher-responses.jsonl`: original question-generation requests, exact final ChatGPT responses and transport artifact fingerprints.\n"
        "- `question-proposals.jsonl`: one reusable clear question and simulated clarification exchange per source scenario, with split and teacher provenance. These are original proposals, not human intent labels.\n"
        "- `sft/{planner,analyst}/{train,validation}.jsonl`: standard chat `messages` records suitable for supervised fine-tuning. Train only on `train`.\n"
        "- `sft-index.jsonl`: row identity, source lineage and content fingerprint.\n"
        "- `review-later.jsonl`: flagged responses preserved for later review and excluded from training.\n"
        "- `deferred-inputs.jsonl`: uncollected requests explicitly deferred to a later run, when collection was limited.\n"
        "- `cases.jsonl`: graph inputs, attachments, questions, proposed contracts and split provenance, including question/conversation derivatives and reserved test cases.\n"
        "- `references.jsonl`: executed graph results and independent numerical/consistency checks.\n\n"
        "Keep all descendants of a source in the same split. `source_splits` and each response's `training_split` describe this training release; original graph/reference split labels and `original_source_splits` preserve collection provenance. A limited run may reserve an entire original training source family for validation without changing any original teacher evidence. `complete` refers to the explicitly selected collection; `original_collection_complete` also accounts for deferred requests. Do not mix validation/test rows into a training refresh. No human preference labels are present. Original CLI transport artifacts remain in the local run's `teacher-targets` directory, identified by SHA-256; private reasoning is excluded from this reusable package.\n",
        encoding="utf-8",
    )
    return manifest


def verify_package(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, record in manifest["files"].items():
        path = (directory / name).resolve()
        if (
            not path.is_relative_to(directory.resolve())
            or HistoryStore.digest(path) != record["sha256"]
        ):
            raise ValueError("Dataset file escaped or changed: " + name)
        with path.open() as stream:
            for line in stream:
                json.loads(line)
    return {
        "verified_files": len(manifest["files"]),
        "counts": manifest["counts"],
        "complete": manifest["complete"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["charts", "package", "verify"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    if args.command == "charts":
        result = {"chart_requests": add_chart_curriculum(args.root)}
    elif args.command == "package":
        if args.output is None:
            parser.error("package requires --output")
        result = package(
            Settings.from_env(),
            args.root,
            args.output,
            require_complete=args.require_complete,
        )
        result = {
            "output": str(args.output),
            "complete": result["complete"],
            "counts": result["counts"],
            "scenarios": result["scenarios"],
            "missing_teacher_calls": len(result["missing_teacher_calls"]),
            "files": len(result["files"]),
        }
    else:
        result = verify_package(args.root)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
