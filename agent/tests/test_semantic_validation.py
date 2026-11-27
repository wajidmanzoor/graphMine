"""The semantic trust boundary includes expressions embedded inside prompts."""

import pytest

from graphmine_agent.errors import AnalyticsError
from graphmine_agent.semantic_validation import validate_semantic
from graphmine_agent.semantic_worker import check_request


@pytest.mark.parametrize("statement", [
    "MATCH (n:Vertex) WHERE has_label(n,'Review') RETURN n;",
    "// DELETE is a comment\nRETURN 'CALL; CREATE' AS text /* SET */",
    "MATCH (n) RETURN n.`SET`, n.create, $delete, {load: 'x'} AS m",
    "MATCH (n) WITH n AS create RETURN create.name",
    "RETURN {NODE: 'scalar', nested: {name: 'REL'}} AS value",
    "UNWIND range(1,3) AS x RETURN count(*) AS total",
    "MATCH (n) WHERE EXISTS { MATCH (m) WHERE m.name=n.name RETURN m } RETURN n",
])
def test_reads_do_not_confuse_data_with_commands(statement):
    assert validate_semantic(statement) == []


@pytest.mark.parametrize("statement", [
    "MATCH(n) SET n.x=1 RETURN n", "MATCH(n) DETACH DELETE n", "CREATE(n)",
    "MATCH(n) RETURN n; RETURN 2", "RETURN 1;;", "CALL db.labels() RETURN *",
    "EXPLAIN RETURN 1", "PROFILE RETURN 1", "COPY Vertex FROM '/tmp/file'",
    "INSTALL json", "LOAD EXTENSION json", "ATTACH '/tmp/db' AS other",
    "RETURN read_file('/etc/passwd')", "RETURN _llm_call('x','y',1)",
    "RETURN llm_generate('mock','x')", "RETURN llm_build_graph('mock','x')",
    "RETURN `read_file`('/etc/passwd')", "RETURN 'unclosed", "RETURN 1 /* unfinished",
    "RETURN (1]", "RETURN llm($model, 'x')", "RETURN llm('mock',$prompt)",
    "RETURN llm('http://localhost:9999', 'x')", "RETURN llm('openai/gpt-x', 'x')",
    "RETURN llm('mock','read {{n.path, IMAGE}} {answer STRING}')",
    "RETURN llm('mock','read {{n.path, inc, image}} {answer STRING}')",
    r"RETURN llm('mock','read {{n.path, \u0049MAGE}} {answer STRING}')",
    "RETURN llm('mock', \"{{llm('qwen','private')}} {answer STRING}\")",
    "RETURN llm('mock', \"{{read_file('/etc/passwd')}} {answer STRING}\")",
    "RETURN llm('mock','{{n; CALL something()}} {answer STRING}')",
])
def test_writes_external_access_and_unapproved_models_are_rejected(statement):
    with pytest.raises(AnalyticsError) as error:
        validate_semantic(statement)
    assert error.value.code == "semantic_read_only"


@pytest.mark.parametrize("expression,kind", [
    ("llm('mock','{{n.name}} {answer STRING}')", "llm"),
    ("llm_score('mock','Rate {{n.name}}', 0, 5)", "llm_score"),
    ("llm_agg(n.name,'mock','{answer STRING}')", "llm_agg"),
    ("llm_path_agg(p,'mock','{answer STRING}')", "llm_path_agg"),
    ("llm_sg_agg(n,r,'mock','{answer STRING}')", "llm_sg_agg"),
    ("llm_sg_agg(n,'mock','{answer STRING}', ['name'])", "llm_sg_agg"),
])
def test_operator_signatures_record_model_prompt_and_outputs(expression, kind):
    step, = validate_semantic("RETURN " + expression + " AS answer")
    assert step["kind"] == kind and step["model_alias"] == "mock"
    assert step["outputs"][0]["type"] in {"STRING", "INT64"}


def test_prompt_inputs_preserve_nested_braces_and_escaped_quotes():
    steps = validate_semantic('RETURN llm("mock", "Use {{ {text: \'a}b\', image: n.image} }} {answer STRUCT(name STRING, age INT64)[]}") AS answer')
    assert steps[0]["inputs"] == [" {text: 'a}b', image: n.image} "]
    assert steps[0]["outputs"] == [{"name": "answer", "type": "STRUCT(name STRING, age INT64)[]"}]


@pytest.mark.parametrize("body,code", [
    ({"statement": "RETURN llm('qwen', '{answer STRING}')", "model": "qwen"}, "semantic_controls_unsupported"),
    ({"statement": "RETURN llm('qwen', '{answer STRING}')", "model": "mock"}, "semantic_controls_unsupported"),
    ({"statement": "RETURN llm('mock', '{answer STRING}')", "model": "qwen"}, "semantic_controls_unsupported"),
    ({"statement": "RETURN 1", "reuse_answers": True}, "semantic_controls_unsupported"),
])
def test_live_and_cache_gates_fail_before_any_worker_is_created(body, code, monkeypatch):
    from graphmine_agent import semantic_engine
    lock = {**semantic_engine.engine_lock(), "live_blockers": ["strict_json_without_fallback"]}
    monkeypatch.setattr(semantic_engine, "engine_lock", lambda: lock)
    with pytest.raises(AnalyticsError) as error:
        check_request(body)
    assert error.value.code == code and error.value.status == 503


def test_plain_reads_need_no_provider_and_mock_is_explicit():
    assert check_request({"statement": "RETURN 1", "model": "qwen"}) == []
    assert check_request({"statement": "RETURN llm('mock:echo','{answer STRING}')", "model": "mock"})
