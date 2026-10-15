"""Private workflow recipes; each use validates new inputs and requires review."""

import copy
import json
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, InputReference, WorkflowRequest, _json, _seconds
from .analytics_answers import build_facts
from .database import RecordNotFound
from .datasets import _owner
from .identity import AccountError, current_principal
from .models import new_id, utc_now


class TemplateSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    workflow_id: str
    expected_revision: int = Field(ge=1)


class TemplateUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, InputReference]
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class CompareRuns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_ids: list[str] = Field(min_length=2, max_length=6)


class WorkflowTemplates:
    def __init__(self, runtime):
        self.runtime = runtime
        self.db = runtime.database

    def list(self):
        with self.db._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT document FROM workflow_templates WHERE owner_id IS ? ORDER BY rowid DESC",
                    (_owner(),),
                )
            ]

    def get(self, template_id):
        with self.db._connect() as db:
            row = db.execute(
                "SELECT document FROM workflow_templates WHERE id=? AND owner_id IS ?",
                (template_id, _owner()),
            ).fetchone()
        if row is None:
            raise RecordNotFound("Workflow template not found")
        return json.loads(row[0])

    def save(self, body):
        record = self.runtime.analytics.get(body.workflow_id)
        if record["revision"] != body.expected_revision:
            raise AnalyticsError(
                "The workflow changed. Reload it before saving a template.",
                "revision_conflict",
                409,
            )
        if not body.name.strip():
            raise AnalyticsError("Enter a template name")
        template = {
            "id": new_id("template"),
            "name": body.name.strip(),
            "created_at": utc_now().isoformat(),
            "plan": record["validation"]["plan"],
            "input_kinds": {
                alias: ref["kind"] for alias, ref in record["input_files"].items()
            },
            "source": {
                "workflow_id": record["id"],
                "revision": record["revision"],
                "workflow_hash": record["validation"]["workflow_hash"],
            },
        }
        raw = _json(template)
        if len(raw.encode()) > 128 * 1024:
            raise AnalyticsError("Template exceeds the 128 KiB limit", "resource_limit")
        principal = current_principal.get()
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if principal and len(raw.encode()) > principal.accounts.upload_remaining(
                principal.user_id
            ):
                raise AccountError("Your storage allowance is full.", "storage_limit")
            db.execute(
                "INSERT INTO workflow_templates VALUES (?,?,?)",
                (template["id"], _owner(), raw),
            )
        return template

    async def use(self, template_id, session_id, body):
        self.db.get_session(session_id)
        template = self.get(template_id)
        if {alias: ref.kind for alias, ref in body.inputs.items()} != template[
            "input_kinds"
        ]:
            raise AnalyticsError(
                "Bind every template input to a file of its declared kind"
            )
        plan = copy.deepcopy(template["plan"])
        steps = {step["id"]: step for step in plan["steps"]}
        for step_id, values in body.parameters.items():
            if step_id not in steps:
                raise AnalyticsError("Template parameter refers to an unknown step")
            step = steps[step_id]
            if set(values) & set(step.get("bindings", {})):
                raise AnalyticsError(
                    "A parameter supplied by another workflow step cannot be overridden"
                )
            step.setdefault("parameters", {}).update(values)
        record = await self.runtime.analytics.create(
            session_id,
            WorkflowRequest(mode="interactive", plan=plan, inputs=body.inputs),
        )
        record["source_template"] = {
            "id": template["id"],
            "name": template["name"],
            "source": template["source"],
        }
        self.runtime.analytics._save(record)
        return record

    def delete(self, template_id):
        self.get(template_id)
        with self.db._lock, self.db._connect() as db:
            db.execute(
                "DELETE FROM workflow_templates WHERE id=? AND owner_id IS ?",
                (template_id, _owner()),
            )


