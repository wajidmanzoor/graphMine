# Source: https://pgraphbenchweb.vercel.app/assets/neo4j_stackoverflow.docx
# Copied: 2026-11-15
# Extracted verbatim from the published Word document; no script changes.
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

INTEGER_COLUMNS = {
    "id",
    "accepted_answer_id",
    "answer_count",
    "comment_count",
    "favorite_count",
    "last_editor_user_id",
    "owner_user_id",
    "parent_id",
    "post_type_id",
    "score",
    "view_count",
    "count",
    "excerpt_post_id",
    "wiki_post_id",
    "src",
    "dst",
    "link_type_id",
    "post_id",
    "related_post_id",
    "user_id",
    "vote_type_id",
    "class",
}

DATE_COLUMNS = {
    "community_owned_date",
    "creation_date",
    "last_access_date",
    "last_activity_date",
    "last_edit_date",
    "date",
}

DATE_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)? UTC$"
)

NEO4J_INTEGER_MIN = -(2**63)
NEO4J_INTEGER_MAX = 2**63 - 1

# Neo4j's default LOAD CSV behavior treats a backslash immediately before a
# quote as quote escaping. These are the only backslashes this script removes.
BACKSLASHES_BEFORE_QUOTE = re.compile(r'\\+(?=")')
TRAILING_BACKSLASHES = re.compile(r"\\+$")
EXAMPLE_LIMIT = 20

def set_csv_field_size_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10

def validate_integer(
    value: str,
    *,
    column: str,
    record_number: int,
) -> None:
    value = value.strip()
    if value == "":
        return
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(
            f"record {record_number}: {column} is not an integer: {value!r}"
        ) from exc
    if not NEO4J_INTEGER_MIN <= number <= NEO4J_INTEGER_MAX:
        raise ValueError(
            f"record {record_number}: {column} is outside Neo4j's "
            f"64-bit integer range: {value!r}"
        )

def validate_date(
    value: str,
    *,
    column: str,
    record_number: int,
) -> None:
    value = value.strip()
    if value and DATE_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"record {record_number}: {column} has an unexpected date "
            f"format: {value!r}"
        )

def clean_cell(
    value: str,
    *,
    single_line: bool,
) -> tuple[str, int]:
    if single_line:
        # Optional lossy mode: collapse newlines, tabs, and repeated spaces.
        value = " ".join(value.split())

    removed = 0

    def remove_run(match: re.Match[str]) -> str:
        nonlocal removed
        removed += len(match.group(0))
        return ""

    # Remove complete runs so values such as \\\" cannot leave another
    # backslash immediately before the quote after a single replacement.
    value = BACKSLASHES_BEFORE_QUOTE.sub(remove_run, value)
    value = TRAILING_BACKSLASHES.sub(remove_run, value)
    return value, removed

def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)

