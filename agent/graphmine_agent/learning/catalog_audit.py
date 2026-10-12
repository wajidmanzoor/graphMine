"""CPU-only contract checks for current-catalog development fixtures."""

from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path

from ..catalog import Catalog
from ..database import Database
from ..graph_context import project_graph
from ..graph_store import GraphStore
from ..models import ExecutionPlan, RouteDecision, SessionRecord
from ..planning import (
    PlanValidationError,
    PlanValidator,
    normalize_route,
    route_blocker,
)
from ..profiles import ProfileInputError, prepare_operation_graph
from .catalog_reference import reference_for_case
from .catalog_suite import digest, load_suite
from .corpus import load_corpus
from .oracles import isomorphic


def question_key(question):
    return " ".join(
        re.findall(r"\w+", unicodedata.normalize("NFKC", question).casefold())
    )


def overlap_report(suite, reference_manifest, reference_graphs):
    """Flag exact text and topology reuse; neither check proves semantic isolation."""
    questions = {}
    for example in reference_manifest["examples"]:
        questions.setdefault(question_key(example["task"]["query"]), []).append(example)
    question_matches, topology_matches = [], []
    graph_metadata = {row["id"]: row for row in reference_manifest["graphs"]}
    cached_matches = {}
    for case in suite["cases"]:
        for example in questions.get(question_key(case["task"]["question"]), []):
            question_matches.append(
                {
                    "case_id": case["id"],
                    "reference_example_id": example["id"],
                    "reference_split": example["split"],
                }
            )
        graph_digest = digest(case["graph"])
        if graph_digest not in cached_matches:
            cached_matches[graph_digest] = [
                graph_id
                for graph_id, graph in reference_graphs.items()
                if isomorphic(case["graph"], graph)
            ]
        for graph_id in cached_matches[graph_digest]:
            topology_matches.append(
                {
                    "case_id": case["id"],
                    "reference_graph_id": graph_id,
                    "reference_split": graph_metadata[graph_id]["split"],
                }
            )
    unique_graphs = {}
    for case in suite["cases"]:
        unique_graphs.setdefault(digest(case["graph"]), case["graph"])
    representatives = []
    for graph in unique_graphs.values():
        if not any(isomorphic(graph, other) for other in representatives):
            representatives.append(graph)
    return {
        "reference_manifest_sha256": digest(reference_manifest),
        "reference_generator": reference_manifest["generator"],
        "distinct_input_graphs": len(unique_graphs),
        "distinct_unlabeled_topologies": len(representatives),
        "normalized_question_matches": question_matches,
        "unlabeled_topology_matches": topology_matches,
        "scope": "Exact normalized wording and exact unweighted graph isomorphism only. Direction is preserved; names, types, attributes, edge values, filters and task semantics are ignored in topology checks. Matches flag possible reuse, not identical task meaning. No-match does not establish semantic independence.",
        "generalization_holdout": False,
    }


def materialize_case(store, database, case):
    """Use production ingestion; attachments contain no external file paths."""
    session = database.create_session(SessionRecord(domain_id=case["domain_id"]))

    def ingest(content, role, name):
        return store.ingest(
            session_id=session.id,
            role=role,
            filename=name + ".json",
            content=json.dumps(content, allow_nan=False).encode(),
            media_type="application/json",
        )

    graph = ingest(case["graph"], "graph", "dataset")
    auxiliary = {}
    for name, files in case["attachments"].items():
        auxiliary[name] = [
            ingest(item["content"], item["role"], f"{name}-{index}").id
            for index, item in enumerate(files)
        ]
    return session, graph, auxiliary


