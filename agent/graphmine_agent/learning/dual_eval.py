"""Paired stage evaluation against frozen source-separated runtime inputs.

Stage scores are not end-to-end task success or human usefulness ratings.
Native execution and complete agent workflows are evaluated separately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from ..config import Settings
from ..history import HistoryStore
from ..llm import LLMError, OpenAICompatibleModel
from ..models import LLMMode, utc_now
from .catalog_replay import source_bindings
from .dual_teacher import SCHEMAS, check_target


def verify_request_reuse(output, binding=None):
    """Verify explicit carry-forward of byte-identical initial/repair requests."""
    path = output / "request-reuse.json"
    reused = {}
    if not path.exists():
        return None, reused
    receipt = json.loads(path.read_text())
    fingerprints = []
    for side in ("before", "after"):
        source = Path(receipt[side]["path"])
        if HistoryStore.digest(source) != receipt[side]["sha256"]:
            raise ValueError("Request fingerprint artifact changed")
        fingerprints.append(json.loads(source.read_text()))
    before, after = fingerprints
    if any(
        before[key] != after[key] for key in ("manifest_sha256", "model", "endpoint")
    ):
        raise ValueError("Reused requests have different inputs or models")
    if binding and (
        binding["manifest_sha256"] != after["manifest_sha256"]
        or binding["profile"]["planner"] != after["model"]
        or binding["profile"]["analyst"] != after["model"]
        or binding["profile"]["endpoint"] != after["endpoint"]
    ):
        raise ValueError("Reused requests do not match this evaluation configuration")
    if after["llm_sha256"] != source_bindings()["llm.py"]:
        raise ValueError("Reused requests were not checked against this runtime")
    old = {row["id"]: row for row in before["rows"]}
    new = {row["id"]: row for row in after["rows"]}
    equivalent = {
        identifier for identifier, row in old.items() if row == new.get(identifier)
    }
    if {row["id"] for row in receipt["calls"]} != equivalent:
        raise ValueError(
            "Reuse must retain every equivalent request, regardless of score"
        )
    source_profile = Path(receipt["source_profile"]["path"])
    if HistoryStore.digest(source_profile) != receipt["source_profile"]["sha256"]:
        raise ValueError("Original execution profile changed")
    original_binding = json.loads(source_profile.read_text())
    if (
        original_binding["manifest_sha256"] != before["manifest_sha256"]
        or original_binding["profile"]["sources"]["llm.py"] != before["llm_sha256"]
    ):
        raise ValueError("Original execution sources do not match the request capture")
    if any(
        original_binding["profile"]["sources"].get(name) != digest
        for name, digest in source_bindings().items()
        if name != "llm.py"
    ):
        raise ValueError(
            "Other execution sources changed; request equality is insufficient"
        )
    if original_binding["profile"]["rules_sha256"] != HistoryStore.digest(
        Path(__file__).with_name("dual_teacher.py")
    ):
        raise ValueError("Original grading rules changed")
    for row in receipt["calls"]:
        source = Path(row["path"])
        if HistoryStore.digest(source) != row["sha256"]:
            raise ValueError("Original reused response changed")
        actual = json.loads((output / "calls" / (row["id"] + ".json")).read_text())
        origin = actual.pop("origin", None)
        if origin != row or actual != json.loads(source.read_text()):
            raise ValueError("Reused response or its original provenance changed")
        reused[row["id"]] = row
    return HistoryStore.digest(path), reused


def freeze_inputs(root, destination, *, split="validation"):
    if destination.exists():
        raise ValueError("Evaluation input selection is immutable")
    if split not in {"validation", "test"}:
        raise ValueError("Stage evaluation must use source-held-out inputs")
    rows = []
    folder = root / ("teacher-inputs" if split == "validation" else "final-test-inputs")
    for path in sorted(folder.glob("*.json")):
        job = json.loads(path.read_text())
        if job["split"] != split or job.get("variant") in {"repair"}:
            continue
        rows.append(
            {
                "id": job["id"],
                "path": str(path.relative_to(root)),
                "input_sha256": job["sha256"],
                "file_sha256": HistoryStore.digest(path),
                "schema": job["schema"],
                "lineage": job["lineage"],
                "adapter": job["adapter"],
            }
        )
    if not rows:
        raise ValueError("No eligible evaluation inputs")
    report = {
        "version": "dual-stage-evaluation-v1",
        "created_at": utc_now().isoformat(),
        "split": split,
        "rows": rows,
        "selection": "Every available non-repair runtime input in the specified held-out split, fixed before model runs.",
        "scope": "Stage-level teacher-forced context; separate end-to-end evaluation required.",
    }
    HistoryStore.write(destination, report)
    return {"rows": len(rows), "stages": dict(Counter(row["schema"] for row in rows))}


async def evaluate(
    settings, root, manifest, output, *, planner, analyst, base_url, key, concurrency=2
):
    selection = json.loads(manifest.read_text())
    selected = replace(
        settings,
        llm_enabled=True,
        llm_base_url=base_url,
        llm_api_key=key,
        llm_route_base_url=None,
        llm_route_allow_expanded_catalog=False,
        llm_model=planner if planner == analyst else settings.llm_model,
        llm_planner_model=planner if planner != analyst else None,
        llm_analyst_model=analyst if planner != analyst else None,
        llm_route_reasoning_effort="none",
        llm_plan_reasoning_effort="none",
        llm_analyst_reasoning_effort="none",
    )
    model = OpenAICompatibleModel(selected)
    manifest_sha = HistoryStore.digest(manifest)
    profile = {
        "planner": planner,
        "analyst": analyst,
        "endpoint": base_url,
        "reasoning_effort": "none",
        "model_weights_verified_by_harness": False,
        "request_reuse_sha256": None,
        "call_provenance": "Records with origin were captured under their recorded original profile and explicitly verified to have identical initial and repair requests; other records use this profile.",
        "sources": source_bindings(),
        "evaluation_code_sha256": HistoryStore.digest(Path(__file__)),
        "rules_sha256": HistoryStore.digest(
            Path(__file__).with_name("dual_teacher.py")
        ),
    }
    binding = {"manifest_sha256": manifest_sha, "profile": profile}
    profile["request_reuse_sha256"], _ = verify_request_reuse(output, binding)
    profile_path = output / "profile.json"
    if profile_path.exists():
        if json.loads(profile_path.read_text()) != binding:
            raise ValueError("Evaluation output already belongs to another run")
    else:
        HistoryStore.write(profile_path, binding)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(row):
        input_path = root / row["path"]
        if HistoryStore.digest(input_path) != row["file_sha256"]:
            raise ValueError("A frozen evaluation input changed")
        job = json.loads(input_path.read_text())
        path = output / "calls" / (job["id"] + ".json")
        if path.exists():
            record = json.loads(path.read_text())
            if record["input_sha256"] != job["sha256"] or record["model"] != (
                planner if job["adapter"] == "planner" else analyst
            ):
                raise ValueError("Saved evaluation call has a different input")
            return record
        async with semaphore:
            started = time.monotonic()
            record = {
                "id": job["id"],
                "input_sha256": job["sha256"],
                "schema": job["schema"],
                "split": job["split"],
                "lineage": job["lineage"],
                "model": planner if job["adapter"] == "planner" else analyst,
                "started_at": utc_now().isoformat(),
                "adapter": job["adapter"],
            }
            try:
                target = await model.generate(
                    mode=LLMMode(job["mode"]),
                    schema=SCHEMAS[job["schema"]],
                    user_payload=job["user_payload"],
                    conversation=job["conversation"],
                )
                record["target"] = target.model_dump(mode="json")
                Draft202012Validator(job["output_schema"]).validate(record["target"])
                await asyncio.to_thread(check_target, settings, root, job, target)
                record["status"] = "passed"
            except (
                LLMError,
                ValueError,
                RuntimeError,
                OSError,
                KeyError,
                TypeError,
                SchemaValidationError,
            ) as error:
                record.update(status="failed", error=f"{type(error).__name__}: {error}")
            record["elapsed_seconds"] = time.monotonic() - started
            HistoryStore.write(path, record)
            print(
                json.dumps({k: record[k] for k in ("id", "status", "elapsed_seconds")}),
                flush=True,
            )
            return record

    try:
        records = await asyncio.gather(*(one(row) for row in selection["rows"]))
    finally:
        await model.close()
    summary = regrade(settings, root, manifest, output)
    summary["raw_outcomes"] = dict(Counter(row["status"] for row in records))
    HistoryStore.write(output / "summary.json", summary)
    return summary


def regrade(settings, root, manifest, output):
    selection = json.loads(manifest.read_text())
    results = []
    for row in selection["rows"]:
        path = output / "calls" / (row["id"] + ".json")
        record = {"id": row["id"], "schema": row["schema"], "passed": False}
        if not path.exists():
            record["error"] = "Missing trial"
        else:
            saved = json.loads(path.read_text())
            job = json.loads((root / row["path"]).read_text())
            record["call_sha256"] = HistoryStore.digest(path)
            record["elapsed_seconds"] = saved["elapsed_seconds"]
            try:
                if (
                    saved["input_sha256"] != job["sha256"]
                    or HistoryStore.digest(root / row["path"]) != row["file_sha256"]
                ):
                    raise ValueError("Input binding failed")
                if "target" not in saved:
                    raise ValueError(saved.get("error") or "No structured model output")
                Draft202012Validator(job["output_schema"]).validate(saved["target"])
                target = SCHEMAS[row["schema"]].model_validate(saved["target"])
                check_target(settings, root, job, target)
                record["passed"] = True
            except (
                ValueError,
                RuntimeError,
                OSError,
                KeyError,
                TypeError,
                SchemaValidationError,
            ) as error:
                record["error"] = str(error)
        results.append(record)
    return {
        "version": "dual-stage-evaluation-v1",
        "manifest_sha256": HistoryStore.digest(manifest),
        "rules_sha256": HistoryStore.digest(
            Path(__file__).with_name("dual_teacher.py")
        ),
        "finished_at": utc_now().isoformat(),
        "passed": sum(row["passed"] for row in results),
        "total": len(results),
        "by_stage": {
            stage: {
                "passed": sum(
                    row["passed"] for row in results if row["schema"] == stage
                ),
                "total": sum(row["schema"] == stage for row in results),
            }
            for stage in sorted({row["schema"] for row in results})
        },
        "rows": results,
        "scope": "Automatic stage checks on fixed held-out runtime inputs. Numeric references and render checks do not prove arbitrary prose meaning, visual usefulness, or end-to-end success; no human labels.",
    }


def compare(settings, root, manifest, baseline, adapted, destination):
    if destination.exists():
        raise ValueError("Choose a new comparison artifact")
    selection = json.loads(manifest.read_text())
    expected_sha = HistoryStore.digest(manifest)
    profiles = {}
    reports = {}
    for label, directory in (("base", baseline), ("adapters", adapted)):
        profile = json.loads((directory / "profile.json").read_text())
        reuse_sha, reused = verify_request_reuse(directory, profile)
        if profile["profile"].get("request_reuse_sha256") != reuse_sha:
            raise ValueError("The request reuse receipt changed")
        if profile["manifest_sha256"] != expected_sha:
            raise ValueError("Runs do not share the same frozen inputs")
        if (
            profile["profile"].get("sources") != source_bindings()
            or profile["profile"].get("evaluation_code_sha256")
            != HistoryStore.digest(Path(__file__))
            or profile["profile"].get("rules_sha256")
            != HistoryStore.digest(Path(__file__).with_name("dual_teacher.py"))
        ):
            raise ValueError("The runtime, decoder, or evaluation sources changed")
        if any(
            not (directory / "calls" / (row["id"] + ".json")).exists()
            for row in selection["rows"]
        ):
            raise ValueError("A primary paired comparison requires every planned trial")
        for row in selection["rows"]:
            record = json.loads(
                (directory / "calls" / (row["id"] + ".json")).read_text()
            )
            if bool(record.get("origin")) != (row["id"] in reused):
                raise ValueError("A response has unverified execution provenance")
        profiles[label] = profile["profile"]
        reports[label] = regrade(settings, root, manifest, directory)
        if any(
            row.get("error") == "Input binding failed" for row in reports[label]["rows"]
        ):
            raise ValueError(
                "A frozen input binding failed; this is not a valid model comparison"
            )
    if profiles["base"]["endpoint"] != profiles["adapters"]["endpoint"]:
        raise ValueError("Use the same shared model service for both configurations")
    left = {row["id"]: row for row in reports["base"]["rows"]}
    right = {row["id"]: row for row in reports["adapters"]["rows"]}
    pairs = []
    for row in selection["rows"]:
        a, b = left[row["id"]], right[row["id"]]
        pairs.append(
            {
                "id": row["id"],
                "schema": row["schema"],
                "base_passed": a["passed"],
                "adapters_passed": b["passed"],
                "base_error": a.get("error"),
                "adapters_error": b.get("error"),
                "base_call_sha256": a["call_sha256"],
                "adapters_call_sha256": b["call_sha256"],
            }
        )
    stages = {}
    for stage in sorted({row["schema"] for row in pairs}):
        selected = [row for row in pairs if row["schema"] == stage]
        stages[stage] = {
            "total": len(selected),
            "base_passed": sum(row["base_passed"] for row in selected),
            "adapters_passed": sum(row["adapters_passed"] for row in selected),
            "corrected": sum(
                not row["base_passed"] and row["adapters_passed"] for row in selected
            ),
            "regressed": sum(
                row["base_passed"] and not row["adapters_passed"] for row in selected
            ),
            "median_seconds": {
                label: statistics.median(
                    row["elapsed_seconds"]
                    for row in report["rows"]
                    if row["schema"] == stage
                )
                for label, report in reports.items()
            },
        }
    result = {
        "version": "dual-stage-paired-comparison-v1",
        "split": selection["split"],
        "manifest_sha256": expected_sha,
        "profiles": profiles,
        "rules_sha256": reports["base"]["rules_sha256"],
        "evaluation_code_sha256": HistoryStore.digest(Path(__file__)),
        "total": len(pairs),
        "base_passed": reports["base"]["passed"],
        "adapters_passed": reports["adapters"]["passed"],
        "by_stage": stages,
        "pairs": pairs,
        "scope": "Same frozen held-out prompts and service, regraded with identical rules. Includes bounded JSON repair but no semantic correction loop at stage level. Latency includes network, generation and validation and is not an isolated kernel benchmark. Related prompts share source graphs; these rows are not independent statistical samples. Model-weight identity must be established by the serving receipt. Human usefulness and complete workflow success are measured separately.",
    }
    HistoryStore.write(destination, result)
    return {key: value for key, value in result.items() if key != "pairs"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "evaluate", "regrade", "compare"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--planner")
    parser.add_argument("--analyst")
    parser.add_argument("--base-url")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--adapted", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "freeze":
        result = freeze_inputs(args.root, args.manifest, split=args.split)
    elif args.command == "evaluate":
        result = asyncio.run(
            evaluate(
                settings,
                args.root,
                args.manifest,
                args.output,
                planner=args.planner,
                analyst=args.analyst,
                base_url=args.base_url or settings.llm_base_url,
                key=settings.llm_api_key,
            )
        )
    elif args.command == "compare":
        result = compare(
            settings, args.root, args.manifest, args.baseline, args.adapted, args.output
        )
    else:
        result = regrade(settings, args.root, args.manifest, args.output)
        HistoryStore.write(args.output / "regraded.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}))


if __name__ == "__main__":
    main()
