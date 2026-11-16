# Source: https://pgraphbenchweb.vercel.app/assets/neo4j_stackoverflow.docx
# Copied: 2026-11-15
# Extracted verbatim from the published Word document; no script changes.
from __future__ import annotations
import argparse
import csv
import os
import re
import sys
import tempfile
from pathlib import Path

EXPECTED_HEADER = [
    "id",
    "text",
    "creation_date",
    "post_id",
    "user_id",
    "user_display_name",
    "score",
]

# Column index, column name, whether an empty value is allowed.
INTEGER_COLUMNS = [
    (0, "id", False),
    (3, "post_id", False),
    (4, "user_id", True),
    (6, "score", False),
]

NEO4J_INTEGER_MIN = -(2**63)
NEO4J_INTEGER_MAX = 2**63 - 1

BACKSLASHES_BEFORE_QUOTE = re.compile(r'\\+(?=")')
TRAILING_BACKSLASHES = re.compile(r"\\+$")

def set_csv_field_size_limit() -> None:
    """Use the largest CSV field size supported by this Python build."""
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
    optional: bool,
    record_number: int,
) -> None:
    value = value.strip()
    if value == "":
        if optional:
            return
        raise ValueError(
            f"record {record_number}: required integer {column} is empty"
        )

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

def clean_cell(value: str) -> tuple[str, int]:
    # Make every logical record one physical line while retaining ordinary
    # punctuation and ordinary backslashes used in code, regexes, and paths.
    value = " ".join(value.split())

    removed = 0

    def remove_run(match: re.Match[str]) -> str:
        nonlocal removed
        removed += len(match.group(0))
        return ""

    # Remove only backslashes that are dangerous under Neo4j's legacy quote
    # parser. Ordinary backslashes elsewhere remain unchanged.
    value = BACKSLASHES_BEFORE_QUOTE.sub(remove_run, value)
    value = TRAILING_BACKSLASHES.sub(remove_run, value)

    return value, removed

def clean_comments(
    input_path: Path,
    output_path: Path,
    *,
    force: bool,
    progress_every: int,
) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    if output_path.exists() and not force:
        raise FileExistsError(
            f"{output_path} already exists; use --force to replace it only "
            "after a successful conversion"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    set_csv_field_size_limit()

    temporary_name: str | None = None
    records = 0
    affected_records = 0
    removed_backslashes = 0
    replacement_characters = 0

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

            if header != EXPECTED_HEADER:
                raise ValueError(
                    f"unexpected header ({len(header)} columns): {header!r}"
                )
            writer.writerow(header)

            for row in reader:
                records += 1
                if len(row) != len(EXPECTED_HEADER):
                    raise ValueError(
                        f"record {records} (ending at physical line "
                        f"{reader.line_num}) has {len(row)} columns; "
                        f"expected {len(EXPECTED_HEADER)}"
                    )

                for index, column, optional in INTEGER_COLUMNS:
                    validate_integer(
                        row[index],
                        column=column,
                        optional=optional,
                        record_number=records,
                    )

                if row[2].strip() == "":
                    raise ValueError(
                        f"record {records}: required creation_date is empty"
                    )

                cleaned_row: list[str] = []
                removed_in_record = 0
                for cell in row:
                    replacement_characters += cell.count("\ufffd")
                    cleaned, removed = clean_cell(cell)
                    cleaned_row.append(cleaned)
                    removed_in_record += removed

                if removed_in_record:
                    affected_records += 1
                    removed_backslashes += removed_in_record

                writer.writerow(cleaned_row)

                if progress_every and records % progress_every == 0:
                    print(
                        f"Processed {records:,} records; "
                        f"modified {affected_records:,} records...",
                        flush=True,
                    )

            outfile.flush()
            os.fsync(outfile.fileno())

        os.replace(temporary_name, output_path)
        temporary_name = None
        # Neo4j normally runs under a separate service account.
        output_path.chmod(0o644)

    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    print(f"Complete: wrote {records:,} records to {output_path}")
    print(
        "Legacy quote compatibility: removed "
        f"{removed_backslashes:,} dangerous backslashes from "
        f"{affected_records:,} records"
    )
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
            "Convert Stack Overflow comments.csv to a CSV compatible with "
            "Neo4j's default legacy backslash quote mode."
        )
    )
    parser.add_argument("input", type=Path, help="source comments.csv")
    parser.add_argument(
        "output",
        type=Path,
        help="destination comments_clean.csv",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output only after conversion succeeds",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100_000,
        metavar="N",
        help="print progress every N records; use 0 to disable (default: 100000)",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    try:
        clean_comments(
            args.input,
            args.output,
            force=args.force,
            progress_every=args.progress_every,
        )
    except (csv.Error, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
