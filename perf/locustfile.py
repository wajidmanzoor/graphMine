"""One Locust process; unique synthetic account per concurrent user."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gevent
from gevent.queue import Queue
from locust import HttpUser, LoadTestShape, events, task
from locust.exception import StopUser
import yaml

from perf.common import append, read_jsonl, timestamp, seconds
from perf.journey import Journey, JourneyError

RUN = Path(os.environ["GRAPHMINE_PERF_RUN_DIR"])
CONFIG = json.loads((RUN/"private/locust.json").read_text())
QUESTIONS = yaml.safe_load((Path(__file__).with_name("questions.yaml")).read_text())["questions"]
if CONFIG.get("preflight"):
    QUESTIONS = [q for q in QUESTIONS if q["id"] in {"concept","densest-subgraph"}]
REPETITIONS = 1 if CONFIG.get("preflight") else 5
ACCOUNTS = Queue()
for account in CONFIG["accounts"]:
    ACCOUNTS.put(account)
DONE = False


def route_name(path):
    path = path.split("?", 1)[0]
    return re.sub(r"(?<=/)[0-9a-f]{8}-[0-9a-f-]{27,}(?=/|$)", "{id}", path)


class GraphMineUser(HttpUser):
    host = CONFIG["host"]

    def on_start(self):
        self.account = ACCOUNTS.get_nowait()
        self.user_id = self.account["id"]
        self.state, self.in_session, self.question_index = {}, 0, 0
        self.random = random.Random(CONFIG.get("seed", 17)+int(self.account["username"][-2:]))
        self.client.verify = CONFIG.get("verify_tls", True)
        self.client.headers.update({"X-GraphMine-Request": "1", "X-Perf-Run-ID": CONFIG["run_id"]})
        self.journey = Journey(self.request, sleep=gevent.sleep, poll_seconds=CONFIG.get("poll_seconds", 1))
        try:
            login = self.request("POST", "/api/auth/login", step="login", json={
                "username": self.account["username"], "password": self.account["password"], "issue_token": True})
            self.client.headers["Authorization"] = "Bearer "+login["access_token"]
        except JourneyError:
            raise StopUser()

    def request(self, method, path, *, step, **kwargs):
        start, clock, request_id = timestamp(), time.monotonic(), str(uuid4())
        outcome, code, message, status = "success", None, None, None
        headers = {**kwargs.pop("headers", {}), "X-Request-ID": request_id}
        try:
            with self.client.request(method, path, name=step+" "+route_name(path), headers=headers,
                                     timeout=800, catch_response=True, **kwargs) as response:
                status = response.status_code
                request_id = response.headers.get("X-Request-ID", request_id)
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                if not 200 <= status < 300:
                    detail = data.get("error", {}) if isinstance(data, dict) else {}
                    code, message = detail.get("code", "http_"+str(status)), detail.get("message", "HTTP "+str(status))
                    response.failure(code)
                    raise JourneyError(code, message, step)
                response.success()
                return data
        except Exception as exc:
            outcome = "error"
            code = code or getattr(exc, "code", "transport_error")
            message = message or str(exc)[:1000]
            if isinstance(exc, JourneyError):
                raise
            raise JourneyError(code, message, step) from exc
        finally:
            append(RUN/"steps.jsonl", {"start": start, "end": timestamp(), "duration_ms": (time.monotonic()-clock)*1000,
                "step": step, "route": route_name(path), "method": method, "status": status,
                "outcome": outcome, "error_code": code, "message": message, "request_id": request_id,
                "user_id": self.user_id, "username": self.account["username"], "session_id": self.journey.session_id if hasattr(self, "journey") else None,
                "question_instance_id": self.state.get("question_instance_id"), "question_id": self.state.get("question_id"),
                "turn_id": self.state.get("turn_id"), "workflow_id": self.state.get("workflow_id")})

    @task
    def question(self):
        global DONE
        if CONFIG["test"] == "benchmark":
            if self.question_index >= len(QUESTIONS)*REPETITIONS:
                DONE = True
                raise StopUser()
            question = QUESTIONS[self.question_index // REPETITIONS]
        else:
            question = self.random.choices(QUESTIONS, weights=[q["weight"] for q in QUESTIONS])[0]
        self.state = {"question_instance_id": str(uuid4()), "question_id": question["id"], "start": timestamp(),
                      "user_id": self.user_id, "username": self.account["username"], "outcome": "success", "wrong_operation": None,
                      "users": self.environment.runner.user_count}
        try:
            if self.in_session == 0:
                dataset = self.journey.start_session(CONFIG)
                append(RUN/"datasets.jsonl", {"ts": timestamp(), "user_id": self.user_id, **dataset})
            self.state["session_id"] = self.journey.session_id
            # Dataset preparation is a separate user step, outside answer time.
            self.state["question_sent_at"] = timestamp()
            self.journey.ask(question, self.state, spawn=gevent.spawn)
        except JourneyError as exc:
            self.state.update(outcome="error", error_code=exc.code, error_step=exc.step, message=str(exc)[:1000])
        except BaseException as exc:
            self.state.update(outcome="interrupted", error_code=type(exc).__name__, error_step="question", message=str(exc)[:1000])
            raise
        finally:
            self.state["end"] = timestamp()
            append(RUN/"questions.jsonl", self.state)
            self.question_index += 1
            self.in_session = (self.in_session+1) % 3

    def wait_time(self):
        return 0 if CONFIG["test"] == "benchmark" else self.random.uniform(20, 60)

    def on_stop(self):
        if hasattr(self, "account"):
            ACCOUNTS.put(self.account)


class GraphMineShape(LoadTestShape):
    def __init__(self):
        super().__init__()
        self.bad_since = None

    def tick(self):
        elapsed, kind = self.get_run_time(), CONFIG["test"]
        users = self.get_current_user_count()
        append(RUN/"shape.jsonl", {"ts": timestamp(), "elapsed_seconds": elapsed, "users": users})
        if kind == "benchmark":
            return None if DONE else (1, 1)
        durations = {"load": 1200, "spike": 600, "soak": 7200, "stress": 3000}
        if elapsed >= CONFIG.get("duration_seconds", durations[kind]):
            return None
        if kind == "load":
            return 10, 10/60
        if kind == "spike":
            return 20, 2
        if kind == "soak":
            return 5, 1
        recent = [r for r in read_jsonl(RUN/"questions.jsonl") if seconds(r["end"]) >= time.time()-60]
        rate = sum(r["outcome"] != "success" for r in recent)/len(recent) if recent else None
        if rate is not None and rate > .2:
            self.bad_since = self.bad_since if self.bad_since is not None else elapsed
            if elapsed-self.bad_since >= 120:
                append(RUN/"run-events.jsonl", {"ts": timestamp(), "event": "breaking_point", "users": users,
                    "error_rate": rate, "sustained_seconds": elapsed-self.bad_since})
                return None
        else:
            self.bad_since = None
        return min(50, 5+5*int(elapsed//300)), 1


@events.test_stop.add_listener
def stopped(environment, **kwargs):
    append(RUN/"run-events.jsonl", {"ts": timestamp(), "event": "load_generation_stopped", "benchmark_complete": DONE})
