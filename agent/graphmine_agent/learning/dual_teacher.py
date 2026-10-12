"""Capture production inputs and generate max-effort, auditable teacher targets.

The teacher sees only the live messages and schema. Reference annotations are
kept outside its input and used after generation. No agent tools, API keys,
private data, evaluation fixtures, or final-test rows are sent for training.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from ..agent_service import AgentService
from ..analysis import analyst_payload, validate_narrative
from ..catalog import Catalog
from ..config import Settings
from ..database import Database
from ..execution import GraphMineRunner
from ..graph_store import GraphStore
from ..history import HistoryStore
from ..jobs import EventBus, JobManager
from ..llm import runtime_messages, runtime_schema
from ..models import (
    GroundedNarrative,
    LLMMode,
    PlanConfiguration,
    PlanDraft,
    PlanRequest,
    RouteDecision,
    TurnDecision,
    utc_now,
)
from ..planning import PlanValidator
from ..visualization import answer_visualizations
from .catalog_audit import materialize_case
from .catalog_replay import _intent_issues
from .catalog_suite import digest
from .codex import CodexRunner, execution_policy, parse_stream
from .inference import ModelProfile, RequestBudget

VERSION = "dual-adapter-teacher-v1"
SCHEMAS = {
    schema.__name__: schema
    for schema in (RouteDecision, PlanDraft, GroundedNarrative, TurnDecision)
}


class CaptureModel:
    """Reference forcing captures inputs, never supplies final training labels."""

    def __init__(self, catalog, case, destination):
        self.catalog, self.case, self.destination = catalog, case, destination
        self.records = []

    async def close(self):
        pass

    async def generate(self, *, mode, schema, user_payload, conversation=None, **_):
        task = self.case["task"]
        if schema is RouteDecision:
            result = RouteDecision(
                problem_id=task["problem_id"],
                operation_id=task["operation_id"],
                supported=task["operation_id"] is not None,
                confidence=1,
                explanation="Reference contract used to capture the production input; not a training target.",
                intent=task["intent"],
            )
            if "ambiguous" in self.case["tags"]:
                result.ambiguity = [
                    self.case.get("clarification_question")
                    or "Would you like to find tightly connected groups, or records connecting different parts of this network?"
                ]
        elif schema is PlanDraft:
            result = PlanDraft(
                status=task["expected_status"],
                message="Prepare the requested analysis."
                if task["expected_status"] == "ready"
                else "Which starting and ending records should I use?",
                plan=PlanConfiguration(
                    parameters=task["parameters"],
                    optional_outputs=task["optional_outputs"],
                    auxiliary_inputs=user_payload["inferred_auxiliary_inputs"],
                    rationale="Reference contract for input capture.",
                )
                if task["expected_status"] == "ready"
                else None,
            )
        else:
            raise ValueError(f"Unexpected capture stage {schema.__name__}")
        number = len(self.records)
        record = make_job(self.case, mode, schema, user_payload, conversation)
        record["id"] = f"{self.case['id']}-{schema.__name__}-{number}"
        record["sha256"] = digest(record)
        HistoryStore.write(self.destination / (record["id"] + ".json"), record)
        self.records.append(record)
        return result


def make_job(case, mode, schema, payload, conversation=None):
    return {
        "version": VERSION,
        "id": f"{case['id']}-{schema.__name__}",
        "case_id": case["id"],
        "case_sha256": case["sha256"],
        "lineage": case["lineage"],
        "split": case["split"],
        "adapter": "analyst" if mode == LLMMode.analyst else "planner",
        "mode": mode.value,
        "schema": schema.__name__,
        "user_payload": payload,
        "conversation": conversation or [],
        "messages": runtime_messages(
            mode=mode, schema=schema, user_payload=payload, conversation=conversation
        ),
        "output_schema": runtime_schema(schema, payload),
        "reference_contract": case["task"],
        "human_review": "unreviewed",
    }


async def capture(settings, root, *, resume=False, evaluation_only=False):
    destination = root / ("final-test-inputs" if evaluation_only else "teacher-inputs")
    if destination.exists() and not resume:
        raise ValueError("Teacher input capture is immutable; choose a new output root")
    isolated = replace(
        settings,
        data_root=root
        / ("evaluation-capture-store" if evaluation_only else "capture-store"),
        history_directory=None,
        llm_enabled=False,
    )
    catalog = Catalog(isolated)
    database = Database(isolated.database_path)
    store = GraphStore(isolated, database)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(isolated, catalog, store, validator)
    jobs = JobManager(database, runner, EventBus(database), summary_items=20)
    service = AgentService(isolated, catalog, database, store, validator, jobs)
    corpus = json.loads((root / "corpus.json").read_text())
    manifest_path = root / (
        "final-test-capture.json" if evaluation_only else "teacher-input-manifest.json"
    )
    summaries = (
        json.loads(manifest_path.read_text())["rows"]
        if resume and manifest_path.exists()
        else []
    )
    captured_cases = {row["case_id"] for row in summaries}
    for case in corpus["cases"]:
        if (case["split"] == "test") != evaluation_only:
            continue
        if case["id"] in captured_cases:
            continue
        reference_path = root / "references" / "cases" / (case["id"] + ".json")
        reference = json.loads(reference_path.read_text())
        if reference["status"] != "verified":
            continue
        if reference["case_sha256"] != case["sha256"]:
            raise ValueError("Reference case binding changed")
        session, graph, _ = materialize_case(store, database, case)
        model = CaptureModel(catalog, case, destination)
        await service.model.close()
        service.model = model
        outcome = await service.plan(
            session.id, PlanRequest(message=case["task"]["question"], graph_id=graph.id)
        )
        if outcome.status != case["task"]["expected_status"]:
            raise ValueError(
                f"Reference forcing failed for {case['id']}: {outcome.message}"
            )
        if reference.get("answer"):
            answer = reference["answer"]
            defaults = answer_visualizations(answer)
            payload = analyst_payload(
                answer, defaults, catalog, case["domain_id"], case["task"]["question"]
            )
            job = make_job(case, LLMMode.analyst, GroundedNarrative, payload)
            job["reference_path"] = str(reference_path.relative_to(root))
            job["reference_sha256"] = HistoryStore.digest(reference_path)
            job["sha256"] = digest(job)
            HistoryStore.write(destination / (job["id"] + ".json"), job)
            model.records.append(job)
        summaries.extend(
            {
                k: row[k]
                for k in (
                    "id",
                    "case_id",
                    "split",
                    "lineage",
                    "adapter",
                    "schema",
                    "sha256",
                )
            }
            for row in model.records
        )
    await service.close()
    HistoryStore.write(
        manifest_path,
        {
            "version": VERSION,
            "corpus_sha256": digest(corpus),
            "rows": summaries,
            "counts": dict(Counter(row["schema"] for row in summaries)),
        },
    )
    return {
        "jobs": len(summaries),
        "stages": dict(Counter(row["schema"] for row in summaries)),
    }


def check_target(settings, root, job, target):
    """Strict reference agreement, not a human semantic/preference judgment."""
    catalog = Catalog(settings)
    expected = job["reference_contract"]
    if isinstance(target, RouteDecision):
        if (
            expected["expected_status"] == "needs_information"
            and expected["problem_id"] is None
        ):
            if not (target.ambiguity or target.missing_information):
                raise ValueError(
                    "An ambiguous objective must ask a concrete clarification before execution"
                )
            if target.problem_id is not None:
                catalog.problem(target.problem_id)
            if (
                target.operation_id is not None
                and catalog.operation(target.operation_id).problem_id
                != target.problem_id
            ):
                raise ValueError("Clarification references an inconsistent operation")
            return
        issues = []
        equivalent_triangles = (
            expected["expected_status"] == "ready"
            and expected["operation_id"] == "k-cliques"
            and expected["parameters"].get("k") == 3
            and set(expected["optional_outputs"]) <= {"cliques"}
            and target.operation_id == "triangle-counting"
            and target.problem_id == catalog.operation("triangle-counting").problem_id
        )
        # A 3-clique is exactly a triangle, including triples inside larger
        # cliques. Both native contracts count and list these unordered triples.
        # This equivalence does not extend to k != 3 or maximal cliques.
        if not equivalent_triangles and (
            target.problem_id != expected["problem_id"]
            or (
                target.operation_id != expected["operation_id"]
                and not (
                    expected["expected_status"] == "unsupported"
                    and target.operation_id is None
                )
            )
        ):
            issues.append(
                "Formal operation differs from the reference contract (possible equivalent operation requires separate review)"
            )
        actual_intent = target.intent.model_dump(mode="json")
        if expected["operation_id"] != "temporal-motif-mining":
            # These annotations affect only the temporal profile. A static
            # triangle description must not count as a changed computation.
            for name in ("pattern_vertex_count", "pattern_edges"):
                actual_intent[name] = expected["intent"][name]
        issues.extend(_intent_issues(expected["intent"], actual_intent))
        if expected["expected_status"] == "ready" and (
            not target.supported
            or target.ambiguity
            or target.missing_information
            or target.inspections
            or target.additional_analyses
        ):
            issues.append(
                "The fully specified single-step task must be executable without extra questions or analyses"
            )
        # Missing endpoint detection can also happen in the detailed planner.
        if (
            expected["expected_status"] == "needs_information"
            and not (target.ambiguity or target.missing_information)
            and expected["operation_id"] != "max-flow-min-cut"
        ):
            issues.append("Required clarification absent")
        if issues:
            raise ValueError("; ".join(issues))
    elif isinstance(target, PlanDraft):
        if target.status != expected["expected_status"]:
            raise ValueError("Planning status differs from the reference")
        if target.plan:
            actual = target.plan
            contract = catalog.operation(expected["operation_id"]).instruction
            required_outputs = set(expected["optional_outputs"])
            question = expected["question"].casefold()
            # The reference execution deliberately collects extra diagnostics
            # for B. Do not require A to request a diagnostic the user omitted.
            if "normaliz" not in question:
                required_outputs.discard("normalized_score_by_vertex")
            if "total" not in question:
                required_outputs.discard("total_count")
            if "link" not in question and "edge" not in question:
                required_outputs.discard("requested_core_edges")
            if not required_outputs <= set(actual.optional_outputs):
                raise ValueError("Requested outputs omitted")
            for key, value in expected["parameters"].items():
                if (
                    key in {"random_seed", "sample_count", "epsilon"}
                    and str(value) not in expected["question"]
                ):
                    # Reference-run reproducibility/quality controls are not
                    # hidden semantic requirements for the business request.
                    continue
                observed = actual.parameters.get(key)
                if observed is None:
                    observed = contract["parameters"][key].get("default")
                if observed != value:
                    raise ValueError(f"Requested parameter changed: {key}")
            for key, value in actual.parameters.items():
                if (
                    value is not None
                    and key not in expected["parameters"]
                    and value != contract["parameters"][key].get("default")
                ) and not contract["parameters"][key].get("performance_only", False):
                    if key == "result_limit":
                        vertices = job["user_payload"]["verified_projection"][
                            "selected_vertices"
                        ]
                        size = expected["parameters"].get("k", 3)
                        bound = (
                            math.comb(vertices, size)
                            if expected["operation_id"]
                            in {"k-cliques", "triangle-counting"}
                            else 2**vertices
                            if expected["operation_id"]
                            in {"maximal-cliques", "maximum-clique", "quasi-cliques"}
                            else None
                        )
                        if bound is not None and value >= bound:
                            continue
                    raise ValueError(f"Unrequested semantic parameter: {key}")
            wanted = {
                k: v
                for k, v in {
                    **job["user_payload"]["inferred_auxiliary_inputs"],
                    **job["user_payload"].get("supplied_auxiliary_inputs", {}),
                }.items()
                if v
            }
            supplied = {k: v for k, v in actual.auxiliary_inputs.items() if v}
            # Production binds an omitted required file when exactly one
            # uploaded file has the required role. Explicitly naming it is
            # equivalent to leaving that unique binding to the server.
            for name, spec in contract["auxiliary_inputs"].items():
                identifiers = [
                    row["id"]
                    for row in job["user_payload"]["available_files"]
                    if row["role"] == spec["role"]
                ]
                if len(identifiers) == 1 and spec.get("required"):
                    wanted.setdefault(name, identifiers)
                    supplied.setdefault(name, identifiers)
            if supplied != wanted:
                raise ValueError("Attached inputs changed")
    elif isinstance(target, GroundedNarrative):
        if (
            job.get("reference_sha256")
            and HistoryStore.digest(root / job["reference_path"])
            != job["reference_sha256"]
        ):
            raise ValueError("Reference execution artifact changed after capture")
        reference = json.loads((root / job["reference_path"]).read_text())
        answer = reference["answer"]
        validate_narrative(
            target, answer, answer_visualizations(answer), set(catalog.instructions)
        )
        provided_facts = {fact["id"] for fact in job["user_payload"]["answer"]["facts"]}
        references = set(target.fact_ids)
        for item in (
            ([target.summary] if target.summary else [])
            + target.findings
            + target.charts
        ):
            references.update(item.fact_ids)
        if not references <= provided_facts:
            raise ValueError("Teacher cited facts absent from its input")
        if not target.summary or not target.findings:
            raise ValueError(
                "An analysis training target must include a grounded explanation"
            )
        if len(target.charts) < job.get("required_custom_charts", 0):
            raise ValueError("The requested custom chart was omitted")
        if not set(target.followup_ids) <= {
            item["id"] for item in job["user_payload"]["followup_options"]
        }:
            raise ValueError("Unknown follow-up identifier")
    elif isinstance(target, TurnDecision):
        if target.action != job["expected_action"]:
            raise ValueError("Wrong follow-up action")


def teacher_transport_schema(schema):
    """Avoid lossy large-integer bounds in the teacher's JSON transport.

    The original runtime schema is still applied to every returned object.
    A controlled max-effort probe succeeded after removing only these bounds;
    the original endpoint-ID schemas repeatedly failed before completion.
    """
    result = copy.deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "integer":
                for name in ("minimum", "maximum"):
                    if name in value and abs(value[name]) > 2**53:
                        value.pop(name)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result


async def generate(
    settings,
    root,
    *,
    adapter,
    split,
    limit,
    offset=0,
    concurrency=2,
    variant=None,
    retry_transport=False,
):
    if not 1 <= concurrency <= 4:
        raise ValueError("Teacher concurrency must be between one and four")
    if split not in {"train", "validation"}:
        raise ValueError("Final-test examples cannot enter teacher training generation")
    profile = ModelProfile(
        "codex", "gpt-6.1-sol", max_output_tokens=32768, reasoning_effort="max"
    )
    budget = RequestBudget(max_calls=limit)
    runner = CodexRunner()
    await runner.preflight()
    paths = sorted((root / "teacher-inputs").glob("*.json"))
    selected = [json.loads(path.read_text()) for path in paths]
    selected = [
        job
        for job in selected
        if job["adapter"] == adapter
        and job["split"] == split
        and (variant is None or job.get("variant") == variant)
    ][offset : offset + limit]
    semaphore = asyncio.Semaphore(concurrency)
    allowance_exhausted = asyncio.Event()

    async def one(job):
        artifact = root / "teacher-targets" / (job["id"] + ".json")
        previous_attempt = None
        if artifact.exists():
            existing = json.loads(artifact.read_text())
            if existing["input_sha256"] != job["sha256"]:
                raise ValueError("A teacher input changed after generation")
            if not (
                retry_transport
                and not existing.get("target")
                and not existing.get("previous_transport_attempt")
            ):
                return existing["status"]
            archive = root / "teacher-transport-failures" / artifact.name
            if archive.exists():
                raise ValueError("This transport retry was already attempted")
            archive.parent.mkdir(parents=True, exist_ok=True)
            previous_attempt = HistoryStore.digest(artifact)
            artifact.rename(archive)
        async with semaphore:
            if allowance_exhausted.is_set():
                return "not_started"
            if (
                runtime_messages(
                    mode=LLMMode(job["mode"]),
                    schema=SCHEMAS[job["schema"]],
                    user_payload=job["user_payload"],
                    conversation=job["conversation"],
                )
                != job["messages"]
            ):
                raise ValueError("Runtime prompt changed; recapture before training")
            messages = job["messages"]
            body = {
                "model": profile.model,
                "instructions": messages[0]["content"],
                "input": job["user_payload"]
                if len(messages) == 2
                else {
                    "conversation_messages": messages[1:-1],
                    "current_request": job["user_payload"],
                },
                "output_schema": teacher_transport_schema(job["output_schema"]),
                "reasoning_effort": profile.effort,
                "execution_policy": execution_policy(profile.effort),
            }
            record = {
                "version": VERSION,
                "input_sha256": job["sha256"],
                "profile": profile.public(),
                "started_at": utc_now().isoformat(),
                "request": body,
                "reservation": budget.reserve(profile, body),
                "human_review": "unreviewed",
                "validation_scope": "Schema, frozen reference contract, evidence IDs, numeric consistency, chart grammar and real compiler/render. Not proof of business meaning or visual quality.",
                "previous_transport_attempt": previous_attempt,
                "schema_transport": "Integer bounds outside the exact JSON/JavaScript integer range are omitted only during teacher generation; the original runtime schema validates the response.",
            }
            started = time.monotonic()
            try:
                record.update(await runner.generate(body))
                transport_text = (
                    record.get("raw_response", "")
                    + record.get("codex_cli", {}).get("stderr", "")
                ).casefold()
                if any(
                    marker in transport_text
                    for marker in (
                        "usage_limit_reached",
                        "rate_limit_exceeded",
                        "insufficient_quota",
                        "you've hit your usage limit",
                        "you have hit your usage limit",
                    )
                ):
                    allowance_exhausted.set()
                    raise RuntimeError(
                        "ChatGPT teacher allowance is exhausted; generation stopped and existing data is preserved"
                    )
                if record["codex_cli"]["exit_code"] != 0:
                    raise ValueError("ChatGPT CLI exited unsuccessfully")
                content, usage = parse_stream(
                    record["raw_response"], profile.max_output_tokens
                )
                parsed = json.loads(content)
                Draft202012Validator(job["output_schema"]).validate(parsed)
                target = SCHEMAS[job["schema"]].model_validate(parsed)
                record.update(usage=usage, target=target.model_dump(mode="json"))
                await asyncio.to_thread(check_target, settings, root, job, target)
                record["status"] = "accepted"
            except (
                SchemaValidationError,
                ValueError,
                RuntimeError,
                OSError,
                KeyError,
                TypeError,
                AssertionError,
            ) as error:
                record.update(
                    status="quarantined", error=f"{type(error).__name__}: {error}"
                )
            finally:
                record["elapsed_seconds"] = time.monotonic() - started
                HistoryStore.write(artifact, record)
            print(
                json.dumps(
                    {
                        "id": job["id"],
                        "status": record["status"],
                        "elapsed_seconds": round(record["elapsed_seconds"], 1),
                        "error": record.get("error"),
                    }
                ),
                flush=True,
            )
            return record["status"]

    outcomes = await asyncio.gather(*(one(job) for job in selected))
    result = {
        "adapter": adapter,
        "split": split,
        "offset": offset,
        "selected": len(selected),
        "outcomes": dict(Counter(outcomes)),
        "budget": budget.public(),
    }
    HistoryStore.write(root / f"teacher-run-{adapter}-{split}-{offset}.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["capture", "capture-final-test", "generate"]
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--adapter", choices=["planner", "analyst"], default="planner")
    parser.add_argument("--split", choices=["train", "validation"], default="train")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--resume-capture", action="store_true")
    parser.add_argument(
        "--variant", choices=["conversation", "repair", "plan_first", "recovery"]
    )
    parser.add_argument("--retry-transport", action="store_true")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command in {"capture", "capture-final-test"}:
        result = asyncio.run(
            capture(
                settings,
                args.root,
                resume=args.resume_capture,
                evaluation_only=args.command == "capture-final-test",
            )
        )
    else:
        result = asyncio.run(
            generate(
                settings,
                args.root,
                adapter=args.adapter,
                split=args.split,
                limit=args.limit,
                offset=args.offset,
                variant=args.variant,
                retry_transport=args.retry_transport,
                concurrency=args.concurrency,
            )
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
