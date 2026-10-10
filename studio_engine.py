"""Replay a Dataset Studio conversation through the real GraphMine agent.

Every model call is answered by a forcing model. It records the exact messages
production would send for that call (system prompt, conversation history, user
payload) and returns the expected output written in the studio for that step.
Running the agent end to end this way gives every step its real model input,
derives the text the user would see (clarification questions, GraphMine's
replies), and executes ready plans with the GraphMine binary.

A step without an expected output stops its branch of the replay. Its input is
still recorded, so the studio can show it while the output is being written.

Results of GraphMine runs are cached by plan and graph, so rebuilding a
conversation after an edit only re-runs GraphMine when the plan changed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

STAGE_NAMES = {
    "RouteDecision": "Understanding",
    "PlanDraft": "Planning",
    "GroundedNarrative": "Analyst answer",
    "TurnDecision": "Follow-up check",
}


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EngineUnavailable(RuntimeError):
    pass


@dataclass
class _Report:
    steps: dict = field(default_factory=dict)
    next: list = field(default_factory=list)
    events: list = field(default_factory=list)
    main: dict = field(default_factory=dict)
    facts: list = field(default_factory=list)
    followup_options: list = field(default_factory=list)
    derived: dict = field(default_factory=dict)
    needs_run: bool = False
    runs: int = 0
    cached_runs: int = 0
    checks: dict = field(default_factory=dict)

    def event(self, level: str, stage: str, message: str, branch: str = "main") -> None:
        self.events.append({"level": level, "stage": stage, "message": message, "branch": branch})


@dataclass
class _Main:
    session: object = None
    graph: object = None
    outcome: object = None
    result: object = None


class Engine:
    """One agent replay at a time: replays share the GPU and agent module state."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.error: str | None = None
        self.lock = threading.Lock()
        self.m = None
        self.base = None
        try:
            self._load()
        except Exception as error:  # noqa: BLE001 - the studio still works without the engine
            self.error = f"{type(error).__name__}: {error}"

    def _load(self) -> None:
        from graphmine_agent.agent_service import AgentService
        from graphmine_agent.analysis import validate_narrative
        from graphmine_agent.catalog import Catalog
        from graphmine_agent.config import Settings
        from graphmine_agent.database import Database
        from graphmine_agent.execution import GraphMineRunner
        from graphmine_agent.graph_store import GraphStore
        from graphmine_agent.jobs import EventBus, JobManager
        from graphmine_agent.llm import LLMError, runtime_messages
        from graphmine_agent.models import (
            ChatRequest,
            FileRole,
            GroundedNarrative,
            JobRecord,
            JobStatus,
            LLMMode,
            PlanRequest,
            ResultRecord,
            SessionRecord,
            new_id,
        )
        from graphmine_agent.planning import PlanValidator
        from graphmine_agent.results import summarize_result, validate_result
        from graphmine_agent.visualization import answer_visualizations

        self.m = SimpleNamespace(**{k: v for k, v in locals().items() if k != "self"})
        self.base = Settings.from_env(self.repo)
        binary = Path(self.base.graphmine_binary)
        stat = binary.stat() if binary.is_file() else None
        self.binary = {"path": str(binary), "available": stat is not None,
                       "stamp": [stat.st_size, int(stat.st_mtime)] if stat else None}

    @property
    def available(self) -> bool:
        return self.m is not None

    def status(self) -> dict:
        return {"available": self.available, "error": self.error,
                "graphmine": (self.binary or {}).get("available", False) if self.available else False}

    # ------------------------------------------------------------------ API
    def inspect_graph(self, filename: str, content: bytes, media_type: str, directed: bool, tmp_root: Path) -> dict:
        """Ingest a graph the way the agent does; raise ValueError when it is rejected."""
        if not self.available:
            raise EngineUnavailable(self.error or "The GraphMine agent is not importable")
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="inspect-", dir=tmp_root))
        try:
            m = self.m
            settings = replace(self.base, data_root=tmp, history_directory=None, llm_enabled=False)
            database = m.Database(settings.database_path)
            store = m.GraphStore(settings, database)
            session = database.create_session(m.SessionRecord())
            try:
                stored = store.ingest(session_id=session.id, role=m.FileRole.graph, filename=filename,
                                      content=content, media_type=media_type, directed=directed)
            except Exception as error:  # noqa: BLE001 - the agent's own reason
                raise ValueError(f"The agent cannot read this graph: {_explain(error)}") from error
            meta = stored.metadata
            get = (lambda k: getattr(meta, k, None)) if not isinstance(meta, dict) else meta.get
            return {"name": get("name"), "vertices": get("vertex_count"), "edges": get("edge_count"),
                    "directed": get("directed")}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def build(self, script: dict, *, run: bool, run_dir: Path, tmp_root: Path) -> dict:
        """Replay a whole conversation. ``run`` lets GraphMine execute plans it has
        no cached result for; otherwise the replay stops before the first run."""
        if not self.available:
            raise EngineUnavailable(self.error or "The GraphMine agent is not importable")
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp_root.mkdir(parents=True, exist_ok=True)
        with self.lock:
            started = time.monotonic()
            report = asyncio.run(self._build(script, run, run_dir, tmp_root))
            return {
                "version": 1,
                "built_at": _now(),
                "seconds": round(time.monotonic() - started, 2),
                "steps": report.steps,
                "next": report.next,
                "events": report.events,
                "main": report.main,
                "facts": report.facts,
                "followup_options": report.followup_options,
                "derived": report.derived,
                "needs_run": report.needs_run,
                "runs": report.runs,
                "cached_runs": report.cached_runs,
                "checks": report.checks,
            }

    # ------------------------------------------------------------------ replay
    async def _build(self, script, run, run_dir, tmp_root) -> _Report:
        tmp = Path(tempfile.mkdtemp(prefix="replay-", dir=tmp_root))
        report = _Report()
        rt = None
        try:
            rt = self._runtime(tmp)
            rt.forcing.recording, rt.forcing.branch = True, "main"
            main = await self._replay_main(rt, script, run, run_dir, report, record=True)
            followups = script.get("followups") or []
            if followups and main.result is None:
                report.event("info", "Follow-up messages",
                             "Follow-ups continue from the first answer, so they are built once GraphMine has run the main plan.")
            elif followups:
                for fu in followups:
                    await self._replay_followup(rt, script, fu, run, run_dir, report)
            self._collect(rt.forcing, script, report)
            return report
        finally:
            if rt is not None:
                await rt.service.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def _runtime(self, tmp: Path):
        m = self.m
        settings = replace(self.base, data_root=tmp, history_directory=None, llm_enabled=False)
        catalog = m.Catalog(settings)
        database = m.Database(settings.database_path)
        store = m.GraphStore(settings, database)
        validator = m.PlanValidator(catalog)
        runner = m.GraphMineRunner(settings, catalog, store, validator)
        jobs = m.JobManager(database, runner, m.EventBus(database), summary_items=20)
        service = m.AgentService(settings, catalog, database, store, validator, jobs)
        forcing = _Forcing(m)
        service.model = forcing
        return SimpleNamespace(settings=settings, catalog=catalog, database=database, store=store,
                               validator=validator, runner=runner, service=service, forcing=forcing)

    def _session(self, rt, script):
        m = self.m
        session = rt.database.create_session(m.SessionRecord(domain_id=script.get("domain_id") or "general"))
        graph = script["graph"]
        stored = rt.store.ingest(
            session_id=session.id, role=m.FileRole.graph, filename=graph["filename"],
            content=graph["content"], media_type=graph.get("media_type"), directed=bool(graph.get("directed")),
        )
        for name, files in (script.get("attachments") or {}).items():
            for index, item in enumerate(files):
                rt.store.ingest(
                    session_id=session.id, role=m.FileRole(item["role"]), filename=f"{name}-{index}.json",
                    content=json.dumps(item["content"], allow_nan=False).encode(), media_type="application/json",
                )
        return session, stored

    @staticmethod
    def _step(step, record):
        """(row id to credit the capture to, forced output) for one scripted step."""
        if not step:
            return (None, None)
        return (step["row"] if record else None, step.get("output"))

    async def _plan(self, rt, session, graph, message, report, stage, record, branch="main"):
        m = self.m
        try:
            return await rt.service.plan(session.id, m.PlanRequest(message=message, graph_id=graph.id))
        except _Missing:
            return None
        except Exception as error:  # noqa: BLE001 - reported to the reviewer
            if record:
                report.event("error", stage, _explain(error), branch)
            return None

    async def _replay_main(self, rt, script, run, run_dir, report, record) -> _Main:
        f = rt.forcing
        session, graph = self._session(rt, script)
        main = _Main(session=session, graph=graph)
        message = script["question"]
        if script.get("clarify"):
            f.expect({"RouteDecision": self._step(script["clarify"], record)})
            outcome = await self._plan(rt, session, graph, message, report, "Understanding", record)
            if outcome is None:
                return main
            if outcome.status != "needs_information":
                if record:
                    report.event("error", "Understanding",
                                 f"With this output the agent does not ask the user anything; it reports "
                                 f"“{outcome.status}”: {outcome.message}")
                return main
            if record:
                report.derived["clarification"] = outcome.message
            if not script.get("reply"):
                if record:
                    report.next.append({"branch": "main", "schema": "reply", "messages": None})
                return main
            message = script["reply"]
        f.expect({"RouteDecision": self._step(script.get("route"), record),
                  "PlanDraft": self._step(script.get("plan"), record)})
        outcome = await self._plan(rt, session, graph, message, report, "Planning", record)
        main.outcome = outcome
        if outcome is None:
            return main
        if record:
            report.main = {"status": outcome.status, "message": outcome.message,
                           "operation_id": outcome.plan.operation_id if outcome.plan else None,
                           "plan": outcome.plan.model_dump(mode="json") if outcome.plan else None}
            if outcome.status != "ready":
                report.event("info", "Planning", f"The agent stops here and tells the user: {outcome.message}")
        if outcome.status != "ready":
            return main
        plans = self._for_execution(rt, outcome.plans, report, "Main analysis", record)
        if plans is None:
            return main
        results = await self._execute(rt, session, plans, run, run_dir, report, "Main analysis", record)
        if results is None:
            return main
        f.expect({"GroundedNarrative": self._step(script.get("answer"), record)})
        main.result = await self._interpret(rt, results, plans, report, record, script.get("answer"), "Analyst answer")
        if main.result is not None and record:
            payload = _payload_of(f.last("GroundedNarrative"))
            report.facts = (payload or {}).get("answer", {}).get("facts", [])
            report.followup_options = (payload or {}).get("followup_options", [])
            report.derived["reply"] = main.result.interpretation.summary if main.result.interpretation else None
        return main

    async def _replay_followup(self, rt, script, fu, run, run_dir, report):
        m, f = self.m, rt.forcing
        label = f"Follow-up “{_short(fu['message'])}”"
        f.recording, f.branch = False, "main"
        main = await self._replay_main(rt, script, False, run_dir, report, record=False)
        if main.result is None:
            return
        f.recording, f.branch = True, fu["key"]
        f.expect({
            "TurnDecision": self._step(fu.get("check"), True),
            "RouteDecision": self._step(fu.get("route"), True),
            "PlanDraft": self._step(fu.get("plan"), True),
            "GroundedNarrative": self._step(fu.get("answer"), True),
        })
        try:
            response = await rt.service.chat(main.session.id, m.ChatRequest(
                message=fu["message"], graph_id=main.graph.id, result_id=main.result.id, mode="auto", execute=False))
        except _Missing:
            return
        except Exception as error:  # noqa: BLE001
            report.event("error", label, _explain(error), fu["key"])
            return
        if response.mode == m.LLMMode.analyst:
            answer = rt.database.get_result(main.result.id).answer
            self._check_answer(rt, fu.get("answer"), answer, report, label, fu["key"])
            return
        if response.planning_status == "ready" and response.plan is not None:
            plans = self._for_execution(rt, [response.plan], report, label, True, fu["key"])
            if plans is None:
                return
            results = await self._execute(rt, main.session, plans, run, run_dir, report, label, True, fu["key"])
            if results is not None:
                f.expect({"GroundedNarrative": self._step(fu.get("answer"), True)})
                await self._interpret(rt, results, plans, report, True, fu.get("answer"), label, fu["key"])
        else:
            report.event("info", label, f"The agent stops here and tells the user: {response.message}", fu["key"])

    def _for_execution(self, rt, plans, report, stage, record, branch="main"):
        caps = rt.runner.capabilities
        try:
            return [rt.validator.validate(
                plan,
                compiled_backends=rt.runner.compiled_backends_for(plan.operation_id) if caps.binary_available else None,
                for_execution=True,
            ) for plan in plans]
        except Exception as error:  # noqa: BLE001
            if record:
                report.event("error", stage, f"The plan does not pass the execution check: {_explain(error)}", branch)
            return None

    def _run_key(self, rt, plan) -> str:
        data = plan.model_dump(mode="json")
        data.pop("session_id", None)
        data.pop("graph_id", None)
        data["auxiliary_inputs"] = {
            name: [rt.database.get_file(identifier).sha256 for identifier in identifiers]
            for name, identifiers in (data.get("auxiliary_inputs") or {}).items()
        }
        graph = rt.database.get_file(plan.graph_id)
        return _digest({"plan": data, "graph": graph.sha256, "binary": self.binary.get("stamp")})[:40]

    async def _execute(self, rt, session, plans, run, run_dir, report, stage, record, branch="main"):
        m = self.m
        analysis_id = m.new_id("analysis") if len(plans) > 1 else None
        results = []
        for index, plan in enumerate(plans):
            cache = run_dir / f"{self._run_key(rt, plan)}.json"
            if cache.is_file():
                payload = json.loads(cache.read_text())["payload"]
                if record:
                    report.cached_runs += 1
            elif not run:
                if record:
                    report.needs_run = True
                    report.next.append({"branch": branch, "schema": "run", "messages": None,
                                        "operation_id": plan.operation_id})
                return None
            else:
                if not rt.runner.capabilities.binary_available:
                    report.event("error", stage, "The GraphMine binary is not available, so the plan cannot run.", branch)
                    return None
                started = time.monotonic()
                try:
                    payload, command = await rt.runner.execute(plan, rt.settings.workspaces_root / f"run-{uuid.uuid4().hex[:12]}")
                    if payload.get("ok"):
                        m.validate_result(rt.catalog, plan.operation_id, payload)
                except Exception as error:  # noqa: BLE001
                    report.event("error", stage, f"GraphMine could not run {plan.operation_id}: {_explain(error)}", branch)
                    return None
                if not payload.get("ok"):
                    detail = payload.get("error") or {}
                    report.event("error", stage, f"GraphMine reported {detail.get('code', 'a failure')}: "
                                                 f"{detail.get('message', 'no message')}", branch)
                    return None
                seconds = round(time.monotonic() - started, 2)
                cache.write_text(json.dumps({"operation_id": plan.operation_id, "ran_at": _now(), "seconds": seconds,
                                             "command": [str(c) for c in command], "payload": payload}))
                report.runs += 1
                report.event("info", stage, f"GraphMine ran {plan.operation_id} in {seconds} s.", branch)
            job = m.JobRecord(session_id=session.id, plan=plan, analysis_id=analysis_id, step_index=index,
                              step_count=len(plans), status=m.JobStatus.completed)
            rt.database.save_job(job)
            result = rt.database.save_result(m.ResultRecord(
                job_id=job.id, session_id=session.id, operation_id=plan.operation_id,
                payload=payload, summary=m.summarize_result(payload, 20)))
            rt.database.save_job(job.model_copy(update={"result_id": result.id}))
            results.append(result)
        return results

    async def _interpret(self, rt, results, plans, report, record, answer_step, stage, branch="main"):
        """Interpret every step's result like the job worker does; the last one asks the analyst."""
        final = None
        for result, plan in zip(results, plans):
            message = plan.application_intent.objective if plan.application_intent else "Explain the computed result."
            try:
                final = await rt.service.interpret(result.id, user_message=message)
            except Exception as error:  # noqa: BLE001
                if record:
                    report.event("error", stage, _explain(error), branch)
                return None
        if record and final is not None:
            self._check_answer(rt, answer_step, final.answer, report, stage, branch)
        return final

    def _check_answer(self, rt, answer_step, answer, report, stage, branch):
        """The agent silently falls back when it rejects an analyst answer; say why."""
        if not answer_step or answer_step.get("output") is None:
            return
        payload = _payload_of(rt.forcing.first_for(answer_step["row"]))
        if not payload:
            return
        problem = narrative_problem(self.m, rt.catalog, answer_step["output"], payload, answer)
        report.checks[answer_step["row"]] = problem
        if problem:
            report.event("error", stage, f"The agent rejects this answer: {problem}", branch)

    @staticmethod
    def _collect(forcing, script, report) -> None:
        wanted = {}
        for key, step in _script_steps(script):
            wanted[step["row"]] = key
        for capture in forcing.captures:
            if not capture["recording"]:
                continue
            row = capture["row"]
            if capture["missing"] and capture["first_in_branch"]:
                report.next.append({"branch": capture["branch"], "schema": capture["schema"],
                                    "messages": capture["messages"]})
            if row is None:
                continue
            entry = report.steps.setdefault(row, {"schema": capture["schema"], "messages": capture["messages"], "calls": 0})
            entry["calls"] += 1
        for row, key in wanted.items():
            if row not in report.steps:
                stage = STAGE_NAMES.get(key.split(":")[-1], key)
                report.event("warning", stage, "Not reached: with the outputs before it, the agent never asks for this "
                                               "step here, so it has no model input and is not exported.",
                             key.split(":")[0])
        # A step the agent asked for repeatedly (scope review, repair) trains only on its first input.
        for row, entry in report.steps.items():
            if entry["calls"] > 1:
                report.event("info", STAGE_NAMES.get(entry["schema"], entry["schema"]),
                             f"The agent asked this stage {entry['calls']} times (review or repair); the first input is the "
                             "training input.", "main")