def clean_csv(
    input_path: Path,
    output_path: Path,
    *,
    force: bool,
    progress_every: int,
    single_line: bool,
    report_path: Path,
) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    if output_path.exists() and not force:
        raise FileExistsError(
            f"{output_path} already exists; use --force to replace it only "
            "after a successful conversion"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    set_csv_field_size_limit()

    temporary_name: str | None = None
    records = 0
    affected_records = 0
    affected_cells = 0
    removed_backslashes = 0
    ordinary_backslashes_preserved = 0
    replacement_characters = 0
    examples: list[dict[str, Any]] = []
    started = time.time()

    try:
        with input_path.open(
            "r", encoding="utf-8", errors="strict", newline=""
        ) as infile, tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as outfile:
            temporary_name = outfile.name
            reader = csv.reader(infile, strict=True)
            writer = csv.writer(
                outfile,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\n",
            )

            try:
                header = next(reader)
            except StopIteration as exc:
                raise ValueError("input CSV is empty") from exc

            if not header:
                raise ValueError("header is empty")
            if any(name == "" for name in header):
                raise ValueError(f"header contains a blank column: {header!r}")
            if len(set(header)) != len(header):
                raise ValueError(
                    f"header contains duplicate columns: {header!r}"
                )
            writer.writerow(header)

            integer_indexes = [
                (index, name)
                for index, name in enumerate(header)
                if name in INTEGER_COLUMNS
            ]
            date_indexes = [
                (index, name)
                for index, name in enumerate(header)
                if name in DATE_COLUMNS
            ]

            for row in reader:
                records += 1
                if len(row) != len(header):
                    raise ValueError(
                        f"record {records} (ending at physical line "
                        f"{reader.line_num}) has {len(row)} columns; "
                        f"expected {len(header)}"
                    )

                for index, column in integer_indexes:
                    validate_integer(
                        row[index],
                        column=column,
                        record_number=records,
                    )
                for index, column in date_indexes:
                    validate_date(
                        row[index],
                        column=column,
                        record_number=records,
                    )

                cleaned_row: list[str] = []
                removed_in_record = 0
                for index, cell in enumerate(row):
                    replacement_characters += cell.count("\ufffd")
                    original_backslashes = cell.count("\\")
                    cleaned, removed = clean_cell(
                        cell,
                        single_line=single_line,
                    )
                    if removed:
                        affected_cells += 1
                        if len(examples) < EXAMPLE_LIMIT:
                            examples.append(
                                {
                                    "record": records,
                                    "physical_line": reader.line_num,
                                    "column": header[index],
                                    "removed_backslashes": removed,
                                    "original_excerpt": cell[:300],
                                }
                            )
                    removed_in_record += removed
                    ordinary_backslashes_preserved += (
                        original_backslashes - removed
                    )
                    cleaned_row.append(cleaned)

                if removed_in_record:
                    affected_records += 1
                    removed_backslashes += removed_in_record

                writer.writerow(cleaned_row)

                if progress_every and records % progress_every == 0:
                    print(
                        f"Processed {records:,} records; "
                        f"modified {affected_records:,}; "
                        f"elapsed {time.time() - started:.1f}s",
                        flush=True,
                    )

            outfile.flush()
            os.fsync(outfile.fileno())

        os.replace(temporary_name, output_path)
        temporary_name = None
        output_path.chmod(0o644)

    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "header": header,
        "records": records,
        "single_line_mode": single_line,
        "affected_records": affected_records,
        "affected_cells": affected_cells,
        "removed_dangerous_backslashes": removed_backslashes,
        "ordinary_backslashes_preserved": ordinary_backslashes_preserved,
        "replacement_characters": replacement_characters,
        "elapsed_seconds": round(time.time() - started, 1),
        "examples": examples,
    }
    write_json_atomic(report_path, report)

    print(f"Complete: wrote {records:,} records to {output_path}")
    print(
        f"Removed {removed_backslashes:,} dangerous backslashes from "
        f"{affected_cells:,} cells in {affected_records:,} records"
    )
    print(
        f"Preserved {ordinary_backslashes_preserved:,} ordinary backslashes"
    )
    print(f"Report: {report_path}")
    if replacement_characters:
        print(
            "Notice: input contained "
            f"{replacement_characters:,} existing Unicode replacement "
            "characters.",
            file=sys.stderr,
        )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clean any standard CSV for Neo4j LOAD CSV while retaining "
            "Neo4j's default legacy backslash quote configuration."
        )
    )
    parser.add_argument("input", type=Path, help="source CSV")
    parser.add_argument("output", type=Path, help="clean destination CSV")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output only after conversion succeeds",
    )
    parser.add_argument(
        "--single-line",
        action="store_true",
        help=(
            "collapse embedded whitespace so each record is one physical "
            "line; this changes body/text formatting"
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100_000,
        metavar="N",
        help="print progress every N records; use 0 to disable",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="JSON report path (default: OUTPUT.cleaning.json)",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    report_path = args.report or Path(str(args.output) + ".cleaning.json")
    try:
        clean_csv(
            args.input,
            args.output,
            force=args.force,
            progress_every=args.progress_every,
            single_line=args.single_line,
            report_path=report_path,
        )
    except (csv.Error, OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
