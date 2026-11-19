"""The browser's HTTP workflow, shared by Locust and protocol tests.

This module never imports application internals. Selecting a card submits its
opaque IDs and offered parameters; expected operations are assertions only.
"""
from __future__ import annotations

import time
from uuid import uuid4


class JourneyError(Exception):
    def __init__(self, code, message, step):
        self.code, self.step = code, step
        super().__init__(message)


class Journey:
    def __init__(self, request, *, sleep=time.sleep, poll_seconds=1, deadline_seconds=2400):
        self.request, self.sleep = request, sleep
        self.poll_seconds, self.deadline_seconds = poll_seconds, deadline_seconds
        self.session_id = self.inputs = None
        self.previous_workflow = None

    def start_session(self, config):
        sources = self.request("GET", "/api/database-sources", step="sources")
        source = next((s for s in sources if s["id"] == config.get("source_id")), None)
        if source is None:
            source = next((s for s in sources if "yelp" in (s.get("id", "")+s.get("name", "")).lower()), None)
        if source is None:
            raise JourneyError("yelp_missing", "No Yelp source is available to the test account", "dataset")
        datasets = self.request("GET", f"/api/database-sources/{source['id']}/datasets", step="datasets")
        dataset = next((d for d in datasets if d["id"] == "yelp"), None)
        if dataset is None:
            raise JourneyError("yelp_missing", "The selected source does not expose the Yelp dataset", "dataset")
        query = config.get("query") or dataset.get("default_query")
        if not query:
            raise JourneyError("query_missing", "Yelp has no published default query; supply --query", "dataset")
        preview = self.request("POST", f"/api/database-sources/{source['id']}/queries", step="query",
            json={"statement": query, "dataset_id": "yelp", "name": "Yelp performance test"})
        if not preview.get("dataset"):
            raise JourneyError("empty_input", "The Yelp query returned no graph", "dataset")
        metadata = preview["dataset"]
        version = metadata.get("version_id") or metadata.get("id")
        result = self.request("POST", f"/api/database-query-snapshots/{version}/chat", step="start_session",
            json={"domain_id": "general", "title": "Performance test — Yelp"})
        self.session_id = result["session"]["id"]
        self.inputs = {"main": {"file_id": result["file"]["id"], "kind": result["kind"]}}
        self.previous_workflow = None
        graph = result["file"].get("metadata") or {}
        return {"session_id": self.session_id, "source_id": source["id"], "query": query,
                "vertices": graph.get("vertex_count"), "edges": graph.get("edge_count"),
                "input_fingerprint": result["file"].get("sha256") or metadata.get("sha256") or metadata.get("fingerprint")}

    def workspace(self):
        return self.request("GET", f"/api/sessions/{self.session_id}/workspace?history_limit=30", step="poll_conversation")

    def ask(self, question, state, *, spawn):
        started = time.monotonic()
        end = started+self.deadline_seconds
        state.update(turn_ids=[], workflow_id=None, first_reply_ms=None, time_to_answer_ms=None,
                     results_page_ms=[], actual_operations=[], result_items_seen=0)
        def check_deadline(step):
            if time.monotonic() >= end:
                raise JourneyError("journey_timeout", "The question did not finish within the journey deadline", step)
        def first_reply():
            if state["first_reply_ms"] is None:
                state["first_reply_ms"] = (time.monotonic()-started)*1000
        def plan(message, **extra):
            turn_id = str(uuid4())
            state["turn_ids"].append(turn_id)
            state["turn_id"] = turn_id
            body = {"message": message, "mode": "normal", "inputs": self.inputs, "device": "auto",
                    "previous_workflow_id": self.previous_workflow, "request_id": turn_id, **extra}
            pending = spawn(self.request, "POST", f"/api/sessions/{self.session_id}/analytics/plan", step="plan", json=body)
            try:
                while not pending.ready():
                    check_deadline("plan")
                    workspace = self.workspace()
                    messages = [*workspace.get("messages", []),
                                *(e for e in workspace.get("events", []) if e.get("type") == "workflow.chat")]
                    for row in messages:
                        row = row.get("payload", row)
                        if row.get("role") == "assistant" and row.get("turn_id") == turn_id and (row.get("message") or row.get("answer", {}).get("text")):
                            first_reply()
                    self.sleep(self.poll_seconds)
                response = pending.get()
            finally:
                if not pending.ready():
                    pending.kill(block=True)
            if response.get("message") or response.get("answer") or response.get("options"):
                first_reply()
            return response

        response = plan(question["text"])
        for _ in range(6):
            check_deadline("choose_or_clarify")
            if response.get("inputs"):
                self.inputs = response["inputs"]
            status = response.get("status")
            if status == "options":
                options = response.get("options") or []
                if not options:
                    raise JourneyError("empty_options", "The planner offered no calculation choices", "choose")
                option = options[0]
                response = plan("Use "+option["title"]+".", intent="calculate", operations=option["operations"],
                    parameters=option.get("parameters", {}), option_id=option["id"], option_turn_id=response["turn_id"])
            elif status == "needs_information":
                pending = response.get("pending_question") or {}
                clarification = question.get("direction_clarification", "Use an undirected copy for this analysis.") if pending.get("kind") == "direction" else question["clarification"]
                response = plan(clarification, **({"clarification_id": pending["id"]} if pending.get("id") else {}))
            else:
                break
        else:
            raise JourneyError("clarification_loop", "The question did not reach an answer or runnable plan after six follow-ups", "clarify")

        if response.get("status") == "answered":
            state["time_to_answer_ms"] = (time.monotonic()-started)*1000
            state["wrong_operation"] = bool(question["expected_operations"])
            return state
        if response.get("status") != "ready" or not response.get("plan"):
            raise JourneyError("routing_"+str(response.get("status", "missing")), response.get("message", "No executable answer"), "route")
        state["actual_operations"] = [s["operation"] for s in response["plan"]["steps"]]
        expected = set(question["expected_operations"])
        state["wrong_operation"] = not bool(expected.intersection(state["actual_operations"]))
        record = self.request("POST", f"/api/sessions/{self.session_id}/workflows", step="create_workflow",
            json={"mode": "normal", "plan": response["plan"], "inputs": self.inputs, "planning_turn_id": response["turn_id"]})
        workflow = state["workflow_id"] = record["id"]
        self.previous_workflow = workflow
        if record["status"] in {"ready", "awaiting_review"}:
            record = self.request("POST", f"/api/workflows/{workflow}/run", step="approve_calculation",
                json={"workflow_hash": record["validation"]["workflow_hash"], "expected_revision": record["revision"]})
        while record["status"] in {"queued", "running"}:
            check_deadline("calculation")
            self.sleep(self.poll_seconds)
            record = self.request("GET", f"/api/workflows/{workflow}", step="poll_calculation")
        if record["status"] != "completed":
            detail = record.get("error") or {}
            raise JourneyError(detail.get("code", "calculation_"+record["status"]), detail.get("message", "Calculation did not complete"), "calculation")
        # The browser renders a factual answer first, then replaces its pending
        # introduction. Time-to-answer ends at the final answer, not at job exit.
        while True:
            check_deadline("final_answer")
            workspace = self.workspace()
            answers = [e.get("payload", {}) for e in workspace.get("events", [])
                       if e.get("type") == "workflow.answer" and e.get("payload", {}).get("workflow_id") == workflow]
            if any(not a.get("pending", False) for a in answers):
                state["time_to_answer_ms"] = (time.monotonic()-started)*1000
                break
            self.sleep(self.poll_seconds)
        summary = self.request("GET", f"/api/workflows/{workflow}/result?summary=true", step="result_summary")
        ports = [(step, port) for step, row in summary.get("steps", {}).items() if row.get("result")
                 for port in row["result"].get("ports", {})]
        if not ports:
            raise JourneyError("no_results", "The completed calculation has no result view", "result_view")
        step, port = ports[-1]
        view_path = f"/api/workflows/{workflow}/steps/{step}/ports/{port}/view"
        before = time.monotonic()
        view = self.request("GET", view_path, step="result_view")
        state["results_page_ms"].append((time.monotonic()-before)*1000)
        count = view.get("item_count") or 0
        # Scalar/single-result outputs have fewer than three selectable items.
        # Visit every available item up to three; never manufacture indices.
        for index in range(min(3, count)):
            before = time.monotonic()
            self.request("GET", view_path+f"?index={index}", step="result_item")
            state["results_page_ms"].append((time.monotonic()-before)*1000)
            state["result_items_seen"] += 1
        return state
