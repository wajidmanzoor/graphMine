"""Offline diagnostic review queues. Nothing here creates a training example."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..history import HistoryStore
from ..models import utc_now
from .adapter_workflow_review import complete_rows
from .catalog_compare import _load, recheck_report
from .catalog_replay import source_bindings
from .catalog_suite import digest
from .presentation_checks import check_presentation
from .realworld import load_realworld
from .workflows import check_workflow_step


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def collect_failures(
    settings,
    *,
    workflow_suite=None,
    workflow_reports=(),
    corpus=None,
    comparison=None,
    archived_reports=(),
):
    _require(
        bool(workflow_reports or archived_reports),
        "Select at least one evidence report",
    )
    _require(
        not workflow_reports or workflow_suite is not None, "Workflow suite is required"
    )
    _require(
        not archived_reports or (corpus is not None and comparison is not None),
        "Archived reports require a corpus and hash-bound comparison",
    )
    candidates, sources, seen_reports = {}, [], set()

    def source(path):
        checksum = HistoryStore.digest(path)
        if checksum in seen_reports:
            return None
        seen_reports.add(checksum)
        return {"path": str(path.resolve()), "sha256": checksum}

    def add(
        *, kind, graph_hash, context, task, source_kind, evidence, issues, reference
    ):
        identity = digest(
            {
                "kind": kind,
                "graph": graph_hash,
                "context": context,
                "task": task,
                "source_kind": source_kind,
            }
        )
        if identity not in candidates:
            candidates[identity] = {
                "id": f"candidate_{identity[:24]}",
                "identity_sha256": identity,
                "kind": kind,
                "source_kind": source_kind,
                "query": context[-1],
                "conversation": context,
                "graph_sha256": graph_hash,
                "reference_task": task,
                "reference": reference,
                "issues": [],
                "evidence": [],
                "review_status": "unreviewed",
                "training_eligible": False,
                "corrected_label": None,
                "required_review": [
                    "Confirm the intended meaning with a domain reviewer before proposing a corrected label.",
                    "Reproduce against the current runtime before attributing an archived failure to the current model or adapter.",
                    "Keep evaluation/source families separate; prepare and independently check new training examples if authorized.",
                ],
            }
        row = candidates[identity]
        row["issues"] = sorted(set(row["issues"]) | set(issues))
        row["evidence"].append(evidence)

    if workflow_reports:
        suite = _load(workflow_suite)
        cases = {case["id"]: case for case in suite["cases"]}
        for path in workflow_reports:
            receipt = source(path)
            if receipt is None:
                continue
            checked = recheck_report(
                settings, suite_path=workflow_suite, report_path=path
            )
            sources.append(
                {
                    **receipt,
                    "kind": "current_catalog_workflow",
                    "capture_kind": checked["capture_kind"],
                    "summary": checked["summary"],
                }
            )
            for capture in checked["captures"]:
                grade = capture["grade"]
                failed = [
                    name
                    for name, passed in grade["dimensions"].items()
                    if passed is False
                ]
                if not failed:
                    continue
                case = cases[capture["case_id"]]
                add(
                    kind="workflow_contract",
                    graph_hash=digest(case["graph"]),
                    context=[case["task"]["question"]],
                    task=case["task"],
                    source_kind=checked["capture_kind"],
                    evidence={
                        **receipt,
                        "case_id": case["id"],
                        "trial": capture["trial"],
                        "evidence_sha256": capture["evidence_sha256"],
                        "failed_dimensions": failed,
                        "rechecked_issues": grade["issues"],
                    },
                    issues=failed,
                    reference={
                        "suite_sha256": HistoryStore.digest(workflow_suite),
                        "case_sha256": case["sha256"],
                        "split": "development",
                        "label_source": suite["label_source"],
                    },
                )

    if archived_reports:
        manifest, graphs = load_realworld(corpus)
        old = _load(comparison)
        _require(
            old.get("version") == "adapter-application-comparison-v1"
            and old.get("complete") is True,
            "A complete archived application comparison is required",
        )
        _require(
            old["contract"].get("final_holdout") is False,
            "Held-out evidence is not admitted to the candidate queue",
        )
        references = {case["id"]: case for case in manifest["cases"]}
        for path in archived_reports:
            receipt = source(path)
            if receipt is None:
                continue
            _require(
                old["evidence_sha256"].get(str(path.resolve())) == receipt["sha256"],
                "Archived report differs from its comparison evidence hash",
            )
            report = _load(path)
            _require(
                report.get("mode") == "real-world-evaluation-v3"
                and report.get("corpus_sha256")
                == HistoryStore.digest(corpus / "manifest.json"),
                "Archived report belongs to another corpus or format",
            )
            _require(
                report.get("training_started") is False
                and report.get("training_export_allowed") is False,
                "Expected evaluation-only archived evidence",
            )
            rows = complete_rows(report)
            cases = {case["id"]: case for case in report["cases"]}
            for case in cases.values():
                _require(
                    case.get("split") == "development"
                    and {k: v for k, v in case.items() if k != "queries"}
                    == references.get(case["id"]),
                    "Changed contract or held-out source in archived report",
                )
            counts = Counter()
            for (case_id, trial, index), step in rows.items():
                case = cases[case_id]
                task = case["steps"][index - 1]
                graph = graphs[case["graph_id"]]
                outcome = step["observed"]
                # Distinguish old UI format incompatibilities from mathematical
                # or request-preservation failures. Neither is a new model run.
                for kind, check in (
                    ("archived_workflow_contract", check_workflow_step),
                    ("archived_presentation_compatibility", check_presentation),
                ):
                    issues = check(graph, task, outcome)
                    if not issues:
                        continue
                    counts[kind] += 1
                    add(
                        kind=kind,
                        graph_hash=digest(graph),
                        context=case["queries"][:index],
                        task={
                            key: value for key, value in task.items() if key != "oracle"
                        },
                        source_kind="archived_application_observation",
                        evidence={
                            **receipt,
                            "case_id": case_id,
                            "trial": trial,
                            "step": index,
                            "observed_sha256": digest(outcome),
                            "historical_passed": step["passed"],
                            "historical_issues": step["issues"],
                            "rechecked_issues": issues,
                        },
                        issues=issues,
                        reference={
                            "corpus_sha256": report["corpus_sha256"],
                            "case_sha256": digest(references[case_id]),
                            "comparison_sha256": HistoryStore.digest(comparison),
                            "source_id": case["source_id"],
                            "source": manifest["sources"][case["source_id"]],
                            "split": "development",
                            "label_source": "source_derived_automatic_evaluation_contract",
                        },
                    )
            sources.append(
                {
                    **receipt,
                    "kind": "archived_realworld_application",
                    "turns_rechecked": len(rows),
                    "findings_by_kind": dict(counts),
                    "scope": "Current deterministic checks of historical observations; not a fresh runtime/adapter accuracy score.",
                }
            )

    ordered = sorted(candidates.values(), key=lambda row: (row["kind"], row["id"]))
    checks = source_bindings()
    for name in (
        "failure_candidates.py",
        "pipeline.py",
        "workflows.py",
        "presentation_checks.py",
        "realworld.py",
        "realworld_cases.py",
        "adapter_workflow_review.py",
    ):
        checks[f"learning/{name}"] = HistoryStore.digest(Path(__file__).with_name(name))
    return {
        "version": "graphmine-failure-review-queue-v1",
        "created_at": utc_now().isoformat(),
        "sources": sources,
        "checker_source_sha256": checks,
        "candidates": ordered,
        "candidate_count": len(ordered),
        "counts_by_kind": dict(Counter(row["kind"] for row in ordered)),
        "training_eligible": False,
        "training_started": False,
        "human_review": "unreviewed",
        "model_inference": "not_run",
        "native_execution": "not_run",
        "saved_grades_trusted": False,
        "deduplication": "Identical source bytes are processed once. Candidate identity binds graph, complete preceding user conversation, task contract, finding kind and source kind; no semantic-equivalence claim.",
        "scope": "Diagnostic review candidates only. Evaluation artifacts remain excluded from training. No corrected labels, SFT records, independent model attribution, or human approval are manufactured. Content hashes bind saved evidence, not the authenticity of the producer/model weights.",
    }
