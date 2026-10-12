"""Frozen end-to-end conversations with real model calls and native execution."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import statistics
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx

from ..analysis import (
    compile_vega,
    prepare_analysis,
    validate_statement,
    validate_vega_spec,
)
from ..answers import build_answer
from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..models import ExecutionPlan, GroundedStatement, PlanDraft, RouteDecision, utc_now
from ..terminal import ClientError, Terminal, agent_client
from .catalog_grade import grade_output
from .catalog_replay import FALLBACK_NOTICE, encoded, run_profile, source_bindings
from .dual_teacher import check_target

OPERATIONS = (
    "maximal-cliques",
    "k-cliques",
    "betweenness-centrality",
    "community-detection",
    "quasi-cliques",
    "max-flow-min-cut",
    "linear-assignment",
    "temporal-motif-mining",
    "subgraph-isomorphism",
)
FOLLOWUP = "Using only this result, make a custom comparison view with coordinated panels for group size and membership. Explain the main pattern and limitations."


def freeze(root, destination, split, *, operations=OPERATIONS):
    if destination.exists() or split not in {"validation", "test"}:
        raise ValueError("Choose a new held-out workflow manifest")
    cases = json.loads((root / "corpus.json").read_text())["cases"]
    eligible = [case for case in cases if case["split"] == split]
    selected = []
    for operation in operations:
        options = [
            case
            for case in eligible
            if case["task"]["operation_id"] == operation
            and case["task"]["expected_status"] == "ready"
        ]
        options.sort(
            key=lambda case: (not case["lineage"].startswith("source:"), case["id"])
        )
        selected.append(options[0])
    selected.extend(
        case for case in eligible if case["task"]["expected_status"] != "ready"
    )
    rows = [
        {
            "id": case["id"],
            "case_id": case["id"],
            "case_sha256": case["sha256"],
            "clarification_first": False,
            "chart_followup": case["task"]["operation_id"] == "maximal-cliques",
        }
        for case in selected
    ]
    clarified = next(
        case
        for case in selected
        if case["task"]["operation_id"] == "betweenness-centrality"
    )
    rows.append(
        {
            "id": clarified["id"] + "-clarification",
            "case_id": clarified["id"],
            "case_sha256": clarified["sha256"],
            "clarification_first": True,
            "chart_followup": False,
        }
    )
    recovery = next(
        case for case in selected if case["task"]["operation_id"] == "k-cliques"
    )
    rows.append(
        {
            "id": recovery["id"] + "-injected-recovery",
            "case_id": recovery["id"],
            "case_sha256": recovery["sha256"],
            "clarification_first": False,
            "chart_followup": False,
            "inject_invalid_first_draft": True,
        }
    )
    report = {
        "version": "dual-live-workflows-v1",
        "split": split,
        "rows": rows,
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
        "created_at": utc_now().isoformat(),
        "clarification_question": "Which records matter most in this dataset?",
        "chart_followup_question": FOLLOWUP,
        "selection": f"{len(operations)} operation families, preferring the held-out public source when available; all non-ready cases; one complete clarification, one custom-chart follow-up, and one explicitly injected invalid first draft to exercise bounded model recovery. Fixed before model execution.",
    }
    HistoryStore.write(destination, report)
    return {"workflows": len(rows), "split": split}


def presentation_issues(interpretation, answer):
    facts = {fact["id"]: fact for fact in answer["facts"]}
    for statement in interpretation.get("explanation", []):
        validate_statement(GroundedStatement.model_validate(statement), facts)
    if interpretation.get("limitations") != answer["limitations"]:
        raise ValueError("Displayed limitations changed")
    custom = 0
    for view in interpretation.get("visualizations", []):
        if view["type"] != "vega_lite":
            continue
        custom += 1
        if (
            not view.get("evidence_ids")
            or not set(view["evidence_ids"]) <= facts.keys()
        ):
            raise ValueError("Custom chart references unknown evidence")
        spec = copy.deepcopy(view["vega_lite"])
        bound = spec.pop("datasets", None)
        used = validate_vega_spec(spec, answer["analysis_datasets"])
        if bound != {name: answer["analysis_datasets"][name]["rows"] for name in used}:
            raise ValueError("Chart data changed from the computed result")
        compile_vega(view["vega_lite"])
    return custom


def custom_panel_count(interpretation):
    """Count explicit custom panels; layers within one plot remain one panel."""

    def count(spec):
        for key in ("hconcat", "vconcat", "concat"):
            if key in spec:
                return sum(count(child) for child in spec[key])
        # Facet counts depend on bound data; do not invent a static panel count.
        return 1

    return sum(
        count(view["vega_lite"])
        for view in interpretation.get("visualizations", [])
        if view["type"] == "vega_lite"
    )


def grade(settings, root, case, capture):
    dimensions = {}
    errors = {}

    def check(name, action):
        try:
            value = action()
            if value is False:
                raise ValueError("Check failed")
            dimensions[name] = True
            return value
        except (
            ValueError,
            RuntimeError,
            OSError,
            KeyError,
            TypeError,
            AssertionError,
        ) as error:
            dimensions[name] = False
            errors[name] = str(error)
            return None

    outcome = capture["outcome"]
    response = outcome.get("response", {})
    jobs = capture["jobs"]
    uploaded = capture["graph"]
    task = case["task"]
    check(
        "input_binding",
        lambda: (
            uploaded["sha256"] == hashlib.sha256(encoded(case["graph"])).hexdigest()
            and capture["query"] == task["question"]
        ),
    )
    check(
        "status",
        lambda: (
            not outcome.get("error")
            and response.get("planning_status") == task["expected_status"]
        ),
    )
    if capture.get("clarification"):
        first = capture["clarification"]
        check(
            "clarification",
            lambda: (
                first.get("response", {}).get("planning_status") == "needs_information"
                and not first.get("response", {}).get("plan")
                and capture["jobs_before_clarification_reply"] == []
            ),
        )
    if capture.get("recovery_required"):
        check(
            "bounded_recovery",
            lambda: (
                capture.get("injected_error") == "invalid_result_limit_zero"
                and capture.get("recovery_request_count") == 1
            ),
        )
    if task["expected_status"] != "ready":
        check(
            "no_unapproved_execution",
            lambda: not jobs and not outcome.get("result") and not response.get("plan"),
        )
        return {
            "passed": all(dimensions.values()),
            "dimensions": dimensions,
            "errors": errors,
        }
    check("execution", lambda: len(jobs) == 1 and jobs[0]["status"] == "completed")
    if not dimensions["execution"] or not outcome.get("result"):
        return {"passed": False, "dimensions": dimensions, "errors": errors}
    result = outcome["result"]
    plan = ExecutionPlan.model_validate(jobs[0]["plan"])
    check(
        "result_binding",
        lambda: (
            result["job_id"] == jobs[0]["id"]
            and jobs[0]["result_id"] == result["id"]
            and plan.graph_id == uploaded["id"]
            and result["session_id"] == capture["session_id"]
        ),
    )
    route = next(
        (
            row
            for row in reversed(capture["model_calls"])
            if row["schema"] == "RouteDecision" and row.get("target")
        ),
        None,
    )
    planning = next(
        (
            row
            for row in reversed(capture["model_calls"])
            if row["schema"] == "PlanDraft" and row.get("target")
        ),
        None,
    )
    check(
        "routing",
        lambda: check_target(
            settings,
            root,
            {"reference_contract": task},
            RouteDecision.model_validate(route["target"]),
        ),
    )
    # Only the narrowly checked 3-clique/triangle equivalence can change this
    # objective. Score the resulting native contract with its matching oracle.
    actual_case = copy.deepcopy(case)
    if dimensions["routing"] and plan.operation_id != task["operation_id"]:
        actual_case["task"].update(
            operation_id=plan.operation_id,
            problem_id=plan.problem_id,
            parameters={},
            optional_outputs=["triangles"]
            if "cliques" in task["optional_outputs"]
            else [],
        )
    check(
        "planning",
        lambda: check_target(
            settings,
            root,
            {
                "reference_contract": actual_case["task"],
                "user_payload": planning["payload"],
            },
            PlanDraft.model_validate(planning["target"]),
        ),
    )
    if dimensions["routing"] and dimensions["planning"]:
        actual_case["task"]["parameters"] = plan.parameters
        actual_case["task"]["optional_outputs"] = plan.optional_outputs

        def verify_numerical():
            numerical = grade_output(
                Catalog(settings), actual_case, result["payload"]["output"]
            )
            capture["numerical_validation"] = numerical
            return numerical["checks_passed"]

        check("numerical", verify_numerical)
    else:
        dimensions["numerical"] = False
        errors["numerical"] = (
            "Numerical success cannot qualify without a verified matching objective"
        )
    answer = build_answer(
        case["graph"], plan, result["payload"], source_hash=uploaded["sha256"]
    )
    prepare_analysis(answer)
    if result["interpretation_source"] == "fallback":
        answer["limitations"].append(FALLBACK_NOTICE)
    check("grounding", lambda: answer == result["answer"])
    check(
        "model_interpretation",
        lambda: (
            result["interpretation_source"] == "llm"
            and bool(result["interpretation"].get("explanation"))
        ),
    )
    custom = check(
        "presentation", lambda: presentation_issues(result["interpretation"], answer)
    )
    if "chart_followup" in capture:
        followup = capture["chart_followup"]
        check(
            "followup_reuses_result",
            lambda: (
                capture["jobs_after_followup"] == jobs
                and not followup.get("response", {}).get("job_id")
                and followup.get("response", {}).get("result_id") == result["id"]
            ),
        )
        check(
            "custom_followup",
            lambda: (
                presentation_issues(followup["response"]["interpretation"], answer) > 0
                and followup["response"].get("interpretation_source") == "llm"
            ),
        )
        check(
            "multiple_custom_panels",
            lambda: custom_panel_count(followup["response"]["interpretation"]) >= 2,
        )
    return {
        "passed": all(dimensions.values()),
        "dimensions": dimensions,
        "errors": errors,
        "custom_charts": custom,
    }


async def evaluate(settings, root, manifest, output, *, planner, analyst, base_url):
    selection = json.loads(manifest.read_text())
    if HistoryStore.digest(root / "corpus.json") != selection["corpus_sha256"]:
        raise ValueError("Frozen corpus changed")
    corpus = {
        case["id"]: case
        for case in json.loads((root / "corpus.json").read_text())["cases"]
    }
    configured = replace(
        settings,
        llm_enabled=True,
        llm_base_url=base_url,
        llm_model=planner if planner == analyst else settings.llm_model,
        llm_planner_model=planner if planner != analyst else None,
        llm_analyst_model=analyst if planner != analyst else None,
        llm_route_base_url=None,
        llm_route_allow_expanded_catalog=False,
        llm_route_reasoning_effort="none",
        llm_plan_reasoning_effort="none",
        llm_analyst_reasoning_effort="none",
        history_directory=None,
    )
    binding = {
        "manifest_sha256": HistoryStore.digest(manifest),
        "endpoint": base_url,
        "profile": run_profile(configured),
        "sources": source_bindings(),
        "workflow_sha256": HistoryStore.digest(Path(__file__)),
        "rules_sha256": HistoryStore.digest(
            Path(__file__).with_name("dual_teacher.py")
        ),
    }
    profile_path = output / "profile.json"
    if profile_path.exists() and json.loads(profile_path.read_text()) != binding:
        raise ValueError(
            "Existing workflow output belongs to a different configuration"
        )
    HistoryStore.write(profile_path, binding)
    async with agent_client(configured, data_dir=output / "runtime") as (
        client,
        history,
    ):
        for row in selection["rows"]:
            path = output / "captures" / (row["id"] + ".json")
            if path.exists():
                continue
            case = corpus[row["case_id"]]
            if (
                case["sha256"] != row["case_sha256"]
                or case["split"] != selection["split"]
            ):
                raise ValueError("Frozen scenario binding failed")
            terminal = Terminal(
                client,
                history_root=history,
                output=lambda _: None,
                timeout_seconds=configured.job_timeout_seconds + 120,
            )
            await terminal.start(
                domain_id=case["domain_id"], title="Adapter evaluation: " + row["id"]
            )
            inputs = output / "inputs" / row["id"]
            inputs.mkdir(parents=True, exist_ok=True)
            graph_path = inputs / "graph.json"
            graph_path.write_bytes(encoded(case["graph"]))
            uploaded = await terminal.load(graph_path, role="graph")
            for name, attachments in case["attachments"].items():
                for index, attachment in enumerate(attachments):
                    attachment_path = inputs / f"{name}-{index}.json"
                    attachment_path.write_bytes(encoded(attachment["content"]))
                    await terminal.load(attachment_path, role=attachment["role"])
            capture = {
                "id": row["id"],
                "case_id": case["id"],
                "session_id": terminal.session_id,
                "graph": uploaded,
                "query": case["task"]["question"],
            }
            runtime = client._transport.app.state.runtime
            original_generate = runtime.agent.model.generate

            async def injected_generate(
                *, _generate=original_generate, _capture=capture, **kwargs
            ):
                target = await _generate(**kwargs)
                if (
                    kwargs["schema"] is PlanDraft
                    and target.plan
                    and not _capture.get("injected_error")
                ):
                    target = target.model_copy(deep=True)
                    target.plan.parameters["result_limit"] = 0
                    _capture["injected_error"] = "invalid_result_limit_zero"
                return target

            if row.get("inject_invalid_first_draft"):
                capture["recovery_required"] = True
                runtime.agent.model.generate = injected_generate
            started = time.monotonic()
            try:
                if row["clarification_first"]:
                    capture["clarification"] = copy.deepcopy(
                        await terminal.ask(selection["clarification_question"])
                    )
                    capture["jobs_before_clarification_reply"] = await terminal.request(
                        "GET", "/api/jobs", params={"session_id": terminal.session_id}
                    )
                capture["outcome"] = copy.deepcopy(
                    await terminal.ask(case["task"]["question"])
                )
            except (ClientError, httpx.HTTPError) as error:
                capture["outcome"] = {
                    **copy.deepcopy(terminal.last_outcome),
                    "error": str(error),
                }
            finally:
                runtime.agent.model.generate = original_generate
            capture["jobs"] = await terminal.request(
                "GET", "/api/jobs", params={"session_id": terminal.session_id}
            )
            events = list(HistoryStore(history).session_events(terminal.session_id))
            capture["recovery_request_count"] = sum(
                event["type"] == "planning.recovery.request" for event in events
            )
            calls = []
            for event in events:
                data = event["data"]
                if event["type"] == "model.input":
                    calls.append(copy.deepcopy(data))
                elif (
                    event["type"] == "model.parsed"
                    and calls
                    and calls[-1]["schema"] == data["schema"]
                ):
                    calls[-1]["target"] = data["value"]
            capture["model_calls"] = calls
            if row["chart_followup"] and capture["outcome"].get("result"):
                try:
                    capture["chart_followup"] = copy.deepcopy(
                        await terminal.ask(selection["chart_followup_question"])
                    )
                except (ClientError, httpx.HTTPError) as error:
                    capture["chart_followup"] = {
                        **copy.deepcopy(terminal.last_outcome),
                        "error": str(error),
                    }
                capture["jobs_after_followup"] = await terminal.request(
                    "GET", "/api/jobs", params={"session_id": terminal.session_id}
                )
            capture["elapsed_seconds"] = time.monotonic() - started
            capture["grade"] = grade(configured, root, case, capture)
            HistoryStore.write(path, capture)
            print(
                json.dumps(
                    {
                        "id": row["id"],
                        "grade": capture["grade"],
                        "seconds": capture["elapsed_seconds"],
                    }
                ),
                flush=True,
            )
    results = [
        json.loads((output / "captures" / (row["id"] + ".json")).read_text())
        for row in selection["rows"]
    ]
    summary = {
        "total": len(results),
        "passed": sum(row["grade"]["passed"] for row in results),
        "interpretation_sources": dict(
            Counter(
                row["outcome"]
                .get("result", {})
                .get("interpretation_source", "no_result")
                for row in results
            )
        ),
        "scope": "Actual held-out conversations, local model calls, native GPU execution, bounded reference checks, grounded statements and rendered charts. No human preference labels or broad production accuracy claim.",
    }
    HistoryStore.write(output / "summary.json", summary)
    return summary


def compare(settings, root, manifest, baseline, adapted, destination):
    """Recompute paired grades from complete captures with matching provenance."""
    if destination.exists():
        raise ValueError("Choose a new workflow comparison artifact")
    selection = json.loads(manifest.read_text())
    if HistoryStore.digest(root / "corpus.json") != selection["corpus_sha256"]:
        raise ValueError("Frozen corpus changed")
    corpus = {
        case["id"]: case
        for case in json.loads((root / "corpus.json").read_text())["cases"]
    }
    bindings = {}
    captures = {}
    for label, directory in (("base", baseline), ("adapters", adapted)):
        binding = json.loads((directory / "profile.json").read_text())
        if (
            binding["manifest_sha256"] != HistoryStore.digest(manifest)
            or not binding.get("endpoint")
            or binding["sources"] != source_bindings()
            or binding["workflow_sha256"] != HistoryStore.digest(Path(__file__))
            or binding["rules_sha256"]
            != HistoryStore.digest(Path(__file__).with_name("dual_teacher.py"))
        ):
            raise ValueError("Workflow inputs or evaluation implementation changed")
        bindings[label] = binding
        captures[label] = {}
        for row in selection["rows"]:
            path = directory / "captures" / (row["id"] + ".json")
            if not path.exists():
                raise ValueError("A paired workflow comparison requires every trial")
            case = corpus[row["case_id"]]
            capture = json.loads(path.read_text())
            if (
                case["sha256"] != row["case_sha256"]
                or case["split"] != selection["split"]
                or capture["id"] != row["id"]
                or capture["case_id"] != row["case_id"]
            ):
                raise ValueError("Workflow scenario binding failed")
            scored = grade(settings, root, case, capture)
            required = {"input_binding", "status"}
            if case["task"]["expected_status"] == "ready":
                required.update(
                    {
                        "execution",
                        "result_binding",
                        "routing",
                        "planning",
                        "numerical",
                        "grounding",
                        "model_interpretation",
                        "presentation",
                    }
                )
            else:
                required.add("no_unapproved_execution")
            if row.get("clarification_first"):
                required.add("clarification")
            if row.get("chart_followup"):
                required.update(
                    {
                        "followup_reuses_result",
                        "custom_followup",
                        "multiple_custom_panels",
                    }
                )
            if row.get("inject_invalid_first_draft"):
                required.add("bounded_recovery")
            for dimension in required - scored["dimensions"].keys():
                scored["dimensions"][dimension] = False
                scored["errors"][dimension] = "Required stage was not reached"
            scored["passed"] = all(scored["dimensions"].values())
            captures[label][row["id"]] = {
                "grade": scored,
                "capture_sha256": HistoryStore.digest(path),
                "elapsed_seconds": capture["elapsed_seconds"],
            }
    if bindings["base"].get("endpoint") != bindings["adapters"].get("endpoint"):
        raise ValueError("Use the same shared model service for both configurations")
    for field in ("resource_limits", "decoding", "native_binary_sha256"):
        if bindings["base"]["profile"][field] != bindings["adapters"]["profile"][field]:
            raise ValueError("Workflow execution or decoding settings differ")
    pairs = [
        {"id": row["id"], **{label: captures[label][row["id"]] for label in captures}}
        for row in selection["rows"]
    ]
    dimensions = sorted(
        {
            dimension
            for pair in pairs
            for label in captures
            for dimension in pair[label]["grade"]["dimensions"]
        }
    )
    report = {
        "version": "dual-workflow-paired-comparison-v1",
        "split": selection["split"],
        "bindings": bindings,
        "total": len(pairs),
        "passed": {
            label: sum(pair[label]["grade"]["passed"] for pair in pairs)
            for label in captures
        },
        "corrected": sum(
            not pair["base"]["grade"]["passed"] and pair["adapters"]["grade"]["passed"]
            for pair in pairs
        ),
        "regressed": sum(
            pair["base"]["grade"]["passed"] and not pair["adapters"]["grade"]["passed"]
            for pair in pairs
        ),
        "by_dimension": {
            dimension: {
                "total": sum(
                    any(
                        dimension in pair[label]["grade"]["dimensions"]
                        for label in captures
                    )
                    for pair in pairs
                ),
                **{
                    label: sum(
                        pair[label]["grade"]["dimensions"].get(dimension, False)
                        for pair in pairs
                    )
                    for label in captures
                },
            }
            for dimension in dimensions
        },
        "median_seconds": {
            label: statistics.median(pair[label]["elapsed_seconds"] for pair in pairs)
            for label in captures
        },
        "pairs": pairs,
        "scope": "Actual complete workflows on the same held-out scenarios and service. Grades are recomputed from captures; injected recovery is explicitly synthetic. Automatic numerical, evidence and rendering checks are not human usefulness ratings or proof of broad production accuracy. Weight identity is established separately by the serving receipt.",
    }
    HistoryStore.write(destination, report)
    return {
        key: value for key, value in report.items() if key not in {"pairs", "bindings"}
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "evaluate", "compare"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--planner")
    parser.add_argument("--analyst")
    parser.add_argument("--base-url")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--adapted", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(args.root, args.manifest, args.split)
    elif args.command == "compare":
        result = compare(
            Settings.from_env(),
            args.root,
            args.manifest,
            args.baseline,
            args.adapted,
            args.output,
        )
    else:
        result = asyncio.run(
            evaluate(
                Settings.from_env(),
                args.root,
                args.manifest,
                args.output,
                planner=args.planner,
                analyst=args.analyst,
                base_url=args.base_url,
            )
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
