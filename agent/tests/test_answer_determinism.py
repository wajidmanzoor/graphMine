"""Saved computed facts must survive a restart with a different hash seed."""

import json
import os
import subprocess
import sys

from graphmine_agent.learning.catalog_suite import build_suite
from graphmine_agent.models import ExecutionPlan
from test_catalog_grade import authored_output


def test_group_attribute_facts_are_identical_across_process_hash_seeds(catalog):
    case = next(
        case
        for case in build_suite(catalog)["cases"]
        if case["id"] == "maximal-bicliques--supported"
    )
    task = case["task"]
    plan = ExecutionPlan(
        session_id="fixture",
        graph_id="fixture",
        problem_id=task["problem_id"],
        operation_id=task["operation_id"],
        parameters=task["parameters"],
        application_intent=task["intent"],
    )
    payload = json.dumps(
        {
            "graph": case["graph"],
            "plan": plan.model_dump(mode="json"),
            "payload": {"output": authored_output(case)},
        }
    )
    program = """
import json, sys
from graphmine_agent.answers import build_answer
from graphmine_agent.models import ExecutionPlan
data = json.load(sys.stdin)
answer = build_answer(data['graph'], ExecutionPlan.model_validate(data['plan']), data['payload'], source_hash='fixture')
print(json.dumps(answer, sort_keys=True))
"""
    answers = [
        subprocess.run(
            [sys.executable, "-c", program],
            input=payload,
            capture_output=True,
            text=True,
            check=True,
            env=dict(os.environ, PYTHONHASHSEED=str(seed)),
        ).stdout
        for seed in range(6)
    ]
    assert len(set(answers)) == 1, (
        "Computed group attributes/facts changed across process restarts"
    )
