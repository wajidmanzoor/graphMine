"""Build the handoff from completed checks and actual local optimizer evidence."""

from __future__ import annotations

import argparse
import json
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.review import replay_contract_sha256
from graphmine_agent.models import utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Preserve existing checkpoints; choose a new report path")
    root = Path(__file__).resolve().parents[2]
    learning = root / ".graphmine-learning"
    paths = {
        "real_corpus": learning / "real-world-corpus-v5/manifest.json",
        "questions": learning / "real-world-questions-v3/questions.json",
        "real_native": learning / "real-world-native-v4.json",
        "live_student": learning / "real-world-student-v2.json",
        "synthetic_corpus": learning / "finetune-corpus-v2/manifest.json",
        "synthetic_audit": learning / "finetune-native-v1.json",
        "training_export": learning / "finetune-routing-data-v1/provenance.json",
        "training_config": args.run / "run.json",
        "adapter_verification": args.run / "adapter-verification.json",
        "training_environment": args.run / "installed-packages.json",
        "previous_training_attempts": args.run / "previous-attempts.json",
        "visual_inspection": learning / "real-world-visual-fixes-v1/inspection.json",
        "qualitative_feedback": learning / "real-world-visual-fixes-v1/feedback.json",
        "api_restart": root / ".graphmine-v1/api-restart-fixes-2026-10-03.json",
    }
    evidence = {name: json.loads(path.read_text()) for name, path in paths.items()}
    native = evidence["real_native"]
    student = evidence["live_student"]
    questions = evidence["questions"]
    audit = evidence["synthetic_audit"]
    config = evidence["training_config"]
    status = json.loads((args.run / "status.json").read_text())
    for report in (native, student, audit):
        assert report.get("finished_at") and report["passed"] == report["total"]
    assert student["expected_total"] == student["total"]
    assert student["replay_contract_sha256"] == replay_contract_sha256()
    assert questions["reviewer_qualified"] and all(
        x["passed"] for x in questions["calibration"]
    )
    assert status["training_started"] and status["global_step"] >= 2
    assert status["phase"] in {"training", "completed"}
    assert evidence["adapter_verification"]["nonzero_lora_b_tensors"] > 0
    assert evidence["adapter_verification"]["all_finite"]
    assert not evidence["training_export"]["quarantine"]
    test_path = learning / "fixes-validation-v1.xml"
    tests = list(ET.parse(test_path).iter("testcase"))
    assert tests and all(not list(t) for t in tests)
    times = [s["elapsed_seconds"] for t in student["trials"] for s in t["steps"]]
    report = {
        "schema_version": "1.0.0",
        "created_at": utc_now().isoformat(),
        "scope": "Fixes verified on inspected development cases; local routing QLoRA started, not deployed. Not a claim that every system issue or novice-usability requirement is solved.",
        "fixes": [
            "Unchecked planner assumptions moved to explicitly unverified diagnostics, not displayed facts.",
            "Exact-field filter counts/ranges retained; score and ascore cannot be interchanged in server facts.",
            "Valid empty selections complete with a computed empty answer.",
            "Application-layer filtering distinguished from unsupported weighted computation, with bounded re-review and unchanged safety gates.",
            "Source names/attributes joined into readable tables and answer-only, application-colored networks.",
            "Plain-language clarification guidance and validated follow-up actions.",
            "Production routing prompt and export input contract shared.",
        ],
        "verification": {
            "pytest_passed": len(tests),
            "pytest_xml": str(test_path.relative_to(root)),
            "pytest_xml_sha256": HistoryStore.digest(test_path),
            "lint": "Changed application and added/edited tests pass Ruff. Full tests directory retains three pre-existing lint findings in test_api_flow.py and test_release_artifacts.py; unrelated files preserved.",
            "real_native": {"passed": native["passed"], "total": native["total"]},
            "live_student": {
                "passed_turns": student["passed"],
                "total_turns": student["total"],
                "passed_workflow_trials": student["workflows_passed"],
                "workflow_trials": len(student["trials"]),
                "repeats": student["repeats"],
                "inference_profile": student["inference_profile"],
                "median_seconds": statistics.median(times),
                "maximum_seconds": max(times),
            },
            "comparison_caution": "Prior 38/42 report used different reviewed questions, fewer admitted cases and a different planning-reasoning profile. These are not a controlled before/after accuracy or speed comparison.",
            "visual_reports_inspected": len(evidence["visual_inspection"]),
            "additional_assistant_feedback": len(evidence["qualitative_feedback"]),
        },
        "teacher_reviewer": {
            "provider": "ChatGPT-authenticated Codex CLI",
            "teacher": questions["teacher"],
            "reviewer": questions["reviewer"],
            "calls": questions["budget"]["calls"],
            "call_ceiling": questions["maximum_model_calls"],
            "calibration_passed": len(questions["calibration"]),
            "screened": questions["screened"],
            "quarantined": questions["quarantined"],
            "quarantine_reasons": [
                {"case_id": x["case_id"], "issues": x["issues"]}
                for x in questions["candidates"]
                if x["issues"]
            ],
            "paid_api_fallback": False,
            "evaluation_questions_used_for_training": False,
        },
        "training": {
            "run_directory": str(args.run.resolve().relative_to(root)),
            "base_model": config["base_model"],
            "base_revision": config["base_revision"],
            "scope": config["scope"],
            "data": config["data"],
            "hyperparameters": config["hyperparameters"],
            "native_audit_types": dict(
                Counter(x["verification"] for x in audit["examples"])
            ),
            "synthetic_test_cases_excluded": sum(
                x["split"] == "test" for x in evidence["synthetic_corpus"]["examples"]
            ),
            "real_sources_excluded": ["SocioPatterns", "STRING", "OpenFlights"],
            "state_at_handoff": status,
            "deployed": False,
            "status_file_is_mutable": True,
            "systemd_unit": f"graphmine-{args.run.name}.service",
        },
        "deployment": evidence["api_restart"],
        "remaining": [
            "Complete and evaluate the adapter; training loss is not agent-quality evidence.",
            "Empty-result card labels and domain-specific grouping caveats need further polish; feedback is saved.",
            "Larger real graphs, concurrency, GPU contention and actual novice-user task studies remain unvalidated.",
            "Expand automatic teacher-reviewed language, multistep workflows and untouched holdout coverage before promotion.",
        ],
        "guidance": "Evaluation-first and separate training/validation data, following https://developers.openai.com/api/docs/guides/fine-tuning-best-practices ; this is local Qwen training, not an OpenAI hosted fine-tune.",
        "artifacts": {
            name: {
                "path": str(path.resolve().relative_to(root)),
                "sha256": HistoryStore.digest(path),
            }
            for name, path in paths.items()
        },
    }
    HistoryStore.write(args.output, report)
    print(
        json.dumps(
            {
                "report": str(args.output),
                "passed_turns": student["passed"],
                "optimizer_steps": status["global_step"],
                "phase": status["phase"],
            }
        )
    )


if __name__ == "__main__":
    main()
