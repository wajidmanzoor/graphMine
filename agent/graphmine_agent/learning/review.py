"""Teacher comparison and blinded semantic review, with separate execution gates."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from ..config import Settings
from ..graph_context import semantic_context
from ..history import HistoryStore
from ..models import utc_now
from ..terminal import ClientError, Terminal, agent_client
from .codex import parse_stream
from .corpus import digest, load_corpus
from .inference import (
    LearningModel,
    ModelProfile,
    RequestBudget,
    estimate_request,
    request_body,
)
from .meaning import (
    EXTRACTION_SYSTEM,
    MeaningExtraction,
    QuestionMeaning,
    calibration_controls,
    evidence_issues,
    expected_meaning,
    meaning_differences,
    wording_issues,
)
from .pipeline import check_agent_outcome

MEANING_PATH = Path(__file__).with_name("meaning.py")


def reviewer_contract_sha256() -> str:
    return digest(
        {
            name: HistoryStore.digest(Path(__file__).with_name(name))
            for name in ("meaning.py", "review.py", "inference.py", "codex.py")
        }
    )


def replay_contract_sha256() -> str:
    root = Path(__file__).parent.parent
    names = (
        "agent_service.py",
        "llm.py",
        "planning.py",
        "answers.py",
        "presentation.py",
        "selector.py",
        "graph_context.py",
        "models.py",
        "visualization.py",
        "execution.py",
        "learning/oracles.py",
        "learning/pipeline.py",
    )
    return digest({name: HistoryStore.digest(root / name) for name in names})


def blind_payload(graph: dict, question: str) -> dict:
    # Deliberately excludes original question, task/operation, gold route, oracle
    # answer, candidate source ID and the pass/fail criterion.
    context = semantic_context(graph)
    # A meaning reader needs the vocabulary/schema, not counts, statistics or
    # five copies of every record. Do not use answer-derived context here.
    for collection in ("vertex_attributes", "edge_attributes"):
        context[collection] = {
            name: {
                "types": value["types"],
                "examples": [item["value"] for item in value["examples"][:2]],
            }
            for name, value in context[collection].items()
        }
    context["vertex_examples"] = context["vertex_examples"][:1]
    context["edge_examples"] = context["edge_examples"][:1]
    return {"question": question, "graph_context": context}


def verified_artifact(root: Path, relative: str, expected_digest: str) -> dict:
    path = (root / relative).resolve()
    if (
        not path.is_relative_to(root.resolve())
        or HistoryStore.digest(path) != expected_digest
    ):
        raise ValueError("Saved evidence changed or escaped its directory")
    return json.loads(path.read_text())


def verify_extraction_call(
    saved: dict, profile: ModelProfile, graph: dict, query: str, extracted: dict
) -> None:
    expected_request = request_body(
        profile, EXTRACTION_SYSTEM, blind_payload(graph, query), MeaningExtraction
    )
    if (
        saved.get("status") != "completed"
        or saved.get("parsed") != extracted
        or saved.get("profile") != profile.public()
        or saved.get("request") != expected_request
    ):
        raise ValueError("Extraction does not match its blinded model-call evidence")
    if profile.provider == "codex":
        cli = saved.get("codex_cli") or {}
        if cli.get("auth") != "chatgpt" or cli.get("exit_code") != 0:
            raise ValueError(
                "Saved Codex call lacks successful ChatGPT-authenticated execution"
            )
        text, usage = parse_stream(saved["raw_response"], profile.max_output_tokens)
        if usage != saved.get("usage"):
            raise ValueError("Saved Codex usage differs from its event stream")
    elif profile.provider == "local":
        raw = json.loads(saved["raw_response"])
        choice = raw["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
            raise ValueError("Saved local response is incomplete or refused")
        text = choice["message"]["content"]
    else:
        raw = json.loads(saved["raw_response"])
        content = [
            entry
            for item in raw.get("output", [])
            if item.get("type") == "message"
            for entry in item.get("content", [])
        ]
        texts = [
            entry["text"] for entry in content if entry.get("type") == "output_text"
        ]
        if (
            raw.get("status") != "completed"
            or len(texts) != 1
            or any(entry.get("type") == "refusal" for entry in content)
        ):
            raise ValueError("Saved external response is incomplete or refused")
        text = texts[0]
    if MeaningExtraction.model_validate_json(text).model_dump(mode="json") != extracted:
        raise ValueError("Parsed extraction differs from the raw model response")


def _new_directory(destination: Path) -> None:
    if destination.exists():
        raise ValueError("Output exists; choose a new directory to preserve evidence")
    destination.mkdir(parents=True, mode=0o700)


def load_proposals(corpus: Path, candidates: Path) -> tuple[dict, dict, dict]:
    manifest, graphs = load_corpus(corpus)
    report = json.loads(candidates.read_text())
    if not report.get("finished_at") or report.get(
        "corpus_sha256"
    ) != HistoryStore.digest(corpus / "manifest.json"):
        raise ValueError(
            "Completed proposals for this exact synthetic corpus are required"
        )
    if not 1 <= len(report.get("candidates", [])) <= 60 or not report.get(
        "teacher_model"
    ):
        raise ValueError("Expected 1-60 teacher proposals with model provenance")
    examples = {row["id"]: row for row in manifest["examples"]}
    seen = set()
    for row in report["candidates"]:
        identifier = HistoryStore.identifier(row["id"])
        example = examples.get(row["example_id"])
        if not example or example["split"] != "train":
            raise ValueError(
                "Only training-family proposals may be reviewed for export"
            )
        if row.get("example_sha256") != digest(example):
            raise ValueError("Proposal source example changed")
        query = row["query"]
        if not isinstance(query, str) or not 10 <= len(query) <= 3000:
            raise ValueError("Proposal question length is invalid")
        if (
            identifier != "proposal-" + digest([example["id"], query])[:16]
            or identifier in seen
        ):
            raise ValueError("Duplicate or modified proposal identity")
        if (
            row["teacher_model"] != report["teacher_model"]
            or row.get("training_eligible") is not False
        ):
            raise ValueError(
                "Unreviewed proposals must preserve teacher identity and remain ineligible"
            )
        seen.add(identifier)
    return manifest, graphs, report


async def compare_teachers(
    settings: Settings,
    *,
    corpus: Path,
    destination: Path,
    profiles: list[ModelProfile],
    execute: bool = False,
    allow_external: bool = False,
    allow_codex: bool = False,
    budget_usd: float | None = None,
) -> dict:
    manifest, graphs = load_corpus(corpus)
    controls = calibration_controls(manifest)
    if not 1 <= len(profiles) <= 3 or len(
        {digest(p.public()) for p in profiles}
    ) != len(profiles):
        raise ValueError("Compare one to three distinct model profiles")
    budget = RequestBudget(
        maximum_usd=budget_usd, max_calls=len(controls) * len(profiles)
    )
    estimated_total = sum(
        estimate_request(
            profile,
            request_body(
                profile,
                EXTRACTION_SYSTEM,
                blind_payload(graphs[control["graph_id"]], control["query"]),
                MeaningExtraction,
            ),
        )["reserved_usd"]
        for profile in profiles
        for control in controls
    )
    if execute and budget_usd is not None and estimated_total > budget_usd:
        raise ValueError(
            f"Full comparison reservation US${estimated_total:.4f} exceeds the run budget; no calls sent"
        )
    # Validate credentials/consent before creating a directory or sending calls.
    if execute:
        for profile in profiles:
            async with LearningModel(
                settings,
                profile,
                budget,
                allow_external=allow_external,
                allow_codex=allow_codex,
            ):
                pass
    _new_directory(destination)
    report = {
        "schema_version": "1.0.0",
        "mode": "reviewer_calibration",
        "started_at": utc_now().isoformat(),
        "executed": execute,
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "meaning_sha256": HistoryStore.digest(MEANING_PATH),
        "reviewer_contract_sha256": reviewer_contract_sha256(),
        "controls_sha256": digest(controls),
        "controls": controls,
        "models": [],
        "selection_policy": "All controls must pass exact semantics and grounded spans before this profile can gate exports; a small control set is not general accuracy or proof of independent model lineage.",
        "training_started": False,
    }
    for model_index, profile in enumerate(profiles):
        model_report = {
            "profile": profile.public(),
            "checks": [],
            "estimated_reservation_usd": 0.0,
        }
        report["models"].append(model_report)
        for control in controls:
            body = request_body(
                profile,
                EXTRACTION_SYSTEM,
                blind_payload(graphs[control["graph_id"]], control["query"]),
                MeaningExtraction,
            )
            model_report["estimated_reservation_usd"] += estimate_request(
                profile, body
            )["reserved_usd"]
        if execute:
            async with LearningModel(
                settings,
                profile,
                budget,
                allow_external=allow_external,
                allow_codex=allow_codex,
            ) as model:
                for index, control in enumerate(controls):
                    artifact = (
                        destination
                        / "calls"
                        / f"model-{model_index}-control-{index:02d}.json"
                    )
                    print(f"Calibrating {profile.model}: {control['id']}", flush=True)
                    check = {"id": control["id"], "kind": control["kind"]}
                    try:
                        extraction = await model.generate(
                            system=EXTRACTION_SYSTEM,
                            payload=blind_payload(
                                graphs[control["graph_id"]], control["query"]
                            ),
                            schema=MeaningExtraction,
                            artifact=artifact,
                        )
                        check["extracted"] = extraction.model_dump(mode="json")
                        check["issues"] = meaning_differences(
                            QuestionMeaning.model_validate(control["expected"]),
                            extraction.meaning,
                        ) + evidence_issues(control["query"], extraction)
                    except ValueError as error:
                        check["issues"] = [str(error)]
                    check["passed"] = not check["issues"]
                    if artifact.is_file():
                        check["call"] = str(artifact.relative_to(destination))
                        check["call_sha256"] = HistoryStore.digest(artifact)
                    model_report["checks"].append(check)
                    report["budget"] = budget.public()
                    HistoryStore.write(destination / "comparison.json", report)
        model_report["passed"] = sum(row["passed"] for row in model_report["checks"])
        model_report["total"] = len(model_report["checks"])
        model_report["qualified_for_screening"] = execute and model_report[
            "passed"
        ] == model_report["total"] == len(controls)
    report["estimated_total_reservation_usd"] = sum(
        row["estimated_reservation_usd"] for row in report["models"]
    )
    report["fits_requested_budget"] = (
        budget_usd is None or report["estimated_total_reservation_usd"] <= budget_usd
    )
    report["finished_at"] = utc_now().isoformat()
    report["budget"] = budget.public()
    HistoryStore.write(destination / "comparison.json", report)
    return report


def calibrated_profile(
    corpus: Path, manifest: dict, calibration: Path | None, profile: ModelProfile
) -> bool:
    if calibration is None:
        return False
    value = json.loads(calibration.read_text())
    controls = calibration_controls(manifest)
    if (
        value.get("mode") != "reviewer_calibration"
        or not value.get("executed")
        or not value.get("finished_at")
        or value.get("corpus_sha256") != HistoryStore.digest(corpus / "manifest.json")
        or value.get("meaning_sha256") != HistoryStore.digest(MEANING_PATH)
        or value.get("reviewer_contract_sha256") != reviewer_contract_sha256()
        or value.get("controls_sha256") != digest(controls)
    ):
        raise ValueError("Calibration is stale, incomplete or only a dry run")
    _, graphs = load_corpus(corpus)
    matching = [row for row in value["models"] if row["profile"] == profile.public()]
    if len(matching) != 1:
        raise ValueError("Calibration has no matching reviewer profile")
    checks = matching[0]["checks"]
    if len(checks) != len(controls) or {row["id"] for row in checks} != {
        row["id"] for row in controls
    }:
        return False
    by_id = {row["id"]: row for row in controls}
    for check in checks:
        if not check.get("passed") or not check.get("extracted"):
            return False
        extracted = MeaningExtraction.model_validate(check["extracted"])
        control = by_id[check["id"]]
        if meaning_differences(
            QuestionMeaning.model_validate(control["expected"]), extracted.meaning
        ) or evidence_issues(control["query"], extracted):
            return False
        saved = verified_artifact(
            calibration.parent, check["call"], check["call_sha256"]
        )
        verify_extraction_call(
            saved,
            profile,
            graphs[control["graph_id"]],
            control["query"],
            check["extracted"],
        )
    return True


def distinct_reviewer(
    proposals: dict,
    profile: ModelProfile,
    student_model: str,
    student_endpoint: str | None = None,
) -> bool:
    # Distinct identifier is necessary, not proof of independent lineage. Local
    # aliases on the same server never qualify as an independent review.
    normalize = lambda value: value.casefold().split("/")[-1].replace("_", "-")
    reviewer = normalize(profile.model)
    others = [normalize(proposals["teacher_model"]), normalize(student_model)]
    if any(
        reviewer == other
        or reviewer.startswith(other + "-")
        or other.startswith(reviewer + "-")
        for other in others
    ):
        return False

    def server(value):
        parsed = urlsplit(value or "")
        host = parsed.hostname
        if host in {"localhost", "127.0.0.1", "::1"}:
            host = "loopback"
        return host, parsed.port or (443 if parsed.scheme == "https" else 80)

    return not (
        profile.provider == "local"
        and server(profile.base_url)
        in {
            server(proposals.get("teacher_endpoint")),
            server(student_endpoint),
        }
    )


async def review_candidates(
    settings: Settings,
    *,
    corpus: Path,
    candidates: Path,
    destination: Path,
    profile: ModelProfile,
    calibration: Path | None = None,
    data_dir: Path | None = None,
    allow_external: bool = False,
    allow_codex: bool = False,
    budget_usd: float | None = None,
) -> dict:
    manifest, graphs, proposals = load_proposals(corpus, candidates)
    calibrated = calibrated_profile(corpus, manifest, calibration, profile)
    distinct = distinct_reviewer(
        proposals, profile, settings.llm_model, settings.llm_base_url
    )
    if data_dir is not None and (
        data_dir.exists() or data_dir.resolve() == settings.data_root.resolve()
    ):
        raise ValueError("Replays require a new isolated runtime directory")
    if data_dir is not None and not settings.llm_enabled:
        raise ValueError("Live candidate replay requires the configured student model")
    budget = RequestBudget(
        maximum_usd=budget_usd, max_calls=len(proposals["candidates"])
    )
    report = {
        "schema_version": "1.0.0",
        "mode": "semantic_candidate_review",
        "started_at": utc_now().isoformat(),
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "proposals_sha256": HistoryStore.digest(candidates),
        "meaning_sha256": HistoryStore.digest(MEANING_PATH),
        "reviewer_contract_sha256": reviewer_contract_sha256(),
        "replay_contract_sha256": replay_contract_sha256(),
        "reviewer": profile.public(),
        "student_model": settings.llm_model,
        "reviewer_calibrated": calibrated,
        "distinct_reviewer": distinct,
        "calibration_sha256": HistoryStore.digest(calibration) if calibration else None,
        "training_started": False,
        "candidates": [],
        "scope": "Blinded meaning extraction plus deterministic source-contract comparison, novice wording checks and optional live execution. Same-model agreement cannot approve a training candidate.",
    }
    examples = {row["id"]: row for row in manifest["examples"]}
    async with LearningModel(
        settings,
        profile,
        budget,
        allow_external=allow_external,
        allow_codex=allow_codex,
    ) as model:
        _new_directory(destination)
        for index, proposal in enumerate(proposals["candidates"]):
            example = examples[proposal["example_id"]]
            reference = expected_meaning(example["task"])
            call = destination / "calls" / f"candidate-{index:02d}.json"
            row = {
                "id": proposal["id"],
                "example_id": example["id"],
                "proposal_sha256": digest(proposal),
                "query": proposal["query"],
                "expected_meaning": reference.model_dump(mode="json"),
                "wording_issues": wording_issues(proposal["query"], reference),
                "semantic_issues": [],
                "replay_issues": [],
                "training_eligible": False,
                "status": "quarantined",
            }
            print(f"Reviewing {proposal['id']}: {proposal['query']}", flush=True)
            try:
                extracted = await model.generate(
                    system=EXTRACTION_SYSTEM,
                    payload=blind_payload(
                        graphs[example["graph_id"]], proposal["query"]
                    ),
                    schema=MeaningExtraction,
                    artifact=call,
                )
                row["extracted"] = extracted.model_dump(mode="json")
                row["semantic_issues"] = meaning_differences(
                    reference, extracted.meaning
                ) + evidence_issues(proposal["query"], extracted)
            except ValueError as error:
                row["semantic_issues"] = [str(error)]
            if call.is_file():
                row.update(
                    call=str(call.relative_to(destination)),
                    call_sha256=HistoryStore.digest(call),
                )
            row["screening_passed"] = (
                not row["wording_issues"] and not row["semantic_issues"]
            )
            report["candidates"].append(row)
            report["budget"] = budget.public()
            HistoryStore.write(destination / "review.json", report)
    if data_dir is not None:
        report["data_directory"] = str(data_dir.resolve())
        async with agent_client(
            replace(settings, history_directory=None), data_dir=data_dir
        ) as (client, history):
            for row in report["candidates"]:
                if not row["screening_passed"]:
                    continue
                example = examples[row["example_id"]]
                terminal = Terminal(client, history_root=history, output=lambda _: None)
                await terminal.start(
                    domain_id=example["domain"], title=f"Paraphrase replay: {row['id']}"
                )
                file = next(
                    record
                    for record in manifest["graphs"]
                    if record["id"] == example["graph_id"]
                )
                await terminal.load(corpus / file["path"])
                print(f"Replaying {row['id']}", flush=True)
                try:
                    outcome = await terminal.ask(row["query"])
                except ClientError as error:
                    outcome = {**terminal.last_outcome, "error": str(error)}
                row["replay_issues"] = check_agent_outcome(
                    graphs[example["graph_id"]], example["task"], outcome
                )
                artifact = destination / "replays" / f"{row['id']}.json"
                HistoryStore.write(
                    artifact,
                    {
                        "query": row["query"],
                        "proposal_sha256": row["proposal_sha256"],
                        "example_id": row["example_id"],
                        "session_id": terminal.session_id,
                        "turn_id": terminal.turn_id,
                        "outcome": outcome,
                    },
                )
                row.update(
                    session_id=terminal.session_id,
                    turn_id=terminal.turn_id,
                    replay=str(artifact.relative_to(destination)),
                    replay_sha256=HistoryStore.digest(artifact),
                    replay_passed=not row["replay_issues"],
                )
                if row["replay_issues"]:
                    feedback = await terminal.feedback(
                        "; ".join(row["replay_issues"]),
                        "Preserve the independently specified meaning of this paraphrase and return the oracle-checked result.",
                        source="assistant_evaluation",
                    )
                    row["feedback_id"] = feedback["id"]
                HistoryStore.write(destination / "review.json", report)
    for row in report["candidates"]:
        blockers = (
            list(row["wording_issues"])
            + list(row["semantic_issues"])
            + list(row["replay_issues"])
        )
        if not calibrated:
            blockers.append("Reviewer has not passed the current semantic calibration")
        if not distinct:
            blockers.append(
                "Reviewer is the generating/student model or a same-server alias"
            )
        if not row.get("replay_passed"):
            blockers.append("No passing live replay")
        row["blockers"] = blockers
        row["training_eligible"] = not blockers
        row["status"] = "accepted_candidate" if not blockers else "quarantined"
    report.update(
        finished_at=utc_now().isoformat(),
        screened=sum(row["screening_passed"] for row in report["candidates"]),
        replayed=sum("replay_passed" in row for row in report["candidates"]),
        accepted=sum(row["training_eligible"] for row in report["candidates"]),
    )
    HistoryStore.write(destination / "review.json", report)
    return report