class _Missing(Exception):
    """No expected output yet: stops this branch of the replay."""


class _Forcing:
    """Stands in for the model: records each call's messages, returns the studio's output."""

    def __init__(self, m):
        self.m = m
        self.mapping: dict = {}
        self.captures: list = []
        self.recording = True
        self.branch = "main"
        self._missing_seen: set = set()
        # LLMError is what the agent catches for analyst fallbacks; raise a subclass of it.
        self.missing_error = type("MissingOutput", (_Missing, m.LLMError), {})

    def expect(self, mapping: dict) -> None:
        self.mapping = mapping

    async def close(self) -> None:
        pass

    def last(self, schema):
        found = [c for c in self.captures if c["schema"] == schema and c["recording"]]
        return found[-1] if found else None

    def first_for(self, row):
        return next((c for c in self.captures if c["row"] == row), None)

    async def generate(self, *, mode, schema, user_payload, conversation=None, **_):
        name = schema.__name__
        messages = self.m.runtime_messages(mode=mode, schema=schema, user_payload=user_payload, conversation=conversation)
        row, output = self.mapping.get(name, (None, None))
        missing = output is None
        key = (self.branch, name)
        first_missing = missing and key not in self._missing_seen
        if missing:
            self._missing_seen.add(key)
        self.captures.append({"schema": name, "row": row, "messages": messages, "missing": missing,
                              "first_in_branch": first_missing, "branch": self.branch, "recording": self.recording})
        if missing:
            raise self.missing_error(f"No expected {STAGE_NAMES.get(name, name)} output yet")
        try:
            return schema.model_validate(output)
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"The {STAGE_NAMES.get(name, name)} output does not match {name}: {error}") from error


