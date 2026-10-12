import json

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.catalog_reference import reference_for_case
from graphmine_agent.learning.catalog_suite import digest
from graphmine_agent.learning.data_selection import VERSION as SELECTION_VERSION
from graphmine_agent.learning.dual_corpus import graph_from_pairs
from graphmine_agent.learning.dual_recovery import recovery_cases
from graphmine_agent.learning.reusable_data import package, verify_package
from graphmine_agent.models import ApplicationIntent, RouteDecision


def test_recovery_selection_accepts_new_corpus_ids_but_rejects_test_or_changed_cases():
    cases = [
        {
            "id": "full-" + split,
            "split": split,
            "task": {"operation_id": "k-cliques", "expected_status": "ready"},
        }
        for split in ("train", "validation", "test")
    ]
    corpus = {"cases": cases}
    assert recovery_cases(corpus, cases[:2]) == cases[:2]
    with pytest.raises(ValueError, match="contamination"):
        recovery_cases(corpus, cases)
    altered = {**cases[0], "split": "validation"}
    with pytest.raises(ValueError, match="selection"):
        recovery_cases(corpus, [altered])
    with pytest.raises(ValueError, match="selection"):
        recovery_cases(corpus, [cases[0], cases[0]])


def test_larger_core_and_components_have_known_answers_and_keep_exhaustive_guard():
    pairs = [(i, (i + 1) % 100) for i in range(100)]
    graph = graph_from_pairs("ring-and-isolates", pairs, ids=list(range(111)))
    case = {
        "graph": graph,
        "attachments": {},
        "task": {
            "operation_id": "k-core",
            "expected_status": "ready",
            "parameters": {"requested_k": 2},
            "intent": ApplicationIntent().model_dump(mode="json"),
        },
    }
    assert reference_for_case(case)["expected"]["vertices"] == list(range(100))
    case["task"].update(
        operation_id="connected-components",
        parameters={"connectivity_mode": "weakly_connected"},
    )
    assert sorted(map(len, reference_for_case(case)["expected"]["groups"])) == [
        1
    ] * 11 + [100]
    case["task"].update(operation_id="k-cliques", parameters={"k": 3})
    with pytest.raises(ValueError, match="limited to 8"):
        reference_for_case(case)


def teacher_fixture(root):
    for directory in ("teacher-inputs", "teacher-targets"):
        (root / directory).mkdir(parents=True)
    corpus = {
        "source_registry": {},
        "cases": [
            {"id": "source-a", "lineage": "source:a", "split": "train"},
            {"id": "source-b", "lineage": "source:b", "split": "validation"},
            {"id": "source-c", "lineage": "source:c", "split": "test"},
        ],
    }
    (root / "corpus.json").write_text(json.dumps(corpus))
    for index, split in enumerate(("train", "validation")):
        identifier = f"row-{index}"
        target = RouteDecision(
            supported=False,
            confidence=1,
            explanation="Clarify the intended objective.",
            ambiguity=["Which relationship question should I answer?"],
        ).model_dump(mode="json")
        job = {
            "id": identifier,
            "case_id": "source-" + "ab"[index],
            "case_sha256": "reference",
            "split": split,
            "lineage": "source:" + "ab"[index],
            "adapter": "planner",
            "schema": "RouteDecision",
            "messages": [
                {"role": "system", "content": "Route the question."},
                {"role": "user", "content": "Help me."},
            ],
            "output_schema": RouteDecision.model_json_schema(),
            "user_payload": {},
            "conversation": [],
            "reference_contract": {
                "expected_status": "needs_information",
                "problem_id": None,
            },
        }
        job["sha256"] = digest(job)
        events = [
            {"type": "thread.started"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(target)},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        ]
        artifact = {
            "input_sha256": job["sha256"],
            "profile": {
                "provider": "codex",
                "model": "fixture",
                "reasoning_effort": "max",
                "max_output_tokens": 1000,
            },
            "codex_cli": {"reasoning_effort": "max", "exit_code": 0},
            "status": "accepted",
            "target": target,
            "raw_response": "\n".join(map(json.dumps, events)),
        }
        (root / "teacher-inputs" / (identifier + ".json")).write_text(json.dumps(job))
        (root / "teacher-targets" / (identifier + ".json")).write_text(
            json.dumps(artifact)
        )