def history(runtime):
    with runtime.database._connect() as db:
        sessions = {
            row["id"]: json.loads(row["payload"])
            for row in db.execute(
                "SELECT id,payload FROM sessions WHERE owner_id IS ?", (_owner(),)
            )
        }
    rows = [
        record
        for record in runtime.analytics._all()
        if record["session_id"] in sessions
    ]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return [
        {
            "id": r["id"],
            "session_id": r["session_id"],
            "conversation": sessions[r["session_id"]].get("title"),
            "status": r["status"],
            "created_at": r.get("created_at"),
            "revision": r["revision"],
            "operations": [
                s["operation"]
                for s in r.get("validation", {}).get("plan", {}).get("steps", [])
            ],
        }
        for r in rows[:200]
    ]


def compare(runtime, body):
    if len(set(body.workflow_ids)) != len(body.workflow_ids):
        raise AnalyticsError("Choose different saved runs to compare")
    runs = []
    for workflow_id in body.workflow_ids:
        record = runtime.analytics.get(workflow_id)
        saved = runtime.analytics._saved(workflow_id)
        steps = []
        for step in record["validation"]["plan"]["steps"]:
            result = saved.get("steps", {}).get(step["id"], {}).get("result") or {}
            steps.append(
                {
                    "id": step["id"],
                    "operation": step["operation"],
                    "parameters": step.get("parameters", {}),
                    "bindings": step.get("bindings", {}),
                    "quality": result.get("quality"),
                    "complete": result.get("complete"),
                    "backend": result.get("backend"),
                    "outputs": {
                        key: {
                            "type": port["type"],
                            "complete": port.get("complete"),
                            **(
                                {"value": port["value"]}
                                if port["type"] == "scalar"
                                else {"items": len(port["value"])}
                                if isinstance(port["value"], list)
                                else {}
                            ),
                        }
                        for key, port in result.get("ports", {}).items()
                    },
                }
            )
        runs.append(
            {
                "id": workflow_id,
                "revision": record["revision"],
                "status": record["status"],
                "inputs": record["validation"].get("inputs", {}),
                "steps": steps,
                "runtime_seconds": _seconds(record["started_at"], record["finished_at"])
                if record.get("started_at") and record.get("finished_at")
                else None,
                "facts": build_facts(saved, {}, {})[:8],
            }
        )
    identities = [sorted(_json(v) for v in r["inputs"].values()) for r in runs]
    same = bool(identities[0]) and all(
        value == identities[0] for value in identities[1:]
    )
    return {
        "runs": runs,
        "same_inputs": same,
        "note": "Input fingerprints match. Compare quality and completeness alongside values."
        if same
        else "These runs use different or unknown input fingerprints. Differences may reflect the data as well as the method.",
    }


def register_template_routes(router):
    @router.get("/workflow-templates")
    def list_templates(request: Request):
        return WorkflowTemplates(request.app.state.runtime).list()

    @router.post("/workflow-templates", status_code=201)
    async def save_template(body: TemplateSave, request: Request):
        runtime = request.app.state.runtime
        async with runtime.analytics.edit_lock:
            return await run_in_threadpool(WorkflowTemplates(runtime).save, body)

    @router.post(
        "/sessions/{session_id}/workflow-templates/{template_id}/use", status_code=201
    )
    async def use_template(
        session_id: str, template_id: str, body: TemplateUse, request: Request
    ):
        return await WorkflowTemplates(request.app.state.runtime).use(
            template_id, session_id, body
        )

    @router.delete("/workflow-templates/{template_id}", status_code=204)
    def delete_template(template_id: str, request: Request):
        WorkflowTemplates(request.app.state.runtime).delete(template_id)

    @router.get("/workflow-history")
    def workflow_history(request: Request):
        return history(request.app.state.runtime)

    @router.post("/workflows/compare")
    async def compare_workflows(body: CompareRuns, request: Request):
        runtime = request.app.state.runtime
        async with runtime.analytics.edit_lock:
            return await run_in_threadpool(compare, runtime, body)
