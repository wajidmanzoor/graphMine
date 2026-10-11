"""Explicitly reviewed workflow examples, scoped to workspace and core version."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from .analytics import AnalyticsError
from .database import RecordNotFound


def digest(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


class ExampleReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=2000)
    approved: Literal[True]
    expected_revision: int = Field(ge=1)
    workflow_hash: str = Field(pattern="^[a-f0-9]{64}$")
    result_sha256: str = Field(pattern="^[a-f0-9]{64}$")


class ReviewedExamples:
    def __init__(self, analytics):
        self.analytics = analytics
        with closing(sqlite3.connect(analytics.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reviewed_examples (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, document TEXT NOT NULL)"
            )

    def candidate(self, workflow_id):
        record = self.analytics.get(workflow_id)
        if record.get("evaluation_id"):
            raise AnalyticsError(
                "Evaluation cases cannot become planning examples",
                "evaluation_excluded",
            )
        if record["status"] != "completed":
            raise AnalyticsError(
                "Review requires a completed workflow", "incomplete_result"
            )
        result = self.analytics.result(workflow_id)
        if result.get("complete") is not True:
            raise AnalyticsError(
                "Review requires complete outputs", "incomplete_result"
            )
        return {
            "workflow_id": workflow_id,
            "expected_revision": record["revision"],
            "workflow_hash": record["validation"]["workflow_hash"],
            "result_sha256": digest(result),
            "plan": record["validation"]["plan"],
            "implementation_sha256": record["validation"]["implementation_sha256"],
        }

    async def approve(self, workflow_id, review):
        async with self.analytics.edit_lock:
            candidate = self.candidate(workflow_id)
            if any(
                getattr(review, key) != candidate[key]
                for key in ("expected_revision", "workflow_hash", "result_sha256")
            ):
                raise AnalyticsError(
                    "The reviewed workflow or result changed; reload it before approving",
                    "revision_conflict",
                    409,
                )
            record = self.analytics.get(workflow_id)
            example = {
                "id": str(uuid4()),
                "session_id": record["session_id"],
                "status": "approved",
                "question": review.question.strip(),
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approval": "explicit_authenticated_workspace_review",
                "plan": candidate.pop("plan"),
                "provenance": candidate,
                "inputs": {
                    key: {
                        "kind": value["kind"],
                        "file_sha256": self.analytics.database.get_file(
                            value["file_id"]
                        ).sha256,
                    }
                    for key, value in record["input_files"].items()
                },
            }
            if not example["question"]:
                raise AnalyticsError("A reviewed example needs a question")
            if len(json.dumps(example).encode()) > 32000:
                raise AnalyticsError(
                    "Example exceeds the bounded planning context", "resource_limit"
                )
            example["content_sha256"] = digest(example)
            with closing(sqlite3.connect(self.analytics.path)) as db, db:
                db.execute(
                    "INSERT INTO reviewed_examples VALUES (?,?,?)",
                    (
                        example["id"],
                        example["session_id"],
                        json.dumps(example, ensure_ascii=False),
                    ),
                )
            return example

    def list(self, session_id):
        self.analytics.database.get_session(session_id)
        with closing(sqlite3.connect(self.analytics.path)) as db:
            rows = db.execute(
                "SELECT document FROM reviewed_examples WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def revoke(self, session_id, example_id):
        self.analytics.database.get_session(session_id)
        with closing(sqlite3.connect(self.analytics.path)) as db, db:
            row = db.execute(
                "SELECT document FROM reviewed_examples WHERE id=? AND session_id=?",
                (example_id, session_id),
            ).fetchone()
            if row is None:
                raise RecordNotFound("No such reviewed example in this workspace")
            example = json.loads(row[0])
            example["status"] = "revoked"
            example["revoked_at"] = datetime.now(timezone.utc).isoformat()
            db.execute(
                "UPDATE reviewed_examples SET document=? WHERE id=?",
                (json.dumps(example, ensure_ascii=False), example_id),
            )
        return {"id": example_id, "status": "revoked"}

    def search(
        self,
        session_id,
        question,
        operations,
        implementation,
        input_kinds,
        *,
        evaluation_id=None,
    ):
        # Held-out requests use no examples, including near duplicates. Their
        # workflows also carry a permanent non-reviewable evaluation marker.
        if evaluation_id:
            return []

        def tokens(value):
            return Counter(re.findall(r"\w+", value.casefold()))

        query, matches = tokens(question), []
        for row in self.list(session_id):
            if (
                row["status"] != "approved"
                or row["provenance"]["implementation_sha256"] != implementation
            ):
                continue
            if not {step["operation"] for step in row["plan"]["steps"]} <= set(
                operations
            ):
                continue
            if Counter(v["kind"] for v in row["inputs"].values()) != Counter(
                input_kinds
            ):
                continue
            words = tokens(row["question"])
            denominator = math.sqrt(
                sum(v * v for v in query.values()) * sum(v * v for v in words.values())
            )
            score = (
                sum(value * words[key] for key, value in query.items()) / denominator
                if denominator
                else 0
            )
            if score > 0:
                matches.append((score, row))
        matches.sort(key=lambda item: (-item[0], item[1]["id"]))
        selected, size = [], 0
        for score, row in matches[:3]:
            hint = {
                key: row[key]
                for key in (
                    "id",
                    "question",
                    "plan",
                    "inputs",
                    "provenance",
                    "content_sha256",
                )
            }
            hint["retrieval"] = {"method": "unicode-term-cosine-v1", "score": score}
            size += len(json.dumps(hint).encode())
            if size <= 16000:
                selected.append(hint)
        return selected


def register_example_routes(router):
    @router.get("/workflows/{workflow_id}/example-review")
    async def candidate(workflow_id: str, request: Request):
        return request.app.state.runtime.analytics.examples.candidate(workflow_id)

    @router.post("/workflows/{workflow_id}/example-review", status_code=201)
    async def approve(workflow_id: str, body: ExampleReview, request: Request):
        return await request.app.state.runtime.analytics.examples.approve(
            workflow_id, body
        )

    @router.get("/sessions/{session_id}/analytics/examples")
    async def examples(session_id: str, request: Request):
        return request.app.state.runtime.analytics.examples.list(session_id)

    @router.delete("/sessions/{session_id}/analytics/examples/{example_id}")
    async def revoke(session_id: str, example_id: str, request: Request):
        return request.app.state.runtime.analytics.examples.revoke(
            session_id, example_id
        )
