"""Bounded local/opt-in external wording proposals; every output starts quarantined."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..history import HistoryStore
from ..models import utc_now
from .corpus import digest, load_corpus
from .inference import (
    LearningModel,
    ModelProfile,
    RequestBudget,
    estimate_request,
    request_body,
)
from .pipeline import choose_examples
from .review import blind_payload
from .teacher import SYSTEM, ParaphraseBatch


async def propose_candidates(
    settings: Settings,
    *,
    corpus: Path,
    destination: Path,
    profile: ModelProfile,
    count: int = 5,
    execute: bool = False,
    allow_external: bool = False,
    allow_codex: bool = False,
    budget_usd: float | None = None,
) -> dict:
    if not 1 <= count <= 20:
        raise ValueError("Choose 1-20 proposal calls per run")
    manifest, graphs = load_corpus(corpus)
    selected = choose_examples(manifest, "train", count)
    budget = RequestBudget(maximum_usd=budget_usd, max_calls=len(selected))
    estimated = sum(
        estimate_request(
            profile,
            request_body(
                profile,
                SYSTEM,
                blind_payload(graphs[row["graph_id"]], row["task"]["query"]),
                ParaphraseBatch,
            ),
        )["reserved_usd"]
        for row in selected
    )
    if execute and budget_usd is not None and estimated > budget_usd:
        raise ValueError("Full proposal reservation exceeds the budget; no calls sent")
    if destination.exists():
        raise ValueError("Proposal output exists; choose a new directory")
    if execute:
        async with LearningModel(
            settings,
            profile,
            budget,
            allow_external=allow_external,
            allow_codex=allow_codex,
        ):
            pass
    destination.mkdir(parents=True, mode=0o700)
    report = {
        "schema_version": "1.0.0",
        "started_at": utc_now().isoformat(),
        "executed": execute,
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "teacher_model": profile.model,
        "teacher_endpoint": profile.public()["base_url"],
        "profile": profile.public(),
        "call_limit": count,
        "training_started": False,
        "scope": "Wording candidates from verified synthetic training families only. No labels are teacher-certified; every proposal requires independent semantic and execution review.",
        "estimated_total_reservation_usd": estimated,
        "fits_requested_budget": budget_usd is None or estimated <= budget_usd,
        "calls": [],
        "candidates": [],
    }
    seen = set()
    if execute:
        async with LearningModel(
            settings,
            profile,
            budget,
            allow_external=allow_external,
            allow_codex=allow_codex,
        ) as model:
            for index, example in enumerate(selected):
                artifact = destination / "calls" / f"proposal-{index:02d}.json"
                call = {"example_id": example["id"]}
                print(f"Proposing application wording: {example['id']}", flush=True)
                try:
                    batch = await model.generate(
                        system=SYSTEM,
                        payload=blind_payload(
                            graphs[example["graph_id"]], example["task"]["query"]
                        ),
                        schema=ParaphraseBatch,
                        artifact=artifact,
                    )
                    for query in batch.queries:
                        query = query.strip()
                        if (
                            not 10 <= len(query) <= 3000
                            or query in seen
                            or query == example["task"]["query"]
                        ):
                            continue
                        seen.add(query)
                        report["candidates"].append(
                            {
                                "id": "proposal-" + digest([example["id"], query])[:16],
                                "example_id": example["id"],
                                "example_sha256": digest(example),
                                "query": query,
                                "teacher_model": profile.model,
                                "status": "quarantined_unverified_paraphrase",
                                "training_eligible": False,
                            }
                        )
                    call["status"] = "proposed"
                except ValueError as error:
                    call.update(status="failed", error=str(error))
                if artifact.is_file():
                    call.update(
                        artifact=str(artifact.relative_to(destination)),
                        artifact_sha256=HistoryStore.digest(artifact),
                    )
                report["calls"].append(call)
                report["budget"] = budget.public()
                HistoryStore.write(destination / "candidates.json", report)
    report.update(finished_at=utc_now().isoformat(), budget=budget.public())
    HistoryStore.write(destination / "candidates.json", report)
    return report
