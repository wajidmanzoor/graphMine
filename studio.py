#!/usr/bin/env python3
"""GraphMine Dataset Studio: a local app for browsing, tagging and editing
fine-tuning datasets (planner and analyst SFT rows).

Standard library only. When run with an interpreter that can import
``graphmine_agent`` (for example the repository's ``.venv``), edited outputs are
validated against the agent's real Pydantic schemas and re-serialized exactly
as training targets are. Source datasets are never modified: edits live in an
append-only journal under the workspace and are written out as a new export.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
NAMES_FILE = APP_DIR / "dataset-names.json"
# New empty datasets live under <data root>/studio-datasets/<folder>/, marked by this file.
STUDIO_DIR = "studio-datasets"
STUDIO_MARKER = "studio-dataset.json"
DEFAULT_REPO = APP_DIR.parent / "graphMine-repo"
SKIP_DIRS = {"training-model-cache", "bin", "sft", "__pycache__", "cache"}
REVIEW_STATES = ("unreviewed", "approved", "needs_fix", "rejected")
SCHEMAS = ("RouteDecision", "PlanDraft", "TurnDecision", "GroundedNarrative")
PROMPT_LABELS = {
    "message": "User question",
    "user_message": "Request to the analyst",
    "answer.question": "Original user question",
}
INDEX_VERSION = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(value) -> str:
    """Same canonical fingerprint the GraphMine learning pipeline uses."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def get_path(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    obj[parts[-1]] = value


def replace_strings(value, old: str, new: str):
    """Replace exact string values equal to ``old`` anywhere in a JSON value."""
    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and node == old:
            count += 1
            return new
        return node

    return walk(value), count


# --------------------------------------------------------------------------
# Optional strict schemas from the GraphMine agent
# --------------------------------------------------------------------------


class Schemas:
    def __init__(self, agent_src: Path | None):
        self.models = {}
        self.error = None
        if agent_src and agent_src.is_dir() and str(agent_src) not in sys.path:
            sys.path.insert(0, str(agent_src))
        try:
            from graphmine_agent import models  # type: ignore

            self.models = {name: getattr(models, name) for name in SCHEMAS}
        except Exception as error:  # noqa: BLE001 - optional dependency
            self.error = f"{type(error).__name__}: {error}"

    @property
    def strict(self) -> bool:
        return bool(self.models)

    def check(self, schema: str, output) -> tuple[str | None, str | None]:
        """Return (canonical_json, error)."""
        model = self.models.get(schema)
        if model is None:
            return None, None
        try:
            obj = model.model_validate(output)
        except Exception as error:  # pydantic.ValidationError
            text = str(error)
            return None, text[:1200]
        return obj.model_dump_json(), None


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


class Catalog:
    def __init__(self, repo: Path):
        self.problems: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.domains: list[dict] = []
        self.loaded_from = None
        catalog_path = repo / "graphmine_catalog.json"
        if catalog_path.is_file():
            data = json.loads(catalog_path.read_text())
            self.loaded_from = str(catalog_path)
            for pid, info in data.get("problem_index", {}).items():
                self.problems[pid] = {
                    "id": pid,
                    "name": info.get("name", pid),
                    "category": info.get("category", "other"),
                    "status": info.get("library_status", "unknown"),
                    "operation_ids": list(info.get("operation_ids", [])),
                }
            for op in data.get("operations", []):
                backends = []
                for b in op.get("backend_details") or []:
                    backends.append(
                        {
                            "id": b.get("id"),
                            "name": b.get("display_name", b.get("id")),
                            "capabilities": b.get("capabilities", []),
                            "validated": b.get("validated", True),
                        }
                    )
                if not backends:
                    backends = [{"id": b, "name": b, "capabilities": [], "validated": True}
                                for b in op.get("backends", []) if isinstance(b, str)]
                self.operations[op["id"]] = {
                    "id": op["id"],
                    "problem_id": op.get("research_problem_id"),
                    "backends": backends,
                }
        profiles = repo / "agent" / "domain_profiles.json"
        if profiles.is_file():
            data = json.loads(profiles.read_text())
            self.domains = [{"id": d["id"], "name": d["name"]} for d in data.get("domains", [])]

    def problem_of_operation(self, operation_id):
        op = self.operations.get(operation_id or "")
        return op and op.get("problem_id")

    def backend_ids(self, operation_id) -> set[str]:
        op = self.operations.get(operation_id or "")
        return {b["id"] for b in op["backends"]} if op else set()

    def public(self) -> dict:
        return {
            "problems": list(self.problems.values()),
            "operations": list(self.operations.values()),
            "domains": self.domains,
            "loaded_from": self.loaded_from,
        }


# --------------------------------------------------------------------------
# Dataset discovery and indexing
# --------------------------------------------------------------------------


def discover(root: Path, max_depth: int = 3) -> list[dict]:
    found = []
    root = root.resolve()
    for current, dirs, files in os.walk(root):
        path = Path(current)
        depth = len(path.relative_to(root).parts)
        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRS and not d.startswith(".") and not d.endswith("-triton")
            and "checkpoint" not in d and "runtime" not in d and depth < max_depth
        )
        names = set(files)
        layout = None
        if "sft-index.jsonl" in names and (path / "sft").is_dir():
            layout = "reusable"
        elif "provenance.json" in names and "train.jsonl" in names:
            if (path / "train.jsonl").stat().st_size > 0:
                layout = "flat"
        elif STUDIO_MARKER in names:
            layout = "studio"
        if not layout:
            continue
        rel = str(path.relative_to(root))
        extra = {}
        if layout == "reusable":
            with (path / "sft-index.jsonl").open() as stream:
                rows = sum(1 for _ in stream)
        elif layout == "flat":
            try:
                rows = len(json.loads((path / "provenance.json").read_text()).get("rows", []))
            except (ValueError, OSError):
                rows = 0
        else:
            # Created empty in the studio: every row lives in the workspace journal.
            rows = 0
            try:
                marker = json.loads((path / STUDIO_MARKER).read_text())
                extra = {"name": marker.get("name"), "description": marker.get("description", "")}
            except (ValueError, OSError):
                pass
        found.append(
            {
                "key": re.sub(r"[^A-Za-z0-9._-]", "__", rel),
                "path": rel,
                "layout": layout,
                "rows": rows,
                "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                **extra,
            }
        )
    found.sort(key=lambda d: d["modified"], reverse=True)
    return found


def name_datasets(datasets: list[dict], names_path: Path) -> None:
    """Attach the display name, group and description from ``dataset-names.json``.

    Keyed by the dataset path relative to the data root. A dataset created in
    the studio falls back to the name in its own marker file, any other to its path.
    """
    names = {}
    if names_path.is_file():
        try:
            names = json.loads(names_path.read_text()).get("datasets", {})
        except ValueError as error:
            print(f"[studio] ignoring {names_path.name}: {error}")
    for d in datasets:
        entry = names.get(d["path"]) or {}
        d["name"] = entry.get("name") or d.get("name") or d["path"]
        d["group"] = entry.get("group") or ("Created in the studio" if d["layout"] == "studio" else None)
        d["description"] = entry.get("description") or d.get("description") or ""


def read_lines_with_offsets(path: Path):
    offset = 0
    with path.open("rb") as stream:
        for line in stream:
            yield offset, line
            offset += len(line)


def parse_turn(role: str, content: str) -> dict:
    try:
        payload = json.loads(content)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        text = payload.get("message")
        if not isinstance(text, str):
            # The agent's reply after an answer carries the interpretation, not a message.
            text = get_path(payload, "interpretation.summary")
        if not isinstance(text, str):
            text = json.dumps(payload, ensure_ascii=False)
        return {"role": role, "text": text, "status": payload.get("status"), "payload": payload}
    return {"role": role, "text": content, "status": None, "payload": None}


def prompt_fields(payload: dict) -> list[dict]:
    fields = []
    for path in ("answer.question", "user_message", "message"):
        value = get_path(payload, path)
        if isinstance(value, str):
            fields.append({"path": path, "label": PROMPT_LABELS[path], "value": value})
    return fields


def infer_schema(output) -> str | None:
    if not isinstance(output, dict):
        return None
    keys = set(output)
    if {"action", "request"} <= keys:
        return "TurnDecision"
    if "supported" in keys and "operation_id" in keys:
        return "RouteDecision"
    if "status" in keys and "plan" in keys:
        return "PlanDraft"
    if "fact_ids" in keys or "findings" in keys:
        return "GroundedNarrative"
    return None


def build_index(ds_path: Path, layout: str) -> list[dict]:
    """Return base examples (without overlay) for one dataset directory."""
    if layout == "studio":
        return []
    if layout == "reusable":
        return _index_reusable(ds_path)
    return _index_flat(ds_path)


def _base_record(*, rid, adapter, split, file, row, offset, row_obj) -> dict:
    messages = row_obj["messages"]
    final_user = messages[-2]["content"] if len(messages) >= 2 else ""
    try:
        payload = json.loads(final_user)
    except ValueError:
        payload = {"message": final_user}
    if not isinstance(payload, dict):
        payload = {"message": str(payload)}
    try:
        output = json.loads(messages[-1]["content"])
    except ValueError:
        output = messages[-1]["content"]
    history = [parse_turn(m["role"], m["content"]) for m in messages[1:-2]]
    selected = payload.get("selected_operation") if isinstance(payload.get("selected_operation"), dict) else {}
    answer_prov = get_path(payload, "answer.provenance") or {}
    return {
        "id": rid,
        "adapter": adapter,
        "split": split,
        "file": file,
        "row": row,
        "offset": offset,
        "row_sha256": digest(row_obj),
        "turns": history,
        "prompts": prompt_fields(payload),
        "output": output,
        "payload_hints": {
            "selected_operation": selected.get("operation_id"),
            "selected_problem": selected.get("problem_id"),
            "answer_operation": answer_prov.get("operation_id") if isinstance(answer_prov, dict) else None,
            "answer_backend": answer_prov.get("backend") if isinstance(answer_prov, dict) else None,
            "domain_id": get_path(payload, "domain.id"),
        },
    }


