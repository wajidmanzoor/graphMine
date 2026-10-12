#!/usr/bin/env python3
"""Replay planner regressions without changing historical suites or scores.

Uses the existing end-to-end grader and native workers. Model settings and
native paths come from the same environment as evaluate_analytics_holdout.py.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import replace
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--baseline-commit")
    parser.add_argument("--scope", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="graphmine-planner-check-") as directory:
        temporary = Path(directory)
        if args.baseline_commit:
            archive = subprocess.check_output(
                ["git", "archive", args.baseline_commit, "agent"], cwd=root
            )
            with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
                stream.extractall(temporary / "source", filter="data")
            os.environ["GRAPHMINE_APPLICATION_SOURCE"] = str(temporary / "source/agent")

        import evaluate_analytics_holdout as harness
        import graphmine_agent.analytics_planning as planning
        from graphmine_agent.config import Settings

        suite = json.loads(args.suite.read_text())
        original_hash = harness.digest(suite)
        if args.case:
            unknown = set(args.case) - {case["id"] for case in suite["cases"]}
            if unknown:
                raise ValueError(f"Unknown cases: {sorted(unknown)}")
            suite["cases"] = [c for c in suite["cases"] if c["id"] in args.case]
        suite["scope"] = args.scope
        traces = []

        class CapturedPlanner(planning.AnalyticsPlanner):
            async def _generate(self, stage, payload, schema):
                result = await super()._generate(stage, payload, schema)
                traces.append(
                    {
                        "question": payload["question"],
                        "stage": stage,
                        "response": result,
                        "validation_error": payload.get("validation_error"),
                    }
                )
                return result

        planning.AnalyticsPlanner = CapturedPlanner
        files = [
            Path(__file__),
            Path(harness.__file__),
            args.suite,
            *sorted((harness.APP / "graphmine_agent").rglob("*.py")),
            root / "catalog/native_execution_evidence.json",
        ]

        def fingerprints():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

        before = fingerprints()
        settings = replace(Settings.from_env(root), data_root=temporary / "data")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = asyncio.run(harness.evaluate(settings, suite, args.output))
        report.update(
            original_suite_sha256=original_hash,
            selected_cases=args.case,
            baseline_commit=args.baseline_commit,
            generation_responses=traces,
            source_files=before,
            sources_unchanged_during_run=before == fingerprints(),
            model={
                "name": settings.analytics_planner_model or settings.llm_model,
                "base_revision": os.getenv("GRAPHMINE_LLM_REVISION"),
                "reasoning_effort": settings.analytics_reasoning_effort,
                "thinking_token_budget": settings.analytics_thinking_token_budget,
                "max_completion_tokens": settings.llm_plan_max_tokens,
                "temperature": 0,
                "seed": 0,
            },
        )
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        assert report["sources_unchanged_during_run"]
        print(report["passed"], "/", report["total"], flush=True)


if __name__ == "__main__":
    main()
