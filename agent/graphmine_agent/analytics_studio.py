"""Portable reviewed analytics examples; validation never runs a model or graph job."""
from __future__ import annotations

import json
import re
from copy import deepcopy

import jsonschema
from referencing import Registry

from .analytics_examples import digest
from .errors import AnalyticsError

SCHEMAS = ("AnalyticsRoute", "AnalyticsPlan", "AnalyticsPlanNormalized", "AnalyticsAnswer")
FORMAT = "graphmine-analytics-studio-v1"
MAX_BYTES = 4 * 1024 * 1024


def schema_for(name, context):
    from .analytics_answers import choice_schema
    from .analytics_planning import generation_plan_schema, plan_schema, route_schema
    if name == "AnalyticsAnswer":
        return choice_schema(context["facts"])
    if name == "AnalyticsRoute":
        return route_schema(context["cards"], facts=context.get("facts", []), targets=context.get("targets"))
    if name in {"AnalyticsPlan", "AnalyticsPlanNormalized"}:
        schema = plan_schema(context["cards"], context["aliases"], context["device"])
        return generation_plan_schema(schema) if name == "AnalyticsPlan" else schema
    raise ValueError(f"Unknown analytics schema: {name}")


def validate_target(name, output, context):
    """Use the production schema builders, including per-request operation/fact enums."""
    jsonschema.Draft202012Validator(schema_for(name, context), registry=Registry()).validate(output)
    if name in {"AnalyticsPlan", "AnalyticsPlanNormalized"}:
        if (output["status"] == "ready") != (output["plan"] is not None):
            raise ValueError("Only a ready plan may contain executable steps")
    if name == "AnalyticsAnswer" or (name == "AnalyticsRoute" and output.get("intent") == "explain"):
        lead = output.get("lead", output.get("message", ""))
        if re.search(r"\d", lead):
            raise ValueError("Answer figures must come from saved facts, not the lead sentence")
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def validate_bundle(bundle):
    """Check portable integrity, not cryptographic authorship or a fresh execution."""
    if len(json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("Studio exchange exceeds the 4 MiB limit")
    if bundle.get("schema_version") != FORMAT:
        raise ValueError("Unsupported analytics Studio exchange version")
    if bundle.get("sha256") != digest({k: v for k, v in bundle.items() if k != "sha256"}):
        raise ValueError("Studio exchange hash does not match its content")
    row = bundle["example"]
    if row["schema"] != "AnalyticsPlanNormalized":
        raise ValueError("Workflow exchange requires AnalyticsPlanNormalized")
    validate_target(row["schema"], row["output"], row["context"])
    evidence, review = row["evidence"], row["source_review"]
    result = evidence["result"]
    if result.get("complete") is not True or evidence["result_sha256"] != digest(result):
        raise ValueError("Execution evidence is incomplete or its hash changed")
    if result.get("workflow_hash") != evidence["workflow_hash"]:
        raise ValueError("Execution evidence belongs to a different workflow")
    for field in ("workflow_hash", "result_sha256", "expected_revision", "implementation_sha256"):
        if evidence[field] != review["provenance"][field]:
            raise ValueError(f"Reviewed evidence changed: {field}")
    if review.get("status") != "approved" or review.get("content_sha256") != digest({k: v for k, v in review.items() if k != "content_sha256"}):
        raise ValueError("Source review is missing, revoked or changed")
    if review["plan"] != row["output"]["plan"] or review["question"] != row["question"]:
        raise ValueError("Example differs from its reviewed plan or question")
    if row["adapter"] != "workflow" or row["authorship"] != review.get("authorship", {"target_author": None, "reviewer": None}):
        raise ValueError("Example attribution or adapter differs from its source review")
    if set(row["context"]["aliases"]) != set(review["inputs"]):
        raise ValueError("Input aliases differ from the reviewed workflow")
    messages = row["messages"]
    if len(messages) != 3 or [m["role"] for m in messages] != ["system", "user", "assistant"]:
        raise ValueError("Expected a complete normalized workflow training row")
    payload = json.loads(messages[1]["content"])
    if json.loads(messages[2]["content"]) != row["output"] or payload != {"question": row["question"], "context": row["context"], "inputs": review["inputs"]}:
        raise ValueError("Training messages do not match the reviewed content")
    return row


async def export_reviewed(analytics, workflow_id, example_id, expected_revision):
    async with analytics.edit_lock:
        record = analytics.get(workflow_id)
        if record["revision"] != expected_revision:
            raise AnalyticsError("The workflow changed; reload before exporting", "revision_conflict", 409)
        if analytics._result_path(workflow_id, expected_revision=expected_revision).stat().st_size > MAX_BYTES:
            raise AnalyticsError("Studio exchange exceeds the 4 MiB limit", "resource_limit", 413)
        candidate = analytics.examples.candidate(workflow_id)
        review = next((r for r in analytics.examples.list(record["session_id"]) if r["id"] == example_id), None)
        if not review or review["status"] != "approved":
            raise AnalyticsError("Choose an approved example from this workspace", "review_required", 409)
        if any(review["provenance"].get(k) != candidate[k] for k in ("workflow_id", "expected_revision", "workflow_hash", "result_sha256", "implementation_sha256")):
            raise AnalyticsError("The reviewed workflow or evidence changed", "revision_conflict", 409)
        caps = await analytics.capabilities()
        latest = next((r for r in analytics.examples.list(record["session_id"]) if r["id"] == example_id), None)
        if latest != review or analytics.examples.candidate(workflow_id) != candidate:
            raise AnalyticsError("The review or evidence changed during export", "revision_conflict", 409)
        if caps["implementation_sha256"] != candidate["implementation_sha256"]:
            raise AnalyticsError("The verified implementation changed; execute and review again", "revision_conflict", 409)
        plan = review["plan"]
        operations = {s["operation"] for s in plan["steps"]}
        context = {"cards": [c for c in caps["operations"] if c["id"] in operations],
                   "aliases": list(review["inputs"]), "device": plan["device"]}
        output = {"status": "ready", "message": "", "plan": plan}
        validate_target("AnalyticsPlanNormalized", output, context)
        row = {"id": review["id"], "schema": "AnalyticsPlanNormalized", "adapter": "workflow",
               "question": review["question"], "context": context, "output": output,
               "context_origin": "derived_from_reviewed_workflow",
               "authorship": review.get("authorship", {"target_author": None, "reviewer": None}),
               "source_review": deepcopy(review),
               "evidence": {**{k: v for k, v in candidate.items() if k != "plan"},
                            "result": analytics.result(workflow_id)}}
        row["messages"] = [
            {"role": "system", "content": "Return a normalized GraphMine workflow matching the supplied operation contracts. Use named step references and parameters/bindings."},
            {"role": "user", "content": json.dumps({"question": row["question"], "context": context, "inputs": review["inputs"]}, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)},
        ]
        bundle = {"schema_version": FORMAT, "example": row}
        bundle["sha256"] = digest(bundle)
        try:
            validate_bundle(bundle)
        except (ValueError, KeyError, jsonschema.ValidationError) as exc:
            raise AnalyticsError(str(exc), "studio_export_invalid", 409) from exc
        return bundle