def _index_reusable(ds: Path) -> list[dict]:
    index = [json.loads(line) for line in (ds / "sft-index.jsonl").open()]
    by_file = defaultdict(dict)
    for item in index:
        by_file[item["file"]][item["row"]] = item
    teacher = {}
    tr_path = ds / "teacher-responses.jsonl"
    if tr_path.is_file():
        for line in tr_path.open():
            r = json.loads(line)
            if r.get("status") != "accepted":
                continue
            contract = r.get("reference_contract") or {}
            teacher[r["id"]] = {
                "case_id": r.get("case_id"),
                "case_sha256": r.get("case_sha256"),
                "schema": r.get("schema"),
                "variant": r.get("variant"),
                "problem_id": contract.get("problem_id"),
                "operation_id": contract.get("operation_id"),
                "teacher": (r.get("teacher") or {}).get("model"),
                "human_review": r.get("human_review"),
            }
    cases = {}
    cases_path = ds / "cases.jsonl"
    if cases_path.is_file():
        for line in cases_path.open():
            c = json.loads(line)
            task = c.get("task") or {}
            cases[c["id"]] = {
                "domain_id": c.get("domain_id"),
                "lineage": c.get("lineage"),
                "case_tags": c.get("tags", []),
                "expected_status": task.get("expected_status"),
                "problem_id": task.get("problem_id"),
                "operation_id": task.get("operation_id"),
                "label_source": (c.get("provenance") or {}).get("label_source"),
            }
    backends = defaultdict(set)
    refs_path = ds / "references.jsonl"
    if refs_path.is_file():
        for line in refs_path.open():
            r = json.loads(line)
            backend = ((r.get("payload") or {}).get("provenance") or {}).get("backend")
            if backend:
                backends[r["case_sha256"]].add(backend)
    out = []
    for file, rows in sorted(by_file.items()):
        adapter = file.split("/")[1] if file.startswith("sft/") else "planner"
        split = Path(file).stem
        for row_no, (offset, line) in enumerate(read_lines_with_offsets(ds / file)):
            item = rows.get(row_no)
            if item is None:
                continue
            row_obj = json.loads(line)
            rec = _base_record(rid=item["id"], adapter=adapter, split=split, file=file,
                               row=row_no, offset=offset, row_obj=row_obj)
            t = teacher.get(item["id"], {})
            c = cases.get(t.get("case_id") or "", {})
            rec.update(
                schema=t.get("schema") or infer_schema(rec["output"]),
                variant=t.get("variant"),
                group=t.get("case_id") or digest(norm_text(_primary(rec))),
                lineage=c.get("lineage") or item.get("source"),
                case_tags=c.get("case_tags", []),
                expected_status=c.get("expected_status"),
                domain_id=c.get("domain_id") or rec["payload_hints"].get("domain_id"),
                teacher=t.get("teacher"),
                label_source=c.get("label_source"),
                auto=_auto_tags(rec, t.get("problem_id") or c.get("problem_id"),
                                t.get("operation_id") or c.get("operation_id"),
                                sorted(backends.get(t.get("case_sha256") or "", set()))),
            )
            if rec["row_sha256"] != item.get("row_sha256"):
                rec["integrity"] = "row hash differs from sft-index"
            out.append(rec)
    return out


def _index_flat(ds: Path) -> list[dict]:
    prov = json.loads((ds / "provenance.json").read_text())
    by_sha = {r["row_sha256"]: r for r in prov.get("rows", []) if "row_sha256" in r}
    adapter = prov.get("adapter") or "planner"
    out = []
    for split in ("train", "validation", "test"):
        path = ds / f"{split}.jsonl"
        if not path.is_file():
            continue
        for row_no, (offset, line) in enumerate(read_lines_with_offsets(path)):
            row_obj = json.loads(line)
            sha = digest(row_obj)
            p = by_sha.get(sha, {})
            rid = p.get("id") or f"{split}-{row_no}"
            rec = _base_record(rid=rid, adapter=adapter, split=split, file=path.name,
                               row=row_no, offset=offset, row_obj=row_obj)
            stage = p.get("stage")
            rec.update(
                schema=stage if stage in SCHEMAS else infer_schema(rec["output"]),
                variant=p.get("family") or (stage if stage not in SCHEMAS else None),
                group=p.get("case_id") or digest(norm_text(_primary(rec))),
                lineage=p.get("lineage") or p.get("family"),
                case_tags=[t for t in (p.get("review_state"), p.get("label_source")) if t],
                expected_status=None,
                domain_id=rec["payload_hints"].get("domain_id"),
                teacher=p.get("teacher_profile"),
                label_source=p.get("label_source"),
                auto=_auto_tags(rec, None, None, []),
            )
            if p and p.get("split") and p["split"] != split:
                rec["integrity"] = f"provenance split {p['split']} differs from file split {split}"
            out.append(rec)
    return out


def _primary(rec) -> str:
    prompts = rec.get("prompts") or []
    return prompts[0]["value"] if prompts else ""


def _message_of(row) -> str:
    """The user message a step answers (the analyst's request for analyst steps)."""
    fields = {p["path"]: p["value"] for p in row.get("prompts") or []}
    if row.get("adapter") == "analyst":
        return fields.get("user_message") or fields.get("answer.question") or ""
    return fields.get("message") or ""


def _after_answer(row) -> bool:
    """A follow-up: the agent already answered once before this step.

    Earlier turns alone do not say so, because production sends the planner's
    messages as history to the main analyst answer too."""
    if row.get("schema") == "TurnDecision":
        return True
    for turn in row.get("turns") or []:
        payload = turn.get("payload") if isinstance(turn.get("payload"), dict) else {}
        if turn.get("role") == "assistant" and (
                turn.get("status") == "answered" or payload.get("result_id") or payload.get("interpretation")):
            return True
    return False


def _is_clarify_reply(row) -> bool:
    turns = row.get("turns") or []
    return (row.get("schema") in ("RouteDecision", "PlanDraft") and bool(turns) and not _after_answer(row)
            and turns[-1].get("role") == "assistant" and turns[-1].get("status") == "needs_information")


def _is_pipeline_only(row) -> bool:
    """Retries and alternative analyst requests come from the pipeline; replays do not make them."""
    variant = row.get("variant") or ""
    return (variant in ("recovery", "custom_chart") or "-recovery-" in row["id"]
            or "-custom-chart" in row["id"])


def conversation_script(rows: list[dict]) -> tuple[dict, list[str]]:
    """Turn one conversation's live steps into the replay script the engine runs.

    Mirrors the conversation view's order: question → [Understanding asking for
    more information → reply] → Understanding → Planning → GraphMine → analyst
    answer, then follow-up branches keyed by their message.
    """
    notes = []
    live = [r for r in rows if not r.get("deleted") and not _is_pipeline_only(r)]
    step = lambda r: {"row": r["id"], "output": r.get("output")}  # noqa: E731

    def first(candidates, what):
        if len(candidates) > 1:
            notes.append(f"{len(candidates)} {what} steps; the replay uses the first.")
        return candidates[0] if candidates else None

    opening = [r for r in live if r["schema"] in ("RouteDecision", "PlanDraft")
               and not _after_answer(r) and not _is_clarify_reply(r)]
    replies = [r for r in live if _is_clarify_reply(r)]
    answers = [r for r in live if r["schema"] == "GroundedNarrative" and not _after_answer(r)]
    script = {"question": "", "clarify": None, "reply": None, "route": None, "plan": None, "answer": None,
              "followups": []}
    open_route = first([r for r in opening if r["schema"] == "RouteDecision"], "opening Understanding")
    open_plan = first([r for r in opening if r["schema"] == "PlanDraft"], "opening Planning")
    if replies:
        script["clarify"] = step(open_route) if open_route else None
        script["reply"] = _message_of(replies[0])
        route = first([r for r in replies if r["schema"] == "RouteDecision"], "reply Understanding")
        plan = first([r for r in replies if r["schema"] == "PlanDraft"], "reply Planning")
        script["question"] = replies[0]["turns"][0]["text"] if replies[0]["turns"][0].get("role") == "user" else ""
    else:
        route, plan = open_route, open_plan
    script["route"] = step(route) if route else None
    script["plan"] = step(plan) if plan else None
    answer = first(answers, "main Analyst answer")
    script["answer"] = step(answer) if answer else None
    if not script["question"]:
        anchor = open_route or open_plan or route or plan
        if anchor:
            script["question"] = _message_of(anchor)
        elif answer:
            script["question"] = {p["path"]: p["value"] for p in answer["prompts"]}.get("answer.question", "")
    branches: dict[str, dict] = {}
    for r in live:
        if not _after_answer(r):
            continue
        message = _message_of(r)
        if not message and r["schema"] != "TurnDecision":
            continue
        key = "fu-" + digest(norm_text(message))[:12]
        branch = branches.setdefault(key, {"key": key, "message": message, "check": None, "route": None,
                                           "plan": None, "answer": None})
        slot = {"TurnDecision": "check", "RouteDecision": "route", "PlanDraft": "plan",
                "GroundedNarrative": "answer"}[r["schema"]]
        if branch[slot] is None:
            branch[slot] = step(r)
        else:
            notes.append(f"Two {slot} steps answer the same follow-up; the replay uses the first.")
    script["followups"] = list(branches.values())
    return script, notes


def script_fingerprint(script: dict, settings: dict) -> str:
    """What a replay depends on: written messages and outputs, graph and domain (not derived text)."""
    def strip(s):
        return {"output": s["output"]} if s else None
    return digest({
        "graph": (settings.get("graph") or {}).get("id"),
        "domain": settings.get("domain_id"),
        "question": script["question"], "reply": script["reply"],
        "steps": {k: strip(script[k]) for k in ("clarify", "route", "plan", "answer")},
        "followups": sorted(([f["message"]] + [strip(f[k]) for k in ("check", "route", "plan", "answer")]
                             for f in script["followups"]), key=json.dumps),
    })


