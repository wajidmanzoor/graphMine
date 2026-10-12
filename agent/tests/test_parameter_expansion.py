"""Boundaries shared by planner schemas and the extended native paths."""
import copy

import pytest

from graphmine_agent.llm import constrain_plan_schema
from graphmine_agent.models import ExecutionPlan, PlanDraft
from graphmine_agent.planning import PlanValidationError, PlanValidator


def plan(catalog, operation, backend, parameters):
    return ExecutionPlan(session_id="test", graph_id="g", operation_id=operation,
                         problem_id=catalog.operation(operation).problem_id,
                         backend_id=backend, parameters=parameters)


@pytest.mark.parametrize("operation,backend,parameters", [
    ("k-cliques", "kcgpu", {"k": 11}),
    ("k-cliques", "gamma", {"k": 8}),
    ("k-cliques", "graphset", {"k": 7}),
    ("k-cliques", "auto", {"k": 11}),
    ("k-cliques", "auto", {"k": "seven"}),
    ("triangle-counting", "wetric", {"wetric_adjacency_matrix_length": 96}),
    ("triangle-counting", "wetric", {"wetric_spread": 48}),
    ("subgraph-isomorphism", "gmatch", {"initial_match_capacity": 2**31}),
    ("community-detection", "gleiden", {"resolution": 2}),
    ("community-detection", "auto", {"resolution": -1}),
    ("densest-subgraph", "cds", {"clique_order": 1}),
    ("densest-subgraph", "cds", {"clique_order": 2**31}),
])
def test_reject_before_execution(catalog, operation, backend, parameters):
    with pytest.raises(PlanValidationError):
        PlanValidator(catalog).validate(plan(catalog, operation, backend, parameters))


@pytest.mark.parametrize("operation,backend,parameters", [
    ("k-cliques", "kcgpu", {"k": 10}),
    ("k-cliques", "gamma", {"k": 7}),
    ("k-cliques", "graphset", {"k": 6}),
    ("k-cliques", "auto", {"k": 10}),
    ("triangle-counting", "wetric", {"wetric_adjacency_matrix_length": 128}),
    ("triangle-counting", "wetric", {"wetric_spread": 47}),
    ("community-detection", "parallel-leiden", {"resolution": 2}),
    ("community-detection", "auto", {"resolution": 0}),
    ("densest-subgraph", "cds", {"clique_order": 7}),
])
def test_extended_parameters_are_accepted(catalog, operation, backend, parameters):
    PlanValidator(catalog).validate(plan(catalog, operation, backend, parameters))


def test_auto_requires_a_compatible_compiled_backend(catalog):
    with pytest.raises(PlanValidationError, match="No available backend"):
        PlanValidator(catalog).validate(plan(catalog,"k-cliques","auto",{"k":7}),
                                        compiled_backends={"graphset"})
    with pytest.raises(PlanValidationError, match="No available backend"):
        PlanValidator(catalog).validate(plan(catalog,"community-detection","auto",{"resolution":2}),
                                        compiled_backends={"gleiden"})


def test_generation_schema_hides_inapplicable_knobs(catalog):
    schema=copy.deepcopy(PlanDraft.model_json_schema())
    payload={"requested_backend":"tot", "operation_context":catalog.operation_context("triangle-counting")}
    constrain_plan_schema(schema,payload)
    parameters=schema["$defs"]["PlanConfiguration"]["properties"]["parameters"]["properties"]
    assert "wetric_spread" not in parameters
    assert "wetric_adjacency_matrix_length" not in parameters


@pytest.mark.parametrize("backend,maximum",[("kcgpu",10),("gamma",7),("graphset",6),("auto",10)])
def test_generation_schema_encodes_backend_order_limit(catalog,backend,maximum):
    schema=copy.deepcopy(PlanDraft.model_json_schema())
    constrain_plan_schema(schema,{"requested_backend":backend,"operation_context":catalog.operation_context("k-cliques")})
    parameters=schema["$defs"]["PlanConfiguration"]["properties"]["parameters"]["properties"]
    assert parameters["k"]["anyOf"][0]["maximum"]==maximum


@pytest.mark.parametrize("backend", ["cuda-ms", "maximum-clique-on-gpu"])
def test_generation_schema_excludes_unsupported_all_ties(catalog, backend):
    schema = copy.deepcopy(PlanDraft.model_json_schema())
    constrain_plan_schema(schema, {
        "requested_backend": backend,
        "operation_context": catalog.operation_context("maximum-clique"),
    })
    parameters = schema["$defs"]["PlanConfiguration"]["properties"]["parameters"]["properties"]
    assert parameters["return_all_ties"]["anyOf"][0]["enum"] == [False]
