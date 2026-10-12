"""Collect an offline, unreviewed failure queue; never trains or calls a model."""

import argparse
import json
from pathlib import Path

from graphmine_agent.config import Settings
from graphmine_agent.learning.catalog_compare import write_new_report
from graphmine_agent.learning.failure_candidates import collect_failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-suite", type=Path)
    parser.add_argument("--workflow-report", type=Path, action="append", default=[])
    parser.add_argument("--realworld-corpus", type=Path)
    parser.add_argument("--application-comparison", type=Path)
    parser.add_argument("--archived-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve the existing queue; choose a new output path")
    report = collect_failures(
        Settings.from_env(Path(__file__).resolve().parents[2]),
        workflow_suite=args.workflow_suite,
        workflow_reports=args.workflow_report,
        corpus=args.realworld_corpus,
        comparison=args.application_comparison,
        archived_reports=args.archived_report,
    )
    write_new_report(args.output, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "candidate_count",
                    "counts_by_kind",
                    "training_eligible",
                    "training_started",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
