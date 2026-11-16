# Source: https://pgraphbenchweb.vercel.app/assets/neo4j_stackoverflow.docx
# Copied: 2026-11-15
# Extracted verbatim from the published Word document; no script changes.
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path


EXPECTED_HEADER = [
    "id",
    "display_name",
    "about_me",
    "age",
    "creation_date",
    "last_access_date",
    "location",
    "reputation",
    "up_votes",
    "down_votes",
    "views",
    "profile_image_url",
    "website_url",
]

INTEGER_COLUMNS = {
    0: "id",
    3: "age",
    7: "reputation",
    8: "up_votes",
    9: "down_votes",
    10: "views",
}

NEO4J_INTEGER_MIN = -(2**63)
NEO4J_INTEGER_MAX = 2**63 - 1


def set_csv_field_size_limit() -> None:
    """Use the largest CSV field size supported by this Python build."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def clean_cell(value: str, *, strip_backslashes: bool = False) -> str:
    # Collapse newlines, carriage returns, tabs, and repeated whitespace so
    # each logical CSV record is also one physical line. Keep quotes,
    # apostrophes, commas, and backslashes as data; csv.writer will encode them
    # correctly according to the standard CSV format understood by Neo4j.
    value = " ".join(value.split())
    if strip_backslashes:
        # Neo4j's default legacy CSV mode treats a backslash immediately
        # before a quote as quote escaping, even in otherwise standard CSV.
        # Removing backslashes is a lossy compatibility fallback for users
        # who cannot set dbms.import.csv.legacy_quote_escaping=false.
        value = value.replace("\\", "")
    return value


def validate_numeric_cells(row: list[str], record_number: int) -> None:
    for index, name in INTEGER_COLUMNS.items():
        value = row[index].strip()
        if value == "":
            continue

        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError(
                f"record {record_number}: {name} is not an integer: {value!r}"
            ) from exc

        if not NEO4J_INTEGER_MIN <= number <= NEO4J_INTEGER_MAX:
            raise ValueError(
                f"record {record_number}: {name} is outside Neo4j's "
                f"64-bit integer range: {value!r}"
            )


def clean_users(
    input_path: Path,
    output_path: Path,
    *,
    force: bool,
    progress_every: int,
    strip_backslashes: bool,
) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    if output_path.exists() and not force:
        raise FileExistsError(
            f"{output_path} already exists; use --force to replace it after "
            "a successful conversion"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    set_csv_field_size_limit()

    temporary_name: str | None = None
    records = 0
    replacement_characters = 0

    try:
        with input_path.open(
            "r", encoding="utf-8", errors="replace", newline=""
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

                validate_numeric_cells(row, records)
                replacement_characters += sum(
                    cell.count("\ufffd") for cell in row
                )
                writer.writerow(
                    clean_cell(cell, strip_backslashes=strip_backslashes)
                    for cell in row
                )

                if progress_every and records % progress_every == 0:
                    print(f"Processed {records:,} records...", flush=True)

            outfile.flush()
            os.fsync(outfile.fileno())

        os.replace(temporary_name, output_path)
        temporary_name = None
        # Neo4j normally runs under a separate service account. Allow that
        # account to read the completed CSV while keeping writes owner-only.
        output_path.chmod(0o644)

    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    print(f"Complete: wrote {records:,} records to {output_path}")
    if replacement_characters:
        print(
            "Warning: invalid UTF-8 bytes produced "
            f"{replacement_characters:,} replacement characters.",
            file=sys.stderr,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Stack Overflow users.csv to standard, Neo4j-compatible CSV."
        )
    )
    parser.add_argument("input", type=Path, help="source users.csv")
    parser.add_argument("output", type=Path, help="destination users_clean.csv")
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
    parser.add_argument(
        "--strip-backslashes",
        action="store_true",
        help=(
            "remove backslashes for Neo4j installations that retain legacy "
            "backslash quote escaping; this is lossy"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        clean_users(
            args.input,
            args.output,
            force=args.force,
            progress_every=args.progress_every,
            strip_backslashes=args.strip_backslashes,
        )
    except (csv.Error, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