def _payload(capture) -> dict | None:
    """The user payload of a captured model call."""
    try:
        return json.loads(capture["messages"][-1]["content"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def _asks_for_information(output) -> bool:
    return isinstance(output, dict) and bool(
        output.get("ambiguity") or output.get("missing_information") or output.get("supported") is False
    )


def link_clarifications(records: list[dict]) -> dict[str, str]:
    """Map each clarification-reply case onto the case whose route asked for it.

    The learning pipeline stores one clarification exchange as two cases: the
    vague question whose route asks for more information (``-business-ambiguous``,
    ``-clarification-first``) and the user's reply, which carries that exchange
    as earlier turns (``-business-resolved``, ``-clarification-reply``). They are
    matched by the exact opening question on the same graph source; when a
    template question is reused, the case with the longest shared id prefix wins.
    """
    groups = defaultdict(list)
    for r in records:
        groups[r["group"]].append(r)
    replies = {}
    for group, rows in groups.items():
        for r in rows:
            turns = r.get("turns") or []
            if (turns and turns[0]["role"] == "user" and turns[-1]["role"] == "assistant"
                    and turns[-1].get("status") == "needs_information"):
                replies[group] = (norm_text(turns[0]["text"]), r.get("lineage"))
                break
    openers = defaultdict(set)
    for group, rows in groups.items():
        if group in replies:
            continue
        for r in rows:
            if not r.get("turns") and r.get("schema") == "RouteDecision" and _asks_for_information(r.get("output")):
                openers[(norm_text(_primary(r)), r.get("lineage"))].add(group)
    alias = {}
    for group, key in replies.items():
        candidates = sorted(openers.get(key, ()))
        if candidates:
            alias[group] = max(candidates, key=lambda c: len(os.path.commonprefix([group, c])))
    return alias


def _auto_tags(rec, problem_id, operation_id, ref_backends) -> dict:
    output = rec["output"] if isinstance(rec["output"], dict) else {}
    hints = rec["payload_hints"]
    operation_id = operation_id or output.get("operation_id") or hints.get("selected_operation") or hints.get("answer_operation")
    problem_id = problem_id or output.get("problem_id") or hints.get("selected_problem")
    planned = (output.get("plan") or {}).get("backend_id") if isinstance(output.get("plan"), dict) else None
    backend = ref_backends[0] if len(ref_backends) == 1 else None
    if not backend and planned and planned != "auto":
        backend = planned
    if not backend and hints.get("answer_backend"):
        backend = hints["answer_backend"]
    return {
        "problem_id": problem_id,
        "operation_id": operation_id,
        "backend": backend,
        "reference_backends": ref_backends,
        "planned_backend": planned,
    }


# --------------------------------------------------------------------------
# Store: base index + journal overlay
# --------------------------------------------------------------------------


class Store:
    def __init__(self, data_root: Path, workspace: Path, catalog: Catalog, schemas: Schemas, engine=None):
        self.data_root = data_root.resolve()
        self.workspace = workspace
        self.catalog = catalog
        self.schemas = schemas
        self.engine = engine
        self.lock = threading.RLock()
        self.current = None
        self.datasets: list[dict] = []
        self.refresh_datasets()
        # Indexes of other datasets, loaded only to offer templates.
        self._template_bases: dict[str, list[dict]] = {}
        self.base: dict[str, dict] = {}
        # Clarification-reply case -> the case that asked; shown as one conversation.
        self.group_alias: dict[str, str] = {}
        self.order: list[str] = []
        self.overlay: dict[str, dict] = {}
        self.journal_path: Path | None = None
        self._strict_cache: dict[tuple, tuple] = {}
        self._issues: dict[str, list] = {}
        self._cases: dict[str, dict] | None = None
        self._contexts: dict[str, dict | None] = {}
        self._library: list[dict] | None = None
        self._settings_cache: dict | None = None

    # ---------------- dataset lifecycle ----------------
    def dataset(self, key: str) -> dict:
        for d in self.datasets:
            if d["key"] == key:
                return d
        raise KeyError(f"unknown dataset {key!r}")

    def home(self, info: dict) -> Path:
        """Where a dataset's studio files live. A dataset made in the studio keeps
        everything in its own folder; for pipeline datasets the source stays
        untouched and the studio writes to its workspace."""
        if info["layout"] == "studio":
            return self.data_root / info["path"]
        return self.workspace / info["key"]

    def engine_dir(self, info: dict) -> Path:
        return self.home(info) / "engine"

    def refresh_datasets(self) -> None:
        datasets = discover(self.data_root)
        name_datasets(datasets, NAMES_FILE)
        for d in datasets:
            if d["layout"] == "studio":
                self._adopt_workspace_journal(d)
                overlay, _ = self._read_journal(self.home(d) / "journal.jsonl")
                d["rows"] = sum(1 for state in overlay.values() if not state.get("deleted"))
        if self.current:
            self.current = next((d for d in datasets if d["key"] == self.current["key"]), self.current)
        self.datasets = datasets

    def _adopt_workspace_journal(self, info: dict) -> None:
        """Older studio versions kept a created dataset's journal in the workspace."""
        old = self.workspace / info["key"] / "journal.jsonl"
        new = self.home(info) / "journal.jsonl"
        if old.is_file() and not new.exists():
            new.write_bytes(old.read_bytes())
            old.rename(old.with_suffix(".jsonl.moved"))

    @staticmethod
    def _read_journal(path: Path) -> tuple[dict, list[str]]:
        """Replay a journal: the latest state per id, and ids in first-seen order."""
        overlay, seen = {}, []
        if path.is_file():
            for line in path.open():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("state") is None:
                    overlay.pop(entry["id"], None)
                else:
                    overlay[entry["id"]] = entry["state"]
                if entry["id"] not in seen:
                    seen.append(entry["id"])
        return overlay, seen

    def _load_base(self, info: dict) -> list[dict]:
        ds_path = self.data_root / info["path"]
        wdir = self.workspace / info["key"]
        wdir.mkdir(parents=True, exist_ok=True)
        fingerprint = self._fingerprint(ds_path)
        cache = wdir / "index-cache.json"
        if cache.is_file():
            try:
                cached = json.loads(cache.read_text())
                if cached.get("fingerprint") == fingerprint and cached.get("version") == INDEX_VERSION:
                    return cached["examples"]
            except (ValueError, KeyError):
                pass
        started = time.time()
        base = build_index(ds_path, info["layout"])
        cache.write_text(json.dumps({"version": INDEX_VERSION, "fingerprint": fingerprint, "examples": base}))
        print(f"[studio] indexed {len(base)} rows from {info['path']} in {time.time() - started:.1f}s")
        return base

    def open(self, key: str) -> dict:
        with self.lock:
            info = self.dataset(key)
            base = self._load_base(info)
            self.current = info
            self.base = {r["id"]: r for r in base}
            self.group_alias = link_clarifications(base)
            self.order = [r["id"] for r in base]
            home = self.home(info)
            home.mkdir(parents=True, exist_ok=True)
            self.journal_path = home / "journal.jsonl"
            self.overlay, seen = self._read_journal(self.journal_path)
            self.order += [rid for rid in seen if rid not in self.base]
            self._cases = None
            self._contexts = {}
            self._settings_cache = None
            self._recompute_issues()
            return {"dataset": info, "count": len(self.order)}

    def _key_of(self, folder: Path) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "__", str(folder.relative_to(self.data_root)))

    def create_dataset(self, name: str, description: str = "") -> dict:
        """Create an empty dataset under ``studio-datasets/`` and open it."""
        name = self._check_name(name)
        with self.lock:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "dataset"
            parent = self.data_root / STUDIO_DIR
            folder, n = parent / slug, 2
            # A leftover workspace would bring back an old journal, so skip those names too.
            while folder.exists() or (self.workspace / self._key_of(folder)).exists():
                folder, n = parent / f"{slug}-{n}", n + 1
            folder.mkdir(parents=True)
            marker = {
                "schema_version": "graphmine-dataset-studio-dataset-v1",
                "name": name,
                "description": (description or "").strip(),
                "created_at": utc_now(),
                "note": "Created in Dataset Studio. journal.jsonl holds every step; conversations.json the graph "
                        "and domain of each conversation; engine/ the replayed model inputs and GraphMine results.",
            }
            (folder / STUDIO_MARKER).write_text(json.dumps(marker, indent=2, ensure_ascii=False) + "\n")
            self.refresh_datasets()
            return {**self.open(self._key_of(folder)), "datasets": self.datasets}

    def _check_name(self, name: str, *, except_key: str | None = None) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("Give the dataset a name")
        if len(name) > 80:
            raise ValueError("Keep the name to 80 characters or fewer")
        if any(d["name"].lower() == name.lower() and d["key"] != except_key for d in self.datasets):
            raise ValueError(f"A dataset named {name!r} already exists")
        return name

    def update_dataset(self, key: str, name: str, description: str = "") -> dict:
        """Rename or re-describe a dataset made in the studio (its folder keeps its name)."""
        with self.lock:
            info = self.dataset(key)
            if info["layout"] != "studio":
                raise ValueError("Only datasets made in the studio can be renamed here; "
                                 "name pipeline datasets in dataset-names.json")
            name = self._check_name(name, except_key=key)
            path = self.home(info) / STUDIO_MARKER
            marker = json.loads(path.read_text())
            marker.update({"name": name, "description": (description or "").strip(), "updated_at": utc_now()})
            path.write_text(json.dumps(marker, indent=2, ensure_ascii=False) + "\n")
            self.refresh_datasets()
            return {"dataset": self.dataset(key), "datasets": self.datasets}

    def delete_dataset(self, key: str) -> dict:
        """Move a studio-made dataset to studio-datasets/.deleted/ (restorable by moving it back)."""
        with self.lock:
            info = self.dataset(key)
            if info["layout"] != "studio":
                raise ValueError("Only datasets made in the studio can be deleted here")
            folder = self.home(info)
            trash = self.data_root / STUDIO_DIR / ".deleted"
            trash.mkdir(parents=True, exist_ok=True)
            target = trash / f"{folder.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            folder.rename(target)
            was_open = self.current and self.current["key"] == key
            self.refresh_datasets()
            if was_open:
                self.current = None
                fallback = next((d for d in self.datasets if d["layout"] == "reusable"),
                                self.datasets[0] if self.datasets else None)
                if fallback:
                    self.open(fallback["key"])
                else:
                    self.base, self.order, self.overlay, self.journal_path = {}, [], {}, None
            return {"moved_to": str(target), "datasets": self.datasets,
                    "current": self.current["key"] if self.current else None}

    # ---------------- conversation settings: graph and domain ----------------
    def _settings_path(self) -> Path:
        return self.home(self.current) / "conversations.json"

    def _studio_settings(self) -> dict:
        if self._settings_cache is None:
            path = self._settings_path() if self.current else None
            self._settings_cache = json.loads(path.read_text()) if path and path.is_file() else {}
        return self._settings_cache

    def _write_settings(self, settings: dict) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(path)
        self._settings_cache = settings

    def _case_map(self) -> dict:
        """Graph, attachments and domain of every case in a pipeline dataset."""
        if self._cases is None:
            self._cases = {}
            path = self.data_root / self.current["path"] / "cases.jsonl"
            if self.current["layout"] == "reusable" and path.is_file():
                for line in path.open():
                    c = json.loads(line)
                    self._cases[c["id"]] = {"graph": c.get("graph"), "attachments": c.get("attachments") or {},
                                            "domain_id": c.get("domain_id") or "general", "lineage": c.get("lineage")}
        return self._cases

    def conversation_settings(self, group: str) -> dict | None:
        """Graph and domain the agent replays this conversation on, or None."""
        own = self._studio_settings().get(group)
        if own:
            return own
        case = self._case_map().get(group)
        if case and case.get("graph"):
            graph_id = digest({"graph": case["graph"], "attachments": case["attachments"]})[:16]
            return {"domain_id": case["domain_id"], "source": "case",
                    "graph": {"id": graph_id, "name": case["lineage"] or group, "origin": "case",
                              "vertices": len(case["graph"].get("vertices", [])),
                              "edges": len(case["graph"].get("edges", []))}}
        return None

    def set_conversation_settings(self, group: str, *, domain_id: str, graph_id: str) -> dict:
        with self.lock:
            if domain_id not in {d["id"] for d in self.catalog.domains}:
                raise ValueError(f"Unknown domain {domain_id!r}")
            graph = self._graph_meta(graph_id)
            settings = self._studio_settings()
            entry = settings.get(group, {"created_at": utc_now()})
            entry.update({"domain_id": domain_id, "graph": graph, "updated_at": utc_now()})
            settings[group] = entry
            self._write_settings(settings)
            self._contexts.pop(group, None)
            return entry

    def _graph_input(self, settings: dict, group: str) -> tuple[dict, dict]:
        """(graph file for the agent, attachments) for a conversation's settings."""
        if settings.get("source") == "case":
            case = self._case_map()[group]
            return ({"filename": "dataset.json", "content": json.dumps(case["graph"], allow_nan=False).encode(),
                     "media_type": "application/json", "directed": False}, case["attachments"])
        stored = self._read_graph(settings["graph"]["id"])
        return ({"filename": stored["filename"], "content": stored["content"].encode(),
                 "media_type": stored.get("media_type"), "directed": stored.get("directed", False)},
                stored.get("attachments") or {})

    def template(self, schema: str, want: str = "any", operation: str | None = None) -> dict:
        """A real expected output to start a new step from: the open dataset first, then the others."""
        def fits(r) -> bool:
            out = r.get("output")
            if r.get("schema") != schema or not isinstance(out, dict):
                return False
            if want == "ask":
                return _asks_for_information(out)
            if want == "supported":
                return out.get("supported") is True
            if want == "ready":
                return out.get("status") == "ready"
            return True

        with self.lock:
            for info in sorted(self.datasets, key=lambda d: d is not self.current):
                if info["layout"] == "studio":
                    continue
                if info is self.current:
                    base = list(self.base.values())
                else:
                    if info["key"] not in self._template_bases:
                        self._template_bases[info["key"]] = self._load_base(info)
                    base = self._template_bases[info["key"]]
                matches = [r for r in base if fits(r)]
                pick = next((r for r in matches if operation and (r.get("auto") or {}).get("operation_id") == operation), None)
                pick = pick or (matches[0] if matches else None)
                if pick:
                    return {"output": pick["output"], "source": f"{info['name']} · {pick['id']}"}
        raise KeyError(f"no {schema} example in any dataset")

    # ---------------- graphs: the open dataset's own and the case library ----------------
    def _graphs_dir(self) -> Path:
        return self.home(self.current) / "graphs"

    def _read_graph(self, graph_id: str) -> dict:
        path = self._graphs_dir() / f"{_safe(graph_id)}.json"
        if not path.is_file():
            raise KeyError(f"graph {graph_id}")
        return json.loads(path.read_text())

    def _graph_meta(self, graph_id: str) -> dict:
        stored = self._read_graph(graph_id)
        return {k: stored.get(k) for k in ("id", "name", "origin", "filename", "directed", "vertices", "edges")}

    def _library_index(self) -> list[dict]:
        """Distinct graphs (with attachments) used by cases of every pipeline dataset."""
        if self._library is None:
            seen = {}
            for info in self.datasets:
                path = self.data_root / info["path"] / "cases.jsonl"
                if info["layout"] != "reusable" or not path.is_file():
                    continue
                for line in path.open():
                    c = json.loads(line)
                    if not c.get("graph"):
                        continue
                    gid = digest({"graph": c["graph"], "attachments": c.get("attachments") or {}})[:16]
                    if gid not in seen:
                        seen[gid] = {"id": gid, "name": c.get("lineage") or c["id"], "origin": "library",
                                     "vertices": len(c["graph"].get("vertices", [])),
                                     "edges": len(c["graph"].get("edges", [])),
                                     "attachments": sorted((c.get("attachments") or {}).keys()),
                                     "example_question": (c.get("task") or {}).get("question", "")[:160],
                                     "dataset": info["name"],
                                     "_graph": c["graph"], "_attachments": c.get("attachments") or {}}
            self._library = list(seen.values())
        return self._library

    def graphs(self) -> dict:
        with self.lock:
            own = []
            if self.current and self._graphs_dir().is_dir():
                for path in sorted(self._graphs_dir().glob("*.json")):
                    stored = json.loads(path.read_text())
                    own.append({k: stored.get(k) for k in ("id", "name", "origin", "filename", "directed",
                                                           "vertices", "edges", "added_at")})
            library = [{k: v for k, v in g.items() if not k.startswith("_")} for g in self._library_index()]
            return {"dataset": own, "library": library}

    def _store_graph(self, record: dict) -> dict:
        folder = self._graphs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_safe(record['id'])}.json"
        if not path.is_file():
            path.write_text(json.dumps({**record, "added_at": utc_now()}, ensure_ascii=False))
        return self._graph_meta(record["id"])

    def use_library_graph(self, library_id: str) -> dict:
        with self.lock:
            item = next((g for g in self._library_index() if g["id"] == library_id), None)
            if item is None:
                raise KeyError(f"library graph {library_id}")
            return self._store_graph({
                "id": item["id"], "name": item["name"], "origin": "library", "filename": "dataset.json",
                "media_type": "application/json", "directed": False,
                "content": json.dumps(item["_graph"], allow_nan=False), "attachments": item["_attachments"],
                "vertices": item["vertices"], "edges": item["edges"]})

    def upload_graph(self, name: str, filename: str, content: str, directed: bool) -> dict:
        """Store an uploaded graph after the agent's own ingestion accepts it."""
        if not content:
            raise ValueError("The file is empty")
        filename = Path(filename or "graph.json").name
        suffix = Path(filename).suffix.lower()
        if suffix not in (".json", ".csv", ".tsv", ".txt"):
            raise ValueError("Upload a GraphMine graph (.json) or an edge list (.csv, .tsv, .txt)")
        media = "application/json" if suffix == ".json" else "text/csv"
        if not self.engine or not self.engine.available:
            raise ValueError("Uploads are checked by the GraphMine agent, which is not available: "
                             + ((self.engine and self.engine.error) or "start the studio with the repository's .venv"))
        meta = self.engine.inspect_graph(filename, content.encode(), media, directed, self.engine_dir(self.current) / "tmp")
        with self.lock:
            return self._store_graph({
                "id": digest({"content": content, "directed": directed, "filename": filename})[:16],
                "name": (name or "").strip() or meta.get("name") or filename, "origin": "upload",
                "filename": filename, "media_type": media, "directed": directed, "content": content,
                "attachments": {}, "vertices": meta.get("vertices"), "edges": meta.get("edges")})

    # ---------------- replaying conversations through the agent ----------------
    def _context_path(self, group: str) -> Path:
        return self.engine_dir(self.current) / "context" / f"{_safe(group)[:80]}-{digest(group)[:8]}.json"

    def _context(self, group: str) -> dict | None:
        if group not in self._contexts:
            path = self._context_path(group)
            self._contexts[group] = json.loads(path.read_text()) if path.is_file() else None
        return self._contexts[group]

    def _group_rows(self, group: str) -> list[dict]:
        return [ex for ex in (self.effective(i) for i in self.ids()) if ex["group"] == group]

    def _fingerprint_of(self, group: str, rows: list[dict] | None = None) -> str | None:
        settings = self.conversation_settings(group)
        if not settings:
            return None
        script, _ = conversation_script(rows if rows is not None else self._group_rows(group))
        return script_fingerprint(script, settings)

    def conversation_summary(self, group: str, rows: list[dict] | None = None) -> dict:
        """What the studio knows about replaying this conversation."""
        settings = self.conversation_settings(group)
        engine_ok = bool(self.engine and self.engine.available)
        out = {"group": group, "replayable": bool(settings) and engine_ok, "settings": settings,
               "built": False, "fresh": False}
        report = self._context(group)
        if report:
            out.update({
                "built": True,
                "fresh": settings is not None and report.get("fingerprint") == self._fingerprint_of(group, rows),
                "built_at": report.get("built_at"), "needs_run": report.get("needs_run", False),
                "ran": bool(report.get("facts")) or bool(report.get("runs")) or bool(report.get("cached_runs")),
                "main": {k: (report.get("main") or {}).get(k) for k in ("status", "message", "operation_id")},
                "facts": len(report.get("facts") or []),
                "captured": sorted(report.get("steps") or {}),
                "next": [{k: n.get(k) for k in ("branch", "schema", "operation_id")} for n in report.get("next") or []],
                "events": report.get("events") or [],
                "notes": report.get("notes") or [],
            })
        return out

    def conversation_summaries(self, examples: list[dict]) -> dict:
        groups = defaultdict(list)
        for ex in examples:
            groups[ex["group"]].append(ex)
        wanted = set(self._studio_settings()) | {g for g in groups if self._context(g)}
        out = {g: self.conversation_summary(g, groups.get(g, [])) for g in wanted if g in groups}
        if self.current and self.current["layout"] == "reusable":
            # Every case can be replayed; report that cheaply without fingerprints.
            cases = self._case_map()
            for g in groups:
                if g not in out and g in cases:
                    out[g] = {"group": g, "replayable": bool(self.engine and self.engine.available),
                              "settings": None, "built": False, "fresh": False, "case": True}
        return out

    def build_context(self, group: str, *, run: bool = False) -> dict:
        if not self.engine or not self.engine.available:
            raise ValueError("The replay engine is not available: "
                             + ((self.engine and self.engine.error) or "start the studio with the repository's .venv"))
        with self.lock:
            rows = [r for r in self._group_rows(group) if not r["deleted"]]
            if not rows:
                raise KeyError(f"conversation {group}")
            settings = self.conversation_settings(group)
            if not settings:
                raise ValueError("Choose a graph and domain for this conversation first")
            script, notes = conversation_script(rows)
            graph, attachments = self._graph_input(settings, group)
            engine_dir = self.engine_dir(self.current)
            fingerprint = script_fingerprint(script, settings)
            dataset_key = self.current["key"]
        # The engine has its own lock; a GraphMine run must not block browsing.
        report = self.engine.build({**script, "graph": graph, "attachments": attachments,
                                    "domain_id": settings["domain_id"]},
                                   run=run, run_dir=engine_dir / "runs", tmp_root=engine_dir / "tmp")
        report.update({"group": group, "fingerprint": fingerprint, "notes": notes, "question": script["question"]})
        with self.lock:
            if not self.current or self.current["key"] != dataset_key:
                raise LookupError("The open dataset changed while the conversation was being built")
            path = self._context_path(group)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False))
            self._contexts[group] = report
            before = dict(self._issues)
            changed = self._apply_context(group, report)
            self._recompute_issues()
            return {"summary": self.conversation_summary(group), "context": self._public_context(report),
                    "examples": [self.effective(i) for i in changed], "issues": self._changed_issue_map(before)}

    def _apply_context(self, group: str, report: dict) -> list[str]:
        """Show a step written here with the history and request the agent actually sends."""
        changed = []
        for rid, capture in (report.get("steps") or {}).items():
            if rid in self.base or rid not in self.overlay or self.overlay[rid].get("clone_of"):
                continue
            messages = capture["messages"]
            try:
                payload = json.loads(messages[-1]["content"])
            except ValueError:
                continue
            state = dict(self.overlay[rid])
            turns = [parse_turn(m["role"], m["content"]) for m in messages[1:-1]]
            fields = prompt_fields(payload) or state.get("prompt_fields", [])
            if turns == state.get("turns") and fields == state.get("prompt_fields") and "prompts" not in state:
                continue
            state.update({"turns": turns, "prompt_fields": fields})
            state.pop("prompts", None)
            self._write("context", rid, state)
            changed.append(rid)
        return changed

    @staticmethod
    def _public_context(report: dict) -> dict:
        """The build report for the browser: inputs of the next steps and the facts."""
        return {k: report.get(k) for k in ("built_at", "seconds", "next", "events", "main", "facts",
                                            "followup_options", "derived", "needs_run", "runs", "cached_runs",
                                            "notes", "question")}

    def conversation_context(self, group: str) -> dict:
        with self.lock:
            report = self._context(group)
            return {"summary": self.conversation_summary(group),
                    "context": self._public_context(report) if report else None}

    def preview_understanding(self, *, question: str, domain_id: str, graph_id: str) -> dict:
        """The Understanding input for a question that has no steps yet."""
        if not self.engine or not self.engine.available:
            raise ValueError("The replay engine is not available")
        with self.lock:
            settings = {"domain_id": domain_id, "graph": self._graph_meta(graph_id), "source": "studio"}
            graph, attachments = self._graph_input(settings, "")
            engine_dir = self.engine_dir(self.current)
        script = {"question": question, "clarify": None, "reply": None, "route": None, "plan": None,
                  "answer": None, "followups": [], "graph": graph, "attachments": attachments,
                  "domain_id": domain_id}
        report = self.engine.build(script, run=False, run_dir=engine_dir / "runs", tmp_root=engine_dir / "tmp")
        first = next((n for n in report["next"] if n.get("messages")), None)
        return {"messages": first["messages"] if first else None, "events": report["events"]}

    def _freshness(self) -> dict:
        """group -> (fresh, captured row ids) for every conversation that was built."""
        out = {}
        if not self.current:
            return out
        folder = self.engine_dir(self.current) / "context"
        if folder.is_dir():
            for path in folder.glob("*.json"):
                try:
                    report = json.loads(path.read_text())
                except ValueError:
                    continue
                group = report.get("group")
                if group:
                    self._contexts.setdefault(group, report)
        groups = defaultdict(list)
        contexts = {g: r for g, r in self._contexts.items() if r}
        if not contexts:
            return out
        for ex in (self.effective(i) for i in self.ids()):
            if ex["group"] in contexts:
                groups[ex["group"]].append(ex)
        for group, report in contexts.items():
            fresh = report.get("fingerprint") == self._fingerprint_of(group, groups.get(group, []))
            out[group] = (fresh, set(report.get("steps") or {}))
        return out

    def duplicate_conversation(self, group: str) -> dict:
        """Copy every step into a new conversation; original steps keep their model context."""
        with self.lock:
            rows = [r for r in self._group_rows(group) if not r["deleted"]]
            if not rows:
                raise KeyError(f"conversation {group}")
            new_group = f"studio-conv-{uuid.uuid4().hex[:12]}"
            before = dict(self._issues)
            ids = []
            for r in rows:
                if r["kind"] == "new":
                    state = {k: v for k, v in self.overlay[r["id"]].items()
                             if k in ("adapter", "schema", "split", "prompt_fields", "prompts", "turns", "output", "tags")}
                else:
                    state = {"clone_of": r.get("clone_of") or r["id"], "split": r["split"], "turns": r["turns"],
                             "prompts": {p["path"]: p["value"] for p in r["prompts"]}, "output": r["output"]}
                    if r["manual_tags"]:
                        state["tags"] = dict(r["manual_tags"])
                state["group"] = new_group
                rid = f"studio-{uuid.uuid4().hex[:12]}"
                self._write("duplicate", rid, state)
                ids.append(rid)
            settings = self.conversation_settings(group)
            if settings and self.current["layout"] == "studio":
                own = self._studio_settings()
                own[new_group] = {**settings, "created_at": utc_now(), "duplicated_from": group}
                self._write_settings(own)
            self._recompute_issues()
            return {"group": new_group, "examples": [self.effective(i) for i in ids],
                    "issues": self._changed_issue_map(before)}

    @staticmethod
    def _fingerprint(ds_path: Path) -> list:
        items = []
        for path in sorted(ds_path.rglob("*.jsonl")) + [ds_path / "provenance.json"]:
            if path.is_file():
                st = path.stat()
                items.append([str(path.relative_to(ds_path)), st.st_size, int(st.st_mtime)])
        return items

    # ---------------- effective examples ----------------
    def ids(self) -> list[str]:
        return [i for i in self.order if i in self.base or i in self.overlay]

    def effective(self, rid: str) -> dict:
        base = self.base.get(rid)
        state = self.overlay.get(rid)
        if base is None and state is None:
            raise KeyError(rid)
        if base is None:
            source = self.base.get(state.get("clone_of") or "")
            base = source or {}
            kind = "clone" if source else "new"
        elif state:
            content = any(k in state for k in ("prompts", "turns", "output", "split"))
            kind = "edited" if content else "annotated"
        else:
            kind = "original"
        state = state or {}
        prompts = [dict(p) for p in (base.get("prompts") or [])]
        if kind == "new":
            prompts = [dict(p) for p in state.get("prompt_fields", [])]
        for p in prompts:
            if p["path"] in (state.get("prompts") or {}):
                p["value"] = state["prompts"][p["path"]]
        auto = dict(base.get("auto") or {"problem_id": None, "operation_id": None, "backend": None,
                                         "reference_backends": [], "planned_backend": None})
        output = state["output"] if "output" in state else base.get("output")
        if kind != "original" and isinstance(output, dict):
            # Tags derived from an edited output should follow the edit.
            if output.get("operation_id"):
                auto["operation_id"] = output["operation_id"]
                auto["problem_id"] = output.get("problem_id") or auto["problem_id"]
            plan = output.get("plan")
            if isinstance(plan, dict):
                auto["planned_backend"] = plan.get("backend_id")
        manual = {k: v for k, v in (state.get("tags") or {}).items() if v}
        tags = {k: manual.get(k) or auto.get(k) for k in ("problem_id", "operation_id", "backend")}
        changed = sorted(k for k in ("prompts", "turns", "output", "split", "tags", "labels", "review", "notes") if k in state)
        group = state.get("group") or base.get("group") or rid
        ex = {
            "id": rid,
            "kind": kind,
            "clone_of": state.get("clone_of"),
            "adapter": state.get("adapter") or base.get("adapter"),
            "split": state.get("split") or base.get("split"),
            "schema": state.get("schema") or base.get("schema"),
            "variant": base.get("variant") if kind != "new" else "manual",
            "group": self.group_alias.get(group, group),
            # A step written here takes the source of its conversation's graph.
            "lineage": base.get("lineage") or (((self._studio_settings().get(self.group_alias.get(group, group)) or {}).get("graph") or {})
                                                .get("name") if kind == "new" else None),
            "case_tags": base.get("case_tags", []),
            "expected_status": base.get("expected_status"),
            "domain_id": base.get("domain_id"),
            "teacher": base.get("teacher") if kind in ("original", "edited", "annotated") else None,
            "turns": state["turns"] if "turns" in state else base.get("turns", []),
            "prompts": prompts,
            "output": output,
            "auto_tags": auto,
            "manual_tags": manual,
            "tags": tags,
            "labels": state.get("labels", []),
            "review": state.get("review", "unreviewed"),
            "notes": state.get("notes", ""),
            "deleted": bool(state.get("deleted")),
            "changed": changed,
            "needs_context": kind == "new",
            "updated_at": state.get("updated_at"),
            "integrity": base.get("integrity"),
            "issues": self._issues.get(rid, []),
        }
        return ex

    def all_effective(self) -> list[dict]:
        with self.lock:
            return [self.effective(i) for i in self.ids()]

    # ---------------- validation ----------------
    def _strict(self, schema, output):
        key = (schema, json.dumps(output, sort_keys=True, ensure_ascii=False))
        if key not in self._strict_cache:
            self._strict_cache[key] = self.schemas.check(schema, output)
        return self._strict_cache[key]

    def validate(self, ex: dict, context: dict | None = None) -> list[dict]:
        issues = []

        def add(level, field, message):
            issues.append({"level": level, "field": field, "message": message})

        output = ex.get("output")
        schema = ex.get("schema")
        if not isinstance(output, dict):
            add("error", "output", "Expected output must be a JSON object.")
        else:
            if self.schemas.strict and schema in SCHEMAS:
                _, error = self._strict(schema, output)
                if error:
                    add("error", "output", f"Does not match the agent's {schema} schema: {error}")
            elif schema not in SCHEMAS:
                add("warning", "schema", "Unknown output schema; strict validation skipped.")
            op = output.get("operation_id")
            problem = output.get("problem_id")
            if op and op not in self.catalog.operations:
                add("error", "output.operation_id", f"Operation {op!r} is not in the GraphMine catalog.")
            if problem and problem not in self.catalog.problems:
                add("error", "output.problem_id", f"Problem {problem!r} is not in the GraphMine catalog.")
            if op and problem and self.catalog.problem_of_operation(op) not in (None, problem):
                add("error", "output", f"Operation {op} belongs to {self.catalog.problem_of_operation(op)}, not {problem}.")
            if schema == "RouteDecision" and output.get("supported") and not op:
                add("error", "output.operation_id", "supported=true requires an operation_id.")
            plan = output.get("plan")
            if schema == "PlanDraft":
                status = output.get("status")
                if status == "ready" and not isinstance(plan, dict):
                    add("error", "output.plan", "status=ready requires a complete plan.")
                if status in ("needs_information", "unsupported") and plan is not None:
                    add("error", "output.plan", f"status={status} requires plan=null.")
            if isinstance(plan, dict):
                backend = plan.get("backend_id")
                op_for_plan = ex["tags"].get("operation_id")
                allowed = self.catalog.backend_ids(op_for_plan)
                if backend and backend != "auto" and allowed and backend not in allowed:
                    add("error", "output.plan.backend_id", f"Backend {backend!r} is not a backend of {op_for_plan}.")
        tags = ex.get("tags") or {}
        if tags.get("operation_id") and tags["operation_id"] not in self.catalog.operations:
            add("warning", "tags.operation_id", "Tagged operation is not in the catalog.")
        if tags.get("problem_id") and tags.get("operation_id"):
            owner = self.catalog.problem_of_operation(tags["operation_id"])
            if owner and owner != tags["problem_id"]:
                add("warning", "tags", f"Tagged operation belongs to {owner}, not {tags['problem_id']}.")
        if tags.get("backend") and tags.get("operation_id"):
            allowed = self.catalog.backend_ids(tags["operation_id"])
            if allowed and tags["backend"] not in allowed:
                add("warning", "tags.backend", f"{tags['backend']} is not an implementation of {tags['operation_id']}.")
        if isinstance(output, dict) and output.get("operation_id") and ex["manual_tags"].get("operation_id") \
                and output["operation_id"] != ex["manual_tags"]["operation_id"]:
            add("warning", "tags.operation_id", "Manual operation tag differs from the operation in the expected output.")
        prompts = ex.get("prompts") or []
        if not prompts or not any((p.get("value") or "").strip() for p in prompts):
            add("error", "prompts", "The user question is empty.")
        if ex.get("needs_context"):
            replay = (context or {}).get("replay", {}).get(ex.get("group"))
            if replay is None:
                add("info", "context", "Written here, so it has no model input yet. Choose a graph and build the "
                                       "conversation to export it as a training row; until then it goes to "
                                       "needs-context.jsonl.")
            elif ex["id"] not in replay[1]:
                add("warning", "context", "The last build of this conversation did not reach this step, so it has no "
                                          "model input and goes to needs-context.jsonl.")
            elif not replay[0]:
                add("warning", "context", "The conversation changed after its last build: rebuild it so this step's "
                                          "model input matches the steps before it.")
            elif schema == "GroundedNarrative" and isinstance(output, dict):
                problem = ((self._contexts.get(ex["group"]) or {}).get("checks") or {}).get(ex["id"])
                if problem:
                    add("error", "output", f"The agent rejects this answer: {problem}")
            if replay is not None and ex["id"] in replay[1] and schema == "GroundedNarrative" \
                    and isinstance(output, dict) and self.engine and self.engine.available:
                # Cited facts can be checked at once against the last analyst input.
                capture = ((self._contexts.get(ex["group"]) or {}).get("steps") or {}).get(ex["id"])
                payload = _payload(capture)
                if payload:
                    from studio_engine import narrative_problem
                    problem = narrative_problem(self.engine.m, None, output, payload)
                    if problem and not any(i["message"].endswith(problem) for i in issues):
                        add("error", "output", f"The agent would reject this answer: {problem}")
        if ex.get("integrity"):
            add("warning", "integrity", ex["integrity"])
        if context and not ex.get("deleted"):
            lineage_splits = context["lineage_splits"].get(ex.get("lineage"))
            if lineage_splits and len(lineage_splits) > 1:
                add("warning", "split", f"Source {ex.get('lineage')} appears in several splits ({', '.join(sorted(lineage_splits))}); keep a source in one split.")
            q = norm_text(prompts[0]["value"]) if prompts else ""
            qsplits = context["question_splits"].get(q)
            if q and qsplits and len(qsplits) > 1:
                add("info", "split", "This question text also appears in another split (usually on a different graph source).")
        return issues

    def _recompute_issues(self) -> None:
        exs = [self.effective(i) for i in self.ids()]
        lineage_splits = defaultdict(set)
        question_splits = defaultdict(set)
        for ex in exs:
            if ex["deleted"]:
                continue
            if ex.get("lineage"):
                lineage_splits[ex["lineage"]].add(ex["split"])
            if ex["prompts"]:
                question_splits[norm_text(ex["prompts"][0]["value"])].add(ex["split"])
        context = {"lineage_splits": lineage_splits, "question_splits": question_splits,
                   "replay": self._freshness()}
        self._issues = {ex["id"]: self.validate(ex, context) for ex in exs}


    # ---------------- mutations ----------------
    def _write(self, op: str, rid: str, state: dict | None) -> None:
        if state is not None:
            state = {**state, "updated_at": utc_now()}
        entry = {"ts": utc_now(), "op": op, "id": rid, "state": state}
        with self.journal_path.open("a") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if state is None:
            self.overlay.pop(rid, None)
        else:
            self.overlay[rid] = state
        if rid not in self.order:
            self.order.append(rid)

    def _changed_issue_map(self, before: dict) -> dict:
        return {i: v for i, v in self._issues.items() if before.get(i) != v}

    def _normalize_patch(self, rid: str, patch: dict) -> dict:
        state = dict(self.overlay.get(rid) or {})
        base = self.base.get(rid)
        is_new = base is None and not state.get("clone_of")
        for key in ("prompts", "turns", "output", "split", "labels", "review", "notes", "tags", "deleted",
                    "schema", "adapter", "prompt_fields"):
            if key not in patch:
                continue
            if key in ("schema", "adapter", "prompt_fields") and not is_new:
                raise ValueError(f"{key} can only be changed on a new example without model context")
            value = patch[key]
            if key == "review" and value not in REVIEW_STATES:
                raise ValueError(f"review must be one of {REVIEW_STATES}")
            if key == "split" and value not in ("train", "validation", "test"):
                raise ValueError("split must be train, validation or test")
            if key == "tags":
                merged = dict(state.get("tags") or {})
                for k in ("problem_id", "operation_id", "backend"):
                    if k in value:
                        merged[k] = value[k] or None
                value = {k: v for k, v in merged.items() if v}
                if not value:
                    state.pop("tags", None)
                    continue
            if key == "labels":
                value = sorted({str(v).strip() for v in value if str(v).strip()})
            if key == "prompts":
                value = {k: str(v) for k, v in value.items()}
            state[key] = value
        # Drop fields that equal the original so "edited" means really edited.
        if base:
            if state.get("output") == base.get("output"):
                state.pop("output", None)
            if state.get("turns") == base.get("turns"):
                state.pop("turns", None)
            if state.get("split") == base.get("split"):
                state.pop("split", None)
            if "prompts" in state:
                original = {p["path"]: p["value"] for p in base.get("prompts", [])}
                kept = {k: v for k, v in state["prompts"].items() if original.get(k) != v}
                state["prompts"] = kept
                if not kept:
                    state.pop("prompts")
            if state.get("review") == "unreviewed":
                state.pop("review", None)
            if state.get("notes") == "":
                state.pop("notes", None)
            if state.get("labels") == []:
                state.pop("labels", None)
            if not state.get("deleted"):
                state.pop("deleted", None)
        return state

    def update(self, rid: str, patch: dict) -> dict:
        with self.lock:
            if rid not in self.base and rid not in self.overlay:
                raise KeyError(rid)
            before = dict(self._issues)
            state = self._normalize_patch(rid, patch)
            if rid in self.base and not state:
                self._write("revert", rid, None)
            else:
                self._write("update", rid, state)
            self._recompute_issues()
            return {"example": self.effective(rid), "issues": self._changed_issue_map(before)}

    def update_many(self, patches: list[dict]) -> dict:
        """Apply a different patch to each example (e.g. one question edit across a conversation)."""
        with self.lock:
            for item in patches:
                if item["id"] not in self.base and item["id"] not in self.overlay:
                    raise KeyError(item["id"])
            states = [(item["id"], self._normalize_patch(item["id"], item.get("patch") or {})) for item in patches]
            before = dict(self._issues)
            for rid, state in states:
                if rid in self.base and not state:
                    self._write("revert", rid, None)
                else:
                    self._write("update", rid, state)
            self._recompute_issues()
            ids = [rid for rid, _ in states]
            return {"examples": [self.effective(i) for i in ids], "issues": self._changed_issue_map(before)}

    def bulk(self, ids: list[str], patch: dict) -> dict:
        with self.lock:
            before = dict(self._issues)
            for rid in ids:
                state = dict(self.overlay.get(rid) or {})
                p = dict(patch)
                if "labels_add" in p or "labels_remove" in p:
                    current = set(state.get("labels", []))
                    current |= set(p.pop("labels_add", []) or [])
                    current -= set(p.pop("labels_remove", []) or [])
                    p["labels"] = sorted(current)
                new_state = self._normalize_patch(rid, p)
                if rid in self.base and not new_state:
                    self._write("revert", rid, None)
                else:
                    self._write("bulk", rid, new_state)
            self._recompute_issues()
            return {"examples": [self.effective(i) for i in ids], "issues": self._changed_issue_map(before)}

    @staticmethod
    def _new_state(draft: dict) -> dict:
        """Journal state for an example written in the studio (no model context)."""
        adapter = draft.get("adapter") or "planner"
        schema = draft.get("schema")
        if adapter not in ("planner", "analyst"):
            raise ValueError("adapter must be planner or analyst")
        if schema not in SCHEMAS:
            raise ValueError(f"schema must be one of {SCHEMAS}")
        fields = draft.get("prompt_fields") or [
            {"path": "message", "label": PROMPT_LABELS["message"], "value": draft.get("question", "")}
        ]
        state = {
            "adapter": adapter,
            "schema": schema,
            "split": draft.get("split") or "train",
            "prompt_fields": [{"path": f["path"], "label": f.get("label") or PROMPT_LABELS.get(f["path"], f["path"]),
                               "value": f.get("value", "")} for f in fields],
            "turns": draft.get("turns") or [],
            "output": draft.get("output"),
        }
        if draft.get("group"):
            state["group"] = str(draft["group"])
        for key in ("tags", "labels", "review", "notes"):
            if draft.get(key):
                state[key] = draft[key]
        return state

    def create_conversation(self, draft: dict) -> dict:
        """Add several new steps as one conversation, or to an existing one (``group``).

        All steps are checked before any is written, so a bad step adds nothing.
        """
        with self.lock:
            steps = draft.get("steps") or []
            if not steps:
                raise ValueError("Add at least one step")
            group = draft.get("group") or f"studio-conv-{uuid.uuid4().hex[:12]}"
            states = [self._new_state({**step, "group": group}) for step in steps]
            before = dict(self._issues)
            ids = []
            for state in states:
                rid = f"studio-{uuid.uuid4().hex[:12]}"
                self._write("create", rid, state)
                ids.append(rid)
            self._recompute_issues()
            return {"group": group, "examples": [self.effective(i) for i in ids],
                    "issues": self._changed_issue_map(before)}

    def revert(self, ids: list[str]) -> dict:
        with self.lock:
            before = dict(self._issues)
            for rid in ids:
                if rid in self.overlay:
                    # Base rows return to the original; new rows and clones are discarded.
                    self._write("revert" if rid in self.base else "discard", rid, None)
            self._recompute_issues()
            return {"examples": [self.effective(i) for i in ids if i in self.base],
                    "removed": [i for i in ids if i not in self.base],
                    "issues": self._changed_issue_map(before)}

    def history(self, rid: str) -> list[dict]:
        out = []
        if self.journal_path and self.journal_path.is_file():
            for line in self.journal_path.open():
                if line.strip():
                    entry = json.loads(line)
                    if entry["id"] == rid:
                        out.append(entry)
        return out

    def original(self, rid: str) -> dict | None:
        base = self.base.get(rid)
        if base is None:
            state = self.overlay.get(rid) or {}
            base = self.base.get(state.get("clone_of") or "")
        if base is None:
            return None
        return {"prompts": base["prompts"], "turns": base["turns"], "output": base["output"], "split": base["split"]}

    # ---------------- context ----------------
    def raw_row(self, rid: str) -> dict | None:
        base = self.base.get(rid)
        if base is None:
            state = self.overlay.get(rid) or {}
            base = self.base.get(state.get("clone_of") or "")
        if base is None:
            return None
        path = self.data_root / self.current["path"] / base["file"]
        with path.open("rb") as stream:
            stream.seek(base["offset"])
            return json.loads(stream.readline())

    def captured_messages(self, ex: dict) -> tuple[list | None, bool]:
        """(messages the agent sends for a step written here, whether its build is current)."""
        report = self._context(ex["group"])
        capture = ((report or {}).get("steps") or {}).get(ex["id"])
        if not capture:
            return None, False
        return capture["messages"], report.get("fingerprint") == self._fingerprint_of(ex["group"])

    def context(self, rid: str) -> dict:
        row = self.raw_row(rid)
        if row is None:
            ex = self.effective(rid)
            messages, fresh = self.captured_messages(ex)
            if not messages:
                return {"available": False, "replayable": bool(self.conversation_settings(ex["group"]))}
            return {"available": True, "captured": True, "fresh": fresh,
                    "built_at": (self._context(ex["group"]) or {}).get("built_at"),
                    "system": messages[0]["content"] if messages[0]["role"] == "system" else "",
                    "history": [parse_turn(m["role"], m["content"]) for m in messages[1:-1]],
                    "payload": _payload({"messages": messages}) or {"text": messages[-1]["content"]},
                    "user_chars": len(messages[-1]["content"]), "source_id": None}
        messages = row["messages"]
        try:
            payload = json.loads(messages[-2]["content"])
        except ValueError:
            payload = {"text": messages[-2]["content"]}
        return {
            "available": True,
            "system": messages[0]["content"] if messages and messages[0]["role"] == "system" else "",
            "payload": payload,
            "user_chars": len(messages[-2]["content"]),
            "source_id": rid if rid in self.base else (self.overlay.get(rid) or {}).get("clone_of"),
        }

    # ---------------- export ----------------
    def export(self, name: str, *, exclude_rejected: bool = True, approved_only: bool = False) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name or ""):
            raise ValueError("Export name may use letters, digits, dot, dash and underscore only")
        with self.lock:
            dest = self.home(self.current) / "exports" / name
            if dest.exists():
                raise ValueError(f"Export {name!r} already exists")
            dest.mkdir(parents=True)
            streams = {}
            counts = Counter()
            warnings = []
            index_rows = []
            annotations = []
            needs_context = []
            freshness = self._freshness()

            def emit(fname, obj):
                if fname not in streams:
                    p = dest / fname
                    p.parent.mkdir(parents=True, exist_ok=True)
                    streams[fname] = p.open("w")
                streams[fname].write(json.dumps(obj, ensure_ascii=False) + "\n")

            try:
                for rid in self.ids():
                    ex = self.effective(rid)
                    if ex["deleted"]:
                        counts["skipped_deleted"] += 1
                        continue
                    if exclude_rejected and ex["review"] == "rejected":
                        counts["skipped_rejected"] += 1
                        continue
                    if approved_only and ex["review"] != "approved":
                        counts["skipped_not_approved"] += 1
                        continue
                    errors = [i for i in ex["issues"] if i["level"] == "error"]
                    annotations.append({
                        "id": rid, "kind": ex["kind"], "adapter": ex["adapter"], "split": ex["split"],
                        "schema": ex["schema"], "tags": ex["tags"], "auto_tags": ex["auto_tags"],
                        "manual_tags": ex["manual_tags"], "labels": ex["labels"], "review": ex["review"],
                        "notes": ex["notes"], "lineage": ex["lineage"],
                    })
                    captured = None
                    if ex["needs_context"]:
                        replay = freshness.get(ex["group"])
                        if replay and replay[0] and rid in replay[1]:
                            captured = ((self._contexts.get(ex["group"]) or {}).get("steps") or {})[rid]["messages"]
                        else:
                            reason = ("not built" if replay is None else "not reached by the last build"
                                      if rid not in replay[1] else "changed after the last build")
                            needs_context.append({
                                "id": rid, "conversation": ex["group"], "reason": reason, "adapter": ex["adapter"],
                                "schema": ex["schema"], "split": ex["split"], "turns": ex["turns"],
                                "prompts": ex["prompts"], "output": ex["output"], "tags": ex["tags"],
                                "labels": ex["labels"], "notes": ex["notes"],
                            })
                            counts["needs_context"] += 1
                            continue
                    if errors:
                        warnings.append(f"{rid}: exported with {len(errors)} validation error(s): {errors[0]['message'][:200]}")
                    if captured is not None:
                        messages, replaced = self._captured_row(ex, captured), 0
                    else:
                        messages, replaced = self._messages_for(ex)
                    if replaced:
                        counts["propagated_question_edits"] += replaced
                    fname = f"sft/{ex['adapter']}/{ex['split']}.jsonl"
                    row = {"messages": messages}
                    emit(fname, row)
                    index_rows.append({
                        "id": rid, "file": fname, "row": counts[fname], "row_sha256": digest(row),
                        "source": ex["lineage"], "conversation": ex["group"],
                        "origin": "studio-replay" if captured is not None else ex["kind"],
                        "base_row_sha256": (self.base.get(rid) or self.base.get(ex.get("clone_of") or "") or {}).get("row_sha256"),
                    })
                    counts[fname] += 1
                    counts[ex["kind"]] += 1
                for row in index_rows:
                    emit("sft-index.jsonl", row)
                for row in annotations:
                    emit("annotations.jsonl", row)
                for row in needs_context:
                    emit("needs-context.jsonl", row)
            finally:
                for s in streams.values():
                    s.close()
            if self.journal_path and self.journal_path.is_file():
                (dest / "changes.jsonl").write_bytes(self.journal_path.read_bytes())
            src = self.data_root / self.current["path"]
            src_manifest = src / "manifest.json"
            manifest = {
                "schema_version": "graphmine-dataset-studio-export-v1",
                "created_at": utc_now(),
                "base_dataset": str(src),
                "base_manifest_sha256": file_sha256(src_manifest) if src_manifest.is_file() else None,
                "strict_schema_validation": self.schemas.strict,
                "options": {"exclude_rejected": exclude_rejected, "approved_only": approved_only},
                "counts": dict(counts),
                "warnings": warnings,
                "human_review_note": "Review states and tags come from Dataset Studio annotations; teacher targets remain unreviewed unless marked approved.",
                "files": {},
            }
            for path in sorted(dest.rglob("*")):
                if path.is_file():
                    rel = str(path.relative_to(dest))
                    manifest["files"][rel] = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
            (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            return {"path": str(dest), "counts": dict(counts), "warnings": warnings[:50],
                    "warning_count": len(warnings)}

    def _captured_row(self, ex: dict, captured: list[dict]) -> list[dict]:
        """A step written here: the agent's replayed input plus the expected output."""
        canonical, _ = self._strict(ex["schema"], ex["output"]) if self.schemas.strict else (None, None)
        content = canonical or json.dumps(ex["output"], ensure_ascii=False, separators=(",", ":"))
        return [dict(m) for m in captured] + [{"role": "assistant", "content": content}]

    def _messages_for(self, ex: dict) -> tuple[list[dict], int]:
        source_id = ex["id"] if ex["id"] in self.base else ex.get("clone_of")
        row = self.raw_row(source_id)
        messages = [dict(m) for m in row["messages"]]
        base = self.base[source_id]
        replaced = 0
        # Earlier turns
        if ex["turns"] != base["turns"]:
            history = []
            for turn in ex["turns"]:
                payload = dict(turn.get("payload") or {})
                payload["message"] = turn.get("text", "")
                if turn.get("role") == "assistant" and turn.get("status"):
                    payload["status"] = turn["status"]
                history.append({"role": turn["role"], "content": json.dumps(payload, ensure_ascii=False)})
            messages = [messages[0]] + history + messages[-2:]
        # Final user payload
        original_prompts = {p["path"]: p["value"] for p in base["prompts"]}
        edits = {p["path"]: p["value"] for p in ex["prompts"] if original_prompts.get(p["path"]) != p["value"]}
        if edits:
            payload = json.loads(messages[-2]["content"])
            for path, value in edits.items():
                payload, n = replace_strings(payload, original_prompts[path], value)
                replaced += max(n - 1, 0)
                set_path(payload, path, value)
            messages[-2] = {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        # Final assistant target
        if ex["output"] != base["output"]:
            canonical, _ = self._strict(ex["schema"], ex["output"]) if self.schemas.strict else (None, None)
            content = canonical or json.dumps(ex["output"], ensure_ascii=False, separators=(",", ":"))
            messages[-1] = {"role": "assistant", "content": content}
        return messages, replaced

    def changes(self) -> list[dict]:
        out = []
        for rid, state in list(self.overlay.items()):
            ex = self.effective(rid)
            out.append({"id": rid, "kind": ex["kind"], "deleted": ex["deleted"], "changed": ex["changed"],
                        "updated_at": state.get("updated_at"), "question": ex["prompts"][0]["value"] if ex["prompts"] else "",
                        "schema": ex["schema"], "split": ex["split"]})
        out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    store: Store = None  # type: ignore[assignment]
    token: str | None = None
    server_version = "GraphMineDatasetStudio/2.0"

    def log_message(self, fmt, *args):  # quieter console
        if self.path.startswith("/api/") and not self.path.startswith("/api/examples"):
            sys.stderr.write("[studio] %s %s\n" % (self.command, self.path.split("?")[0]))

    def _send(self, status, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, message, status=HTTPStatus.BAD_REQUEST):
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 32 * 1024 * 1024:
            raise ValueError("request too large")
        data = self.rfile.read(length) if length else b"{}"
        return json.loads(data or b"{}")

    def _require_dataset(self):
        if not self.store.current:
            raise LookupError("No dataset is open")

    def _authorized(self) -> bool:
        """Pages load freely; every data request needs the token when one is set."""
        if not self.token or not self.path.startswith("/api/"):
            return True
        sent = self.headers.get("X-Studio-Token") or ""
        return hmac.compare_digest(sent.encode(), self.token.encode())

    def _with_summaries(self, result: dict) -> dict:
        """Mutations also report where their conversations now stand (progress, rebuild needed)."""
        examples = result.get("examples") or ([result["example"]] if result.get("example") else [])
        groups = {ex["group"] for ex in examples}
        if result.get("group"):
            groups.add(result["group"])
        result["conversations"] = {g: self.store.conversation_summary(g) for g in groups}
        return result

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not self._authorized():
            return self._error("This studio needs its access token", HTTPStatus.UNAUTHORIZED)
        s = self.store
        try:
            if url.path == "/api/datasets":
                return self._json({"datasets": s.datasets, "current": s.current and s.current["key"]})
            if url.path == "/api/meta":
                return self._json({
                    "catalog": s.catalog.public(),
                    "strict_schema": s.schemas.strict,
                    "strict_schema_error": s.schemas.error,
                    "engine": s.engine.status() if s.engine else {"available": False, "error": "not loaded"},
                    "schemas": list(SCHEMAS),
                    "review_states": list(REVIEW_STATES),
                    "dataset": s.current,
                    "data_root": str(s.data_root),
                    "workspace": str(s.workspace),
                })
            self._require_dataset()
            if url.path == "/api/examples":
                with s.lock:
                    examples = s.all_effective()
                    return self._json({"dataset": s.current, "examples": examples,
                                       "conversations": s.conversation_summaries(examples)})
            if url.path == "/api/original":
                return self._json({"original": s.original(q["id"])})
            if url.path == "/api/context":
                return self._json(s.context(q["id"]))
            if url.path == "/api/conversation":
                return self._json(s.conversation_context(q["group"]))
            if url.path == "/api/graphs":
                return self._json(s.graphs())
            if url.path == "/api/history":
                return self._json({"history": s.history(q["id"])})
            if url.path == "/api/changes":
                return self._json({"changes": s.changes()})
            return self._static(url.path)
        except KeyError as error:
            return self._error(f"Not found: {error}", HTTPStatus.NOT_FOUND)
        except LookupError as error:
            if url.path.startswith("/api/"):
                return self._error(str(error), HTTPStatus.CONFLICT)
            return self._static(url.path)
        except Exception as error:  # noqa: BLE001
            return self._error(f"{type(error).__name__}: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorized():
            return self._error("This studio needs its access token", HTTPStatus.UNAUTHORIZED)
        try:
            body = self._body()
            s = self.store
            if url.path == "/api/open":
                return self._json(s.open(body["key"]))
            if url.path == "/api/new-dataset":
                return self._json(s.create_dataset(body.get("name", ""), body.get("description", "")))
            if url.path == "/api/dataset/update":
                return self._json(s.update_dataset(body["key"], body.get("name", ""), body.get("description", "")))
            if url.path == "/api/dataset/delete":
                return self._json(s.delete_dataset(body["key"]))
            self._require_dataset()
            if url.path == "/api/template":
                return self._json(s.template(body.get("schema"), body.get("want") or "any", body.get("operation") or None))
            if url.path == "/api/update":
                return self._json(self._with_summaries(s.update(body["id"], body.get("patch") or {})))
            if url.path == "/api/bulk":
                return self._json(self._with_summaries(s.bulk(body["ids"], body.get("patch") or {})))
            if url.path == "/api/update-many":
                return self._json(self._with_summaries(s.update_many(body["patches"])))
            if url.path == "/api/create-conversation":
                return self._json(self._with_summaries(s.create_conversation(body)))
            if url.path == "/api/conversation/duplicate":
                return self._json(self._with_summaries(s.duplicate_conversation(body["group"])))
            if url.path == "/api/conversation/settings":
                s.set_conversation_settings(body["group"], domain_id=body.get("domain_id") or "general",
                                            graph_id=body["graph_id"])
                return self._json({"summary": s.conversation_summary(body["group"])})
            if url.path == "/api/conversation/build":
                return self._json(self._with_summaries(s.build_context(body["group"], run=bool(body.get("run")))))
            if url.path == "/api/preview-understanding":
                return self._json(s.preview_understanding(question=body.get("question", ""),
                                                          domain_id=body.get("domain_id") or "general",
                                                          graph_id=body["graph_id"]))
            if url.path == "/api/graphs/use":
                return self._json({"graph": s.use_library_graph(body["id"])})
            if url.path == "/api/graphs/upload":
                return self._json({"graph": s.upload_graph(body.get("name", ""), body.get("filename", ""),
                                                           body.get("content", ""), bool(body.get("directed")))})
            if url.path == "/api/revert":
                with s.lock:
                    groups = {s.effective(i)["group"] for i in body["ids"] if i in s.base or i in s.overlay}
                    result = s.revert(body["ids"])
                    result["conversations"] = {g: s.conversation_summary(g) for g in groups}
                    return self._json(result)
            if url.path == "/api/validate":
                draft = body
                ex = s.effective(draft["id"]) if draft.get("id") in s.base or draft.get("id") in s.overlay else None
                if ex is None:
                    ex = {"tags": {}, "manual_tags": {}, "prompts": draft.get("prompts") or [{"value": "x"}]}
                ex = {**ex, **{k: v for k, v in draft.items() if k in ("output", "schema", "prompts")}}
                ex.setdefault("tags", {})
                ex.setdefault("manual_tags", {})
                if "tags" in draft:
                    ex["tags"] = {**ex["tags"], **{k: v for k, v in draft["tags"].items() if v}}
                with s.lock:
                    context = {"lineage_splits": {}, "question_splits": {}, "replay": s._freshness()}
                    return self._json({"issues": s.validate(ex, context)})
            if url.path == "/api/export":
                return self._json(s.export(body.get("name", ""),
                                           exclude_rejected=bool(body.get("exclude_rejected", True)),
                                           approved_only=bool(body.get("approved_only", False))))
            return self._error("Unknown endpoint", HTTPStatus.NOT_FOUND)
        except KeyError as error:
            return self._error(f"Not found or missing field: {error}", HTTPStatus.NOT_FOUND)
        except LookupError as error:
            return self._error(str(error), HTTPStatus.CONFLICT)
        except ValueError as error:
            return self._error(str(error))
        except Exception as error:  # noqa: BLE001
            return self._error(f"{type(error).__name__}: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.is_file():
            return self._error("Not found", HTTPStatus.NOT_FOUND)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        return self._send(HTTPStatus.OK, target.read_bytes(), ctype)


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def access_token(args, workspace: Path) -> str | None:
    """A token is required whenever the studio listens beyond this machine.
    It is kept in the workspace so bookmarked links survive restarts."""
    if args.token:
        return args.token
    if args.host in LOOPBACK or args.no_token:
        return None
    path = workspace / ".studio-token"
    if path.is_file() and path.read_text().strip():
        return path.read_text().strip()
    workspace.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description="GraphMine Dataset Studio")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO,
                        help="GraphMine repository (catalog, domain profiles, agent schemas)")
    parser.add_argument("--data-root", type=Path, default=None,
                        help="Directory searched for datasets (default: <repo>/.graphmine-learning)")
    parser.add_argument("--dataset", default=None, help="Dataset key or relative path to open at startup")
    parser.add_argument("--workspace", type=Path, default=APP_DIR / "workspace",
                        help="Where edits to pipeline datasets, their exports and the access token are kept")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--token", default=None, help="Access token (default: generated when --host is not local)")
    parser.add_argument("--no-token", action="store_true", help="Serve beyond localhost without a token (unsafe)")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    data_root = (args.data_root or repo / ".graphmine-learning").resolve()
    if not data_root.is_dir():
        parser.error(f"data root not found: {data_root}")
    workspace = args.workspace.resolve()
    schemas = Schemas(repo / "agent")
    catalog = Catalog(repo)
    from studio_engine import Engine
    engine = Engine(repo)
    store = Store(data_root, workspace, catalog, schemas, engine)
    wanted = args.dataset
    choice = next((d for d in store.datasets if wanted in (d["key"], d["path"])), None) if wanted else None
    if choice is None and store.datasets:
        choice = next((d for d in store.datasets if d["layout"] == "reusable"), store.datasets[0])
    if choice:
        store.open(choice["key"])
    Handler.store = store
    Handler.token = access_token(args, workspace)
    if args.host not in LOOPBACK and not Handler.token:
        print("[studio] WARNING: listening beyond localhost without a token; anyone on the network can edit.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[studio] strict schema validation: {'on' if schemas.strict else 'off (' + str(schemas.error) + ')'}")
    print(f"[studio] replay engine: {'on' if engine.available else 'off (' + str(engine.error) + ')'}")
    print(f"[studio] {len(store.datasets)} dataset(s) under {data_root}; "
          f"opened {choice['path'] if choice else 'none (create one in the picker)'}")
    shown = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    print(f"[studio] open http://{shown}:{args.port}/" + (f"?token={Handler.token}" if Handler.token else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
