"""Freeze practical-question routing cases for a completed adapter.

Uses the existing inference implementation unchanged. The same question/label
file can evaluate the original pilot and the revised business-language adapter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..llm import ROUTING_SYSTEM_PROMPT
from ..models import utc_now
from . import adapter_eval
from .business_curriculum import load
from .corpus import digest
from .finetune import read_training_export
from .pipeline import training_route_payload


def cases_for(
    manifest, graphs, catalog, split, training_rows, actual_training_queries=()
):
    if split not in {"validation", "test"}:
        raise ValueError(
            "Only validation or evaluation-family business cards may be evaluated"
        )
    training_ids = {row["id"] for row in training_rows if row["split"] == "train"}
    training_queries = {
        row["task"]["query"] for row in manifest["examples"] if row["split"] == "train"
    }
    training_queries.update(actual_training_queries)
    examples = [row for row in manifest["examples"] if row["split"] == split]
    if not examples or any(row["id"] in training_ids for row in examples):
        raise ValueError("Empty practical evaluation or training identity leakage")
    cases = []
    for example in examples:
        task = example["task"]
        query = task["query"]
        if query in training_queries:
            raise ValueError("Practical evaluation question appeared in training")
        case = {
            "id": example["id"],
            "split": f"business_{split}",
            "family": example["family"],
            "domain": example["domain"],
            "behavior": task["behavior"],
            "operation_id": task["operation_id"],
            "source_sha256": digest(example),
            "source_graph_id": example["graph_id"],
            "source_graph_sha256": digest(graphs[example["graph_id"]]),
            "business_question_kind": example["question_kind"],
            "query_seen_in_training": False,
            "payload": training_route_payload(
                catalog, example, graphs[example["graph_id"]]
            ),
            "expected": example["gold_route"],
        }
        score = adapter_eval.score_route(case, json.dumps(case["expected"]), catalog)
        if not score["passed"]:
            raise ValueError(
                f"Inconsistent practical case {case['id']}: {score['issues']}"
            )
        cases.append(case)
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate practical evaluation identity")
    return cases


def prepare(run: Path, curriculum: Path, output: Path, *, split="test"):
    if output.exists():
        raise ValueError("Use a new practical-question suite directory")
    config = json.loads((run / "run.json").read_text())
    status = json.loads((run / "status.json").read_text())
    if status["phase"] != "completed":
        raise ValueError(
            "Finish training before binding a practical suite to the adapter"
        )
    if config["prompt_sha256"] != digest(ROUTING_SYSTEM_PROMPT) or status[
        "config_sha256"
    ] != HistoryStore.digest(run / "run.json"):
        raise ValueError("Training configuration or routing prompt changed")
    manifest, graphs = load(curriculum)
    curriculum_hash = HistoryStore.digest(curriculum / "manifest.json")
    if config["corpus_sha256"] not in {
        curriculum_hash,
        manifest["source_corpus_sha256"],
    }:
        raise ValueError("Adapter does not belong to the source or business curriculum")
    provenance, training = read_training_export(Path(config["dataset"]))
    cases = cases_for(
        manifest,
        graphs,
        Catalog(Settings.from_env()),
        split,
        provenance["rows"],
        {
            json.loads(row["messages"][1]["content"])["message"]
            for row in training["train"]
        },
    )
    dependencies = adapter_eval.evaluation_dependencies()
    for path in (
        Path(__file__),
        curriculum / "manifest.json",
        curriculum / "audit.json",
    ):
        dependencies[str(path.resolve())] = HistoryStore.digest(path)
    dependencies.update(manifest["source_sha256"])
    output.mkdir(parents=True, mode=0o700)
    HistoryStore.write(output / "cases.json", cases)
    evaluator = Path(adapter_eval.__file__)
    (output / "evaluator.py").write_bytes(evaluator.read_bytes())
    (output / "business_builder.py").write_bytes(Path(__file__).read_bytes())
    plan = {
        "version": adapter_eval.VERSION,
        "created_at": utc_now().isoformat(),
        "run": str(run.resolve()),
        "run_sha256": HistoryStore.digest(run / "run.json"),
        "adapter_sha256": HistoryStore.digest(
            run / "adapter/adapter_model.safetensors"
        ),
        "corpus": manifest["source_corpus"],
        "corpus_sha256": manifest["source_corpus_sha256"],
        "business_curriculum": str(curriculum.resolve()),
        "business_curriculum_sha256": curriculum_hash,
        "training_corpus_sha256": config["corpus_sha256"],
        "split": f"business_{split}",
        "case_count": len(cases),
        "cases_sha256": HistoryStore.digest(output / "cases.json"),
        "source_sha256": HistoryStore.digest(evaluator),
        "dependencies": dependencies,
        "system_prompt": ROUTING_SYSTEM_PROMPT,
        "response_schema": adapter_eval.routing_schema(),
        "max_new_tokens": 2400,
        "max_input_tokens": config["max_sequence_length"],
        "seed": 20261003,
        "decoding": "greedy; thinking disabled; required-field JSON schema; no repair retry",
        "metric": "schema validity + effective routing + exact semantic requirements",
        "queries_seen_in_training": 0,
        "limitations": [
            "Synthetic business requests are authored by the same assistant as their contracts, not independently reviewed customer questions.",
            "Wording banks and graph families are separated; task types and their generator remain related.",
            "The original pilot already encountered evaluation graph families in prior testing, not weight training.",
            "Validation cards can have been used for token-loss evaluation. Evaluation families are excluded from weight and token-loss training.",
            "Routing scores do not establish correct complete conversations, numeric answers, presentation, or business value.",
            "FP8 has another precision and engine; only the NF4 comparisons isolate adapter changes.",
        ],
    }
    HistoryStore.write(output / "plan.json", plan)
    adapter_eval.read_suite(output)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("curriculum", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    args = parser.parse_args()
    result = prepare(args.run, args.curriculum, args.output, split=args.split)
    print(
        json.dumps(
            {key: result[key] for key in ("case_count", "cases_sha256", "split")}
        )
    )


if __name__ == "__main__":
    main()