def narrative_problem(m, catalog, output, payload, answer=None) -> str | None:
    """Why the agent would reject this analyst answer, or None.

    The cited facts and follow-ups are checked against the analyst's input. The
    chart and view checks need the full computed ``answer``, which only a build has."""
    try:
        narrative = m.GroundedNarrative.model_validate(output)
    except Exception as error:  # noqa: BLE001
        return f"it does not match GroundedNarrative: {error}"
    known = {fact["id"] for fact in (payload.get("answer") or {}).get("facts", [])}
    cited = set(narrative.fact_ids)
    for statement in ([narrative.summary] if narrative.summary else []) + narrative.findings + narrative.charts:
        cited.update(statement.fact_ids)
    unknown = sorted(cited - known)
    if unknown:
        return f"it cites facts that are not in the computed result: {', '.join(unknown)}"
    options = {item["id"] for item in payload.get("followup_options", [])}
    if not set(narrative.followup_ids) <= options:
        return f"it offers follow-ups that are not available: {', '.join(sorted(set(narrative.followup_ids) - options))}"
    if answer is not None:
        try:
            m.validate_narrative(narrative, answer, m.answer_visualizations(answer), set(catalog.instructions))
        except ValueError as error:
            return str(error)
    return None


def _script_steps(script):
    """(stage key, step) for every scripted step that has a row."""
    out = []
    for name, schema in (("clarify", "RouteDecision"), ("route", "RouteDecision"), ("plan", "PlanDraft"),
                         ("answer", "GroundedNarrative")):
        if script.get(name):
            out.append((f"main:{schema}", script[name]))
    for fu in script.get("followups") or []:
        for name, schema in (("check", "TurnDecision"), ("route", "RouteDecision"), ("plan", "PlanDraft"),
                             ("answer", "GroundedNarrative")):
            if fu.get(name):
                out.append((f"{fu['key']}:{schema}", fu[name]))
    return out


def _payload_of(capture):
    if not capture:
        return None
    try:
        return json.loads(capture["messages"][-1]["content"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _explain(error: Exception) -> str:
    text = str(error) or type(error).__name__
    return text if len(text) < 600 else text[:600] + "…"


def _short(text: str, n: int = 50) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"