def audit_case(catalog, store, database, case):
    session, graph, auxiliary = materialize_case(store, database, case)
    task = case["task"]
    decision = normalize_route(
        catalog,
        RouteDecision(
            problem_id=task["problem_id"],
            operation_id=task["operation_id"],
            supported=task["operation_id"] is not None,
            confidence=1,
            explanation="Assistant-authored contract proposal; not a model prediction.",
            intent=task["intent"],
        ),
    )
    blocker = route_blocker(catalog, decision)
    if blocker:
        status, reason = blocker
        plan = None
    else:
        plan = ExecutionPlan(
            session_id=session.id,
            graph_id=graph.id,
            problem_id=task["problem_id"],
            operation_id=task["operation_id"],
            parameters=task["parameters"],
            optional_outputs=task["optional_outputs"],
            auxiliary_inputs=auxiliary,
            application_intent=task["intent"],
        )
        try:
            plan = PlanValidator(catalog).validate(plan)
            projected = project_graph(
                store.read_graph(graph.id, session.id), plan.application_intent.filters
            )
            prepare_operation_graph(projected, plan)
            if plan.missing_inputs:
                status, reason = "needs_information", ", ".join(plan.missing_inputs)
            else:
                plan = PlanValidator(catalog).validate(plan, for_execution=True)
                status, reason = "ready", None
        except ProfileInputError as error:
            status, reason = error.status, str(error)
        except PlanValidationError as error:
            status, reason = "unsupported", str(error)
    return {
        "id": case["id"],
        "case_sha256": case["sha256"],
        "operation_id": task["operation_id"],
        "problem_id": task["problem_id"],
        "expected_status": task["expected_status"],
        "observed_status": status,
        "passed": status == task["expected_status"],
        "reason": reason,
        "normalized_parameters": plan.parameters if plan else None,
        "verification": "cpu_ingestion_and_planning_contract_only",
        "reference": reference_for_case(case)
        if status == task["expected_status"]
        else None,
    }


def audit_suite(settings, suite_path: Path, *, reference_corpora=()):
    catalog = Catalog(settings)
    suite = load_suite(catalog, suite_path)
    # Never open the pilot database, invoke an inference endpoint, start a
    # worker, or run the native binary while auditing contract fixtures.
    with tempfile.TemporaryDirectory(prefix="graphmine-catalog-audit-") as directory:
        isolated = replace(
            settings,
            data_root=Path(directory),
            history_directory=None,
            llm_enabled=False,
        )
        database = Database(isolated.database_path)
        store = GraphStore(isolated, database)
        records = [
            audit_case(catalog, store, database, case) for case in suite["cases"]
        ]
    overlaps = []
    for path in reference_corpora:
        manifest, graphs = load_corpus(Path(path))
        overlaps.append(overlap_report(suite, manifest, graphs))
    return {
        "version": "current-catalog-contract-audit-v1",
        "suite_sha256": digest(suite),
        "catalog_sha256": suite["catalog_sha256"],
        "source_sha256": digest(
            {
                name: (Path(__file__).parent.parent / name).read_text()
                for name in [
                    "planning.py",
                    "profiles.py",
                    "graph_store.py",
                    "graph_context.py",
                ]
            }
        ),
        "label_source": suite["label_source"],
        "audit_source_sha256": digest(
            {
                name: Path(__file__).with_name(name).read_text()
                for name in [
                    "catalog_audit.py",
                    "catalog_suite.py",
                    "corpus.py",
                    "oracles.py",
                    "catalog_reference.py",
                ]
            }
        ),
        "human_review": "unreviewed",
        "native_execution": "not_run",
        "model_inference": "not_run",
        "numerical_validation": "not_run",
        "reference_computation": "complete"
        if all(row["reference"] is not None for row in records)
        else "incomplete",
        "passed": sum(record["passed"] for record in records),
        "total": len(records),
        "problem_count": len({record["problem_id"] for record in records}),
        "operation_count": len(
            {record["operation_id"] for record in records if record["operation_id"]}
        ),
        "by_status": dict(Counter(record["observed_status"] for record in records)),
        "overlap_checks": overlaps,
        "overlap_check_status": "completed" if overlaps else "not_requested",
        "cases": records,
    }
