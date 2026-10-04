"""Build an application-question curriculum without rewriting the prior pilot.

The wording is authored synthetic supervision. Numeric labels reuse an existing
native audit only when the graph, requested computation, filters and requirements
are unchanged. That check is not an independent review of natural-language meaning.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections import Counter
from pathlib import Path

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import RouteDecision, utc_now
from . import business_questions
from .business_questions import CLARIFICATIONS, question_for, wording_issues
from .corpus import digest, load_corpus
from .finetune import read_training_export
from .oracles import expected_answer, verify_output
from .pipeline import training_route_payload

VERSION = "business-routing-curriculum-v1"


def source_hashes():
    return {
        str(path.resolve()): HistoryStore.digest(path)
        for path in (Path(__file__), Path(business_questions.__file__))
    }


def semantic_contract(task):
    value = copy.deepcopy(task)
    value.pop("query")
    value["intent"].pop("objective")
    return value


def adapt_example(source, *, broad_goal=False):
    if broad_goal and source["task"]["behavior"] != "clarify":
        raise ValueError("Broad business goals require an explicit clarification label")
    query, omission = question_for(source, broad_goal=broad_goal)
    if omission:
        return None, omission
    issues = wording_issues(query)
    if issues:
        raise ValueError(f"Invalid business card {source['id']}: {issues}")
    result = copy.deepcopy(source)
    result.update(
        id=f"business-{source['id']}" + ("-goal" if broad_goal else ""),
        source="authored_business_task_card_with_source_contract",
        source_example_id=source["id"],
        source_example_sha256=digest(source),
        question_kind="broad_business_goal" if broad_goal else "application_request",
    )
    result["task"]["query"] = query
    result["task"]["intent"]["objective"] = query
    label = result["gold_route"]
    label["intent"]["objective"] = query
    if result["task"]["behavior"] == "clarify":
        message = CLARIFICATIONS[result["domain"]]
        label["explanation"], label["ambiguity"] = message, [message]
    elif result["task"]["behavior"] == "unsupported":
        label["explanation"] = (
            "The available analysis cannot rank intermediaries using total journey costs. I can still help select records using their recorded costs."
            if result["task"]["intent"]["requires_edge_weights"]
            else "The available checks cannot count the requested four-machine relay. I cannot provide a reliable count for that sequence."
        )
    else:
        label["explanation"] = (
            "I can use these records to answer this request while preserving the stated selection rules."
        )
    RouteDecision.model_validate(label)
    if semantic_contract(result["task"]) != semantic_contract(source["task"]):
        raise ValueError("Changing business wording changed a source contract")
    return result, None


def build_examples(source_manifest):
    examples, omitted = [], []
    for source in source_manifest["examples"]:
        example, reason = adapt_example(source)
        if example is None:
            omitted.append({"source_example_id": source["id"], "reason": reason})
            continue
        examples.append(example)
        if source["task"]["behavior"] == "clarify":
            broad, _ = adapt_example(source, broad_goal=True)
            examples.append(broad)
    queries = {
        split: {e["task"]["query"] for e in examples if e["split"] == split}
        for split in ("train", "validation", "test")
    }
    if any(
        queries[left] & queries[right]
        for left, right in (
            ("train", "validation"),
            ("train", "test"),
            ("validation", "test"),
        )
    ):
        raise ValueError("Question wording leaked between split-specific banks")
    return examples, omitted


def audit_examples(examples, source_manifest, graphs, native, corpus):
    if (
        native.get("mode") != "native_oracle"
        or not native.get("finished_at")
        or native["corpus_sha256"] != HistoryStore.digest(corpus / "manifest.json")
        or native["checker_sha256"]
        != HistoryStore.digest(Path(__file__).with_name("oracles.py"))
    ):
        raise ValueError(
            "A current completed native audit of the source corpus is required"
        )
    sources = {e["id"]: e for e in source_manifest["examples"]}
    checks = {row["id"]: row for row in native["examples"]}
    if len(checks) != len(native["examples"]):
        raise ValueError("Duplicate native-audit identity")
    records = []
    for example in examples:
        source = sources[example["source_example_id"]]
        check = checks.get(source["id"])
        task = example["task"]
        graph = graphs[example["graph_id"]]
        issues = wording_issues(task["query"])
        if semantic_contract(task) != semantic_contract(source["task"]):
            issues.append("Changed source computation or requirements")
        if expected_answer(graph, task) != task["oracle"]:
            issues.append("Independent oracle result changed")
        if (
            not check
            or not check["passed"]
            or check["example_sha256"] != digest(source)
        ):
            issues.append("Missing, failed or changed source native audit")
        elif task["behavior"] == "execute":
            payload = check.get("payload", {})
            if payload.get("ok") is not True:
                issues.append("Source native execution failed")
            issues.extend(verify_output(graph, task, payload.get("output", {})))
        records.append(
            {
                "id": example["id"],
                "example_sha256": digest(example),
                "source_example_id": source["id"],
                "source_native_check_sha256": digest(check),
                "semantic_contract_sha256": digest(semantic_contract(task)),
                "computation_unchanged": not issues,
                "passed": not issues,
                "issues": issues,
                "meaning_review": "authored_question_bank_not_independent_language_review",
                "verification": (
                    "unchanged_computation_saved_native_output_revalidated"
                    if task["behavior"] == "execute"
                    else "unchanged_source_clarification_or_capability_contract"
                ),
            }
        )
    return records


def build(corpus: Path, native_audit: Path, output: Path):
    if output.exists():
        raise ValueError("Use a new curriculum directory; preserve prior evidence")
    source_manifest, graphs = load_corpus(corpus)
    native = json.loads(native_audit.read_text())
    examples, omitted = build_examples(source_manifest)
    checks = audit_examples(examples, source_manifest, graphs, native, corpus)
    if any(not row["passed"] for row in checks):
        raise ValueError(
            "Business cards failed source-contract or native-output checks"
        )
    now = utc_now().isoformat()
    manifest = {
        "version": VERSION,
        "created_at": now,
        "source_corpus": str(corpus.resolve()),
        "source_corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "source_native_audit": str(native_audit.resolve()),
        "source_native_audit_sha256": HistoryStore.digest(native_audit),
        "source_sha256": source_hashes(),
        "examples": examples,
        "omitted_source_examples": omitted,
        "split_counts": dict(Counter(e["split"] for e in examples)),
        "scope": "Authored synthetic application questions. Separate wording banks and graph families; same author and task types, not independent customer data. Business goals with unspecified criteria ask a domain-language clarification. All real-world sources excluded.",
        "independent_language_review": False,
        "training_started": False,
    }
    output.mkdir(parents=True, mode=0o700)
    for path in (Path(__file__), Path(business_questions.__file__)):
        (output / path.name).write_bytes(path.read_bytes())
    HistoryStore.write(output / "manifest.json", manifest)
    audit = {
        "mode": "business_question_source_contract_audit",
        "created_at": now,
        "finished_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(output / "manifest.json"),
        "source_native_audit_sha256": HistoryStore.digest(native_audit),
        "examples": checks,
        "passed": sum(row["passed"] for row in checks),
        "total": len(checks),
        "native_jobs_rerun": 0,
        "independent_language_review": False,
        "caution": "The computation and graph are unchanged and saved native results were rechecked. This does not independently establish that the new wording has exactly the intended meaning or that the model understands it.",
    }
    HistoryStore.write(output / "audit.json", audit)
    return manifest


def load(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("version") != VERSION
        or manifest["source_sha256"] != source_hashes()
    ):
        raise ValueError("Business curriculum implementation or version changed")
    corpus = Path(manifest["source_corpus"])
    audit_path = Path(manifest["source_native_audit"])
    if (
        HistoryStore.digest(corpus / "manifest.json")
        != manifest["source_corpus_sha256"]
        or HistoryStore.digest(audit_path) != manifest["source_native_audit_sha256"]
    ):
        raise ValueError("Business curriculum source evidence changed")
    source, graphs = load_corpus(corpus)
    examples, omitted = build_examples(source)
    if (
        examples != manifest["examples"]
        or omitted != manifest["omitted_source_examples"]
    ):
        raise ValueError("Business questions, labels or exclusions changed")
    audit = json.loads((directory / "audit.json").read_text())
    checks = audit_examples(
        examples, source, graphs, json.loads(audit_path.read_text()), corpus
    )
    if (
        audit.get("mode") != "business_question_source_contract_audit"
        or not audit.get("finished_at")
        or audit["corpus_sha256"] != HistoryStore.digest(directory / "manifest.json")
        or audit["examples"] != checks
        or any(not row["passed"] for row in checks)
    ):
        raise ValueError("Business curriculum audit is changed, incomplete or failed")
    return manifest, graphs


def export(directory: Path, output: Path):
    if output.exists():
        raise ValueError("Use a new business training export")
    manifest, graphs = load(directory)
    catalog = Catalog(Settings.from_env())
    lines, provenance = {"train": [], "validation": []}, []
    for example in manifest["examples"]:
        split = example["split"]
        if split == "test":
            continue
        payload = training_route_payload(catalog, example, graphs[example["graph_id"]])
        row = {
            "messages": [
                {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {
                    "role": "assistant",
                    "content": json.dumps(example["gold_route"], ensure_ascii=False),
                },
            ]
        }
        lines[split].append(row)
        provenance.append(
            {
                "id": example["id"],
                "split": split,
                "family": example["family"],
                "row_sha256": digest(row),
                "source_example_id": example["source_example_id"],
                "example_sha256": digest(example),
                "label_source": "authored_business_request_and_unchanged_oracle_gated_contract",
                "review_state": "authored_synthetic_candidate_not_independently_reviewed",
                "stage": "RouteDecision",
            }
        )
    output.mkdir(parents=True, mode=0o700)
    for split, rows in lines.items():
        path = output / f"{split}.jsonl"
        with path.open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
    result = {
        "schema_version": "1.0.0",
        "created_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(directory / "manifest.json"),
        "audit_sha256": HistoryStore.digest(directory / "audit.json"),
        "business_curriculum": str(directory.resolve()),
        "source_corpus_sha256": manifest["source_corpus_sha256"],
        "rows": provenance,
        "quarantine": [],
        "files": {
            split: HistoryStore.digest(output / f"{split}.jsonl") for split in lines
        },
        "training_started": False,
        "teacher_model": None,
        "scope": "Business-language synthetic routing supervision, not independently reviewed teacher distillation. Test-family and all real-source examples excluded. Does not train planning or answer-writing stages.",
    }
    HistoryStore.write(output / "provenance.json", result)
    read_training_export(output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    create.add_argument("corpus", type=Path)
    create.add_argument("--native-audit", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    save = commands.add_parser("export")
    save.add_argument("curriculum", type=Path)
    save.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.corpus, args.native_audit, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "split_counts": result["split_counts"],
                    "omitted": len(result["omitted_source_examples"]),
                }
            )
        )
    else:
        result = export(args.curriculum, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "split_counts": dict(Counter(r["split"] for r in result["rows"])),
                }
            )
        )


if __name__ == "__main__":
    main()