def test_portable_export_retains_rejected_teacher_output_and_excludes_it_from_sft(
    settings, tmp_path
):
    root = tmp_path / "run"
    teacher_fixture(root)
    path = root / "teacher-targets/row-1.json"
    artifact = json.loads(path.read_text())
    artifact["target"]["explanation"] = (
        "An altered answer, different from the actual response."
    )
    path.write_text(json.dumps(artifact))
    output = tmp_path / "portable"
    manifest = package(settings, root, output, require_complete=True)
    assert manifest["counts"]["accepted"] == 1
    assert manifest["counts"]["quarantined"] == 1
    assert not (output / "sft/planner/validation.jsonl").exists()
    assert len((output / "teacher-responses.jsonl").read_text().splitlines()) == 2
    assert verify_package(output)["complete"]
    (output / "sft/planner/train.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="changed"):
        verify_package(output)


def test_export_rejects_held_out_inputs_before_training(settings, tmp_path):
    root = tmp_path / "run"
    teacher_fixture(root)
    path = root / "teacher-inputs/row-0.json"
    job = json.loads(path.read_text())
    job.update(split="test", lineage="source:c")
    job.pop("sha256")
    job["sha256"] = digest(job)
    path.write_text(json.dumps(job))
    with pytest.raises(ValueError, match="Held-out"):
        package(settings, root, tmp_path / "portable", require_complete=True)


def test_incomplete_teacher_queue_cannot_be_marked_complete(settings, tmp_path):
    root = tmp_path / "run"
    teacher_fixture(root)
    (root / "teacher-targets/row-1.json").unlink()
    with pytest.raises(ValueError, match="not finished"):
        package(settings, root, tmp_path / "portable", require_complete=True)
    assert not (tmp_path / "portable").exists()


def write_selection(root, identifiers, holdout=()):
    records = {}
    for identifier in identifiers:
        job = json.loads((root / "teacher-inputs" / (identifier + ".json")).read_text())
        target = root / "teacher-targets" / (identifier + ".json")
        records[identifier] = {
            "input_sha256": job["sha256"],
            "teacher_sha256": HistoryStore.digest(target),
            "original_status": json.loads(target.read_text())["status"],
        }
    selection = {
        "version": SELECTION_VERSION,
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
        "holdout_lineages": list(holdout),
        "records": records,
    }
    (root / "current-run-selection.json").write_text(json.dumps(selection))


def test_limited_collection_keeps_deferred_requests_and_original_split_evidence(
    settings, tmp_path
):
    root = tmp_path / "run"
    teacher_fixture(root)
    (root / "teacher-targets/row-1.json").unlink()
    original = (root / "teacher-targets/row-0.json").read_bytes()
    write_selection(root, ["row-0"], holdout=["source:a"])
    output = tmp_path / "portable"
    report = package(settings, root, output, require_complete=True)
    assert report["complete"] and not report["original_collection_complete"]
    assert report["deferred_teacher_calls"] == ["row-1.json"]
    assert report["counts"]["sft/planner/validation.jsonl"] == 1
    assert not (output / "sft/planner/train.jsonl").exists()
    response = json.loads((output / "teacher-responses.jsonl").read_text())
    assert response["split"] == "train" and response["training_split"] == "validation"
    assert (root / "teacher-targets/row-0.json").read_bytes() == original
    assert json.loads((output / "deferred-inputs.jsonl").read_text())["id"] == "row-1"


def test_data_only_review_queue_is_not_silently_promoted_to_training(
    settings, tmp_path
):
    root = tmp_path / "run"
    teacher_fixture(root)
    path = root / "teacher-targets/row-0.json"
    record = json.loads(path.read_text())
    record["status"] = "quarantined"
    path.write_text(json.dumps(record))
    write_selection(root, ["row-0", "row-1"])
    output = tmp_path / "portable"
    report = package(settings, root, output, require_complete=True)
    assert report["counts"]["quarantined"] == 1
    assert not (output / "sft/planner/train.jsonl").exists()
    queued = json.loads((output / "review-later.jsonl").read_text())
    assert queued["id"] == "row-0" and queued["response_text"]


def test_collection_selection_rejects_changed_responses_and_invalid_holdouts(
    settings, tmp_path
):
    root = tmp_path / "run"
    teacher_fixture(root)
    write_selection(root, ["row-0", "row-1"], holdout=["source:b"])
    with pytest.raises(ValueError, match="training source"):
        package(settings, root, tmp_path / "bad-holdout", require_complete=True)
    write_selection(root, ["row-0", "row-1"])
    path = root / "teacher-targets/row-0.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="binding changed"):
        package(settings, root, tmp_path / "changed", require_complete=True)


def test_data_only_policy_blocks_training_before_any_external_process(tmp_path):
    from graphmine_agent.learning.full_train import run

    (tmp_path / "collection-policy.json").write_text(
        json.dumps({"mode": "data_only", "automatic_training": False})
    )
    with pytest.raises(RuntimeError, match="Training is disabled"):
        run(tmp_path, "not-a-real-unit")


def test_planner_collection_stops_at_target_and_never_retries_review_queue(tmp_path):
    from graphmine_agent.learning.collection_only import STAGES, next_batch

    (tmp_path / "teacher-targets").mkdir()
    jobs = [
        {
            "id": "review-later",
            "split": "train",
            "lineage": "source:a",
            "schema": "PlanDraft",
        },
        {
            "id": "whole-family-holdout",
            "split": "train",
            "lineage": "source:holdout",
            "schema": "RouteDecision",
        },
        {
            "id": "next-planner",
            "split": "train",
            "lineage": "source:a",
            "schema": "TurnDecision",
        },
    ]
    (tmp_path / "teacher-targets/review-later.json").write_text(
        '{"status":"quarantined"}'
    )
    policy = {
        "holdout_lineages": ["source:holdout"],
        "planner_accepted_targets": {"train": 1000, "validation": 100},
    }
    stages = {"train": sorted(STAGES), "validation": sorted(STAGES)}
    assert (
        next_batch(tmp_path, jobs, policy, {"train": 1000, "validation": 100}, stages)
        is None
    )
    assert next_batch(
        tmp_path, jobs, policy, {"train": 999, "validation": 100}, stages
    ) == ("train", 2, 1)
    stages["train"] = ["PlanDraft", "RouteDecision"]
    assert next_batch(
        tmp_path, jobs, policy, {"train": 1000, "validation": 100}, stages
    ) == ("train", 2, 1)


@pytest.mark.parametrize("tamper", [False, True])
def test_portable_questions_preserve_exact_teacher_response_and_derivative_sources(
    settings, tmp_path, tamper
):
    root = tmp_path / "run"
    teacher_fixture(root)
    corpus = json.loads((root / "corpus.json").read_text())
    source = corpus["cases"][0]
    source["sha256"] = digest(source)
    (root / "corpus.json").write_text(json.dumps(corpus))
    derivative = {**source, "id": "source-a-business-clear"}
    derivative.pop("sha256")
    derivative["sha256"] = digest(derivative)
    (root / "question-input-manifest.json").write_text(
        json.dumps({"additional_scenarios": [derivative]})
    )
    proposal = {
        "case_id": "source-a",
        "clear_question": "Which records link the most separate groups?",
        "ambiguous_question": "Which records matter most?",
        "clarification_question": "Do you mean records that connect separate groups?",
        "clarified_reply": "Yes, find the records connecting separate groups.",
        "preserved_requirements": ["Use the supplied source records."],
    }
    parsed = {"questions": [proposal]}
    artifact = json.loads((root / "teacher-targets/row-0.json").read_text())
    events = [json.loads(line) for line in artifact["raw_response"].splitlines()]
    events[2]["item"]["text"] = json.dumps(parsed)
    artifact.update(
        status="completed",
        parsed=parsed,
        raw_response="\n".join(map(json.dumps, events)),
        request={
            "instructions": "Generate questions from the supplied scenarios.",
            "input": {"scenarios": [{"case_id": "source-a"}]},
            "output_schema": {},
        },
    )
    if tamper:
        artifact["parsed"]["questions"][0]["clear_question"] = (
            "A different stored question."
        )
    (root / "business-question-teacher.json").write_text(json.dumps(artifact))
    destination = tmp_path / "portable"
    if tamper:
        with pytest.raises(ValueError, match="actual teacher response"):
            package(settings, root, destination, require_complete=True)
        assert not destination.exists()
    else:
        result = package(settings, root, destination, require_complete=True)
        assert result["counts"]["question-proposals.jsonl"] == 1
        assert result["scenarios"] == 4
        original = json.loads(
            (destination / "question-teacher-responses.jsonl").read_text()
        )
        assert json.loads(original["response_text"])["questions"] == [proposal]
        assert "raw_response" not in original
        preserved = [
            json.loads(line)
            for line in (destination / "cases.jsonl").read_text().splitlines()
        ]
        assert derivative in preserved
