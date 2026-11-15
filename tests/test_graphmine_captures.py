"""GraphMine conversations in the studio: own account only, exact inputs, reviewed targets."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import studio
from graphmine_agent.accounts import password_hash
from graphmine_agent.analytics_answers import choice_schema
from graphmine_agent.analytics_planning import generation_plan_schema, plan_schema, route_schema
from graphmine_agent.capture import TrainingCapture
from studio_auth import Auth, AuthError
from studio_captures import GraphMineAccounts, dataset_key

REPO = Path(__file__).resolve().parents[2] / "graphMine-database-cypher"
PASSWORD = "graphmine-password"
CARDS = [{"id": "k-core", "parameters": {"requested_k": {"kind": "integer"}}, "output_ports": {"count": {"type": "scalar"}}}]
FACTS = [{"id": "f1", "statement": "The core has four members."}]
ROUTE = {"intent": "calculate", "operations": ["k-core"], "message": "Find the core."}
PLAN = {"status": "ready", "message": "Find the core.", "plan": {"version": 1, "device": "cpu", "steps": [
    {"operation": "k-core", "input": {"source": "input", "input": "main"},
     "arguments": [{"name": "requested_k", "value": {"literal": 2}}]}]}}
ANSWER = {"lead": "Here is the tightest core.", "fact_ids": ["f1"]}


def call(capture, session, turn, stage, output, schema, decoded=None, question="Who is in the core?"):
    request = {"model": "planner", "messages": [
        {"role": "system", "content": f"SYSTEM {stage}"},
        {"role": "user", "content": json.dumps({"stage": stage, "question": question})}],
        "response_format": {"type": "json_schema", "json_schema": {"name": stage, "strict": True, "schema": schema}}}
    response = {"choices": [{"message": {"content": json.dumps(output), "reasoning": f"{stage} reasoning"}}]}
    capture.model_call(session, stage=stage, request=request, response=response, output=output, outcome="ok",
                       seconds=1.0, turn_id=turn, target_schema=schema, output_schema=decoded or schema)


def ask(capture, session, turn, question="Who is in the core?"):
    capture.record(session, "workflow.chat", {"turn_id": turn, "role": "user", "message": question,
                                              "inputs": {"main": {"file_id": "file_1", "kind": "graph"}}}, turn_id=turn)


def feedback(capture, session, turn, **values):
    capture.record(session, "feedback.saved", {"id": f"feedback_{len(values)}", "source": "user", **values}, turn_id=turn)


@pytest.fixture
def graphmine(tmp_path):
    store = tmp_path / "graphmine"
    store.mkdir()
    with closing(sqlite3.connect(store / "agent.sqlite3")) as db, db:
        db.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                   "password_hash TEXT NOT NULL, created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0)")
        for account, name, disabled in (("acct_ana", "ana", 0), ("acct_ben", "ben", 0), ("acct_cy", "cy", 1)):
            db.execute("INSERT INTO accounts VALUES (?,?,?,0,?)", (account, name, password_hash(PASSWORD), disabled))
    owners = {"s_ana": {"id": "acct_ana", "username": "ana"}, "s_ben": {"id": "acct_ben", "username": "ben"}}
    capture = TrainingCapture(store / "captures", owner_of=owners.get)
    ask(capture, "s_ana", "t1")
    capture.record("s_ana", "dataset.used", {"file_id": "file_1", "sha256": "d" * 64, "name": "team.json"})
    call(capture, "s_ana", "t1", "route", ROUTE, route_schema(CARDS))
    decoded = plan_schema(CARDS, ["main"], "cpu")
    call(capture, "s_ana", "t1", "plan", PLAN, generation_plan_schema(decoded), decoded)
    capture.record("s_ana", "workflow.answer", {"turn_id": "t1", "lead": ANSWER["lead"], "fact_ids": ["f1"],
                                                "facts": FACTS, "source": "model"}, turn_id="t1")
    call(capture, "s_ana", "t1", "answer", ANSWER, choice_schema(FACTS))
    feedback(capture, "s_ana", "t1", category="correction", what_went_wrong="Use k = 3.",
             expected_behavior="The 3-core.")
    ask(capture, "s_ben", "t9", "Ben's private question")
    call(capture, "s_ben", "t9", "route", ROUTE, route_schema(CARDS), question="Ben's private question")
    return GraphMineAccounts(store), capture


@pytest.fixture
def mine(tmp_path, graphmine):
    accounts, _capture = graphmine
    data = tmp_path / "data"
    data.mkdir()
    app = studio.Studio(data, tmp_path / "workspace", studio.Catalog(REPO), studio.Schemas(REPO / "agent"),
                        graphmine=accounts)
    studio.ACTOR.name = "ana"
    key = app.sync_captures({"id": "acct_ana", "username": "ana"})
    yield app, key
    studio.ACTOR.name = None


def by_stage(store):
    return {ex["capture"]["stage"]: ex for ex in store.all_effective()}


def revisions(store):
    return {e["id"]: e["revision"] for e in store.all_effective()}


def test_graphmine_sign_in_links_the_account_and_never_takes_over_a_studio_account(tmp_path, graphmine):
    accounts, _ = graphmine
    auth = Auth(tmp_path / "auth", graphmine=accounts)
    auth.create_user("ben", "studio-only-password", role="admin")
    assert auth.login("ana", PASSWORD)
    assert auth.users["ana"]["graphmine"] == {"id": "acct_ana", "username": "ana"}
    assert auth.users["ana"]["password"] is None
    with pytest.raises(AuthError):
        auth.login("ana", "wrong password")
    # A GraphMine password never signs in to a studio account of the same name.
    with pytest.raises(AuthError):
        auth.login("ben", PASSWORD)
    auth.login("ben", "studio-only-password")
    assert "graphmine" not in auth.users["ben"]
    with pytest.raises(AuthError):
        auth.login("cy", PASSWORD)  # disabled in GraphMine
    # No studio password can be set, so nobody else can sign in as ana.
    with pytest.raises(AuthError):
        auth.update_user("ana", password="admin-chosen-password")
    with pytest.raises(AuthError):
        auth.change_password("ana", PASSWORD, "another-password")


def test_each_account_sees_only_its_own_conversations_admins_included(tmp_path, graphmine):
    accounts, _ = graphmine
    auth = Auth(tmp_path / "auth", graphmine=accounts)
    auth.create_user("root", "studio-admin-password", role="admin")
    auth.login("ana", PASSWORD)
    auth.login("ben", PASSWORD)
    ana, ben = dataset_key("acct_ana"), dataset_key("acct_ben")
    assert auth.can_access("ana", ana) and not auth.can_access("ana", ben)
    assert auth.can_access("ben", ben) and not auth.can_access("ben", ana)
    assert not auth.can_access("root", ana)
    auth.grant("ben", ana)
    auth.update_user("ben", datasets=[ana])
    assert not auth.can_access("ben", ana)
    with closing(sqlite3.connect(accounts.database)) as db, db:
        db.execute("UPDATE accounts SET disabled=1 WHERE id='acct_ana'")
    assert not auth.can_access("ana", ana)


def test_each_model_call_is_a_row_with_its_exact_input_and_the_feedback(mine):
    app, key = mine
    store = app.store_for(key)
    rows = by_stage(store)
    assert {stage: (ex["schema"], ex["adapter"]) for stage, ex in rows.items()} == {
        "route": ("AnalyticsRoute", "planner"), "plan": ("AnalyticsPlan", "planner"),
        "answer": ("AnalyticsAnswer", "analyst")}
    assert {ex["group"] for ex in rows.values()} == {"t1"}
    assert rows["plan"]["output"] == PLAN and rows["plan"]["prompts"][0]["value"] == "Who is in the core?"
    assert store.context(rows["plan"]["id"])["system"] == "SYSTEM plan"
    capture = rows["answer"]["capture"]
    assert capture["feedback"][0]["expected_behavior"] == "The 3-core."
    assert capture["answer"]["lead"] == ANSWER["lead"] and capture["dataset"]["name"] == "team.json"
    assert capture["reasoning"] == "answer reasoning"
    assert not [i for ex in rows.values() for i in ex["issues"] if i["level"] == "error"]
    for folder in (app.workspace / key, app.workspace / "graphmine-captures" / key):
        assert folder.stat().st_mode & 0o077 == 0
    # Ben's question never reaches ana's dataset.
    assert "Ben's private question" not in json.dumps(store.all_effective())


def test_edits_are_checked_as_graphmine_checks_the_model_and_later_steps_are_held_back(mine, tmp_path):
    app, key = mine
    store = app.store_for(key)
    rows = by_stage(store)
    invented = json.loads(json.dumps(PLAN))
    invented["plan"]["steps"][0]["operation"] = "made-up-operation"
    result = store.update(rows["plan"]["id"], {"output": invented}, rows["plan"]["revision"])
    rejected = [i["message"] for i in result["example"]["issues"] if "GraphMine would reject" in i["message"]]
    # The reason names the wrong field, not the whole plan.
    assert rejected and "'k-core' was expected (at plan/steps/0/operation)" in rejected[0]
    corrected = json.loads(json.dumps(PLAN))
    corrected["plan"]["steps"][0]["arguments"][0]["value"]["literal"] = 3
    plan = store.update(rows["plan"]["id"], {"output": corrected}, store.effective(rows["plan"]["id"])["revision"])
    assert not [i for i in plan["example"]["issues"] if i["level"] == "error"]
    rows = by_stage(store)
    # The answer was written from facts of the original plan's result.
    assert any("earlier step" in i["message"] for i in rows["answer"]["issues"])
    assert not [i for i in rows["route"]["issues"] if i["level"] == "error"]
    for stage in ("route", "plan", "answer"):
        ex = store.effective(rows[stage]["id"])
        store.update(ex["id"], {"review": "approved"}, ex["revision"])
    exported = store.export("reviewed", expected_revisions=revisions(store))
    assert exported["counts"]["skipped_invalid"] == 1
    planner = [json.loads(line) for line in (Path(exported["path"]) / "sft/planner/train.jsonl").read_text().splitlines()]
    trained = next(row for row in planner if row["messages"][0]["content"] == "SYSTEM plan")["messages"]
    assert json.loads(trained[1]["content"]) == {"stage": "plan", "question": "Who is in the core?"}
    assert json.loads(trained[2]["content"]) == corrected


def test_new_questions_and_late_feedback_arrive_without_losing_edits(mine, graphmine):
    app, key = mine
    _, capture = graphmine
    store = app.store_for(key)
    route = by_stage(store)["route"]
    store.update(route["id"], {"notes": "checked"}, route["revision"])
    feedback(capture, "s_ana", "t1", category="rating", rating=2, what_went_wrong="Slow.")
    ask(capture, "s_ana", "t2", "And the second core?")
    call(capture, "s_ana", "t2", "route", ROUTE, route_schema(CARDS), question="And the second core?")
    app.sync_captures({"id": "acct_ana", "username": "ana"})
    fresh = app.store_for(key)
    assert fresh is not store and len(fresh.order) == 4
    assert fresh.effective(route["id"])["notes"] == "checked"
    assert len(fresh.effective(route["id"])["capture"]["feedback"]) == 2
    # Rows indexed before the sync still read their own messages.
    assert fresh.context(route["id"])["system"] == "SYSTEM route"
    assert store.context(route["id"])["system"] == "SYSTEM route"
