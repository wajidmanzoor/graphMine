#!/usr/bin/env python3
"""Prepare the exact publisher import paths, without connecting to a database.

Run with .database-workspace/import-venv/bin/python. Split inputs reuse
benchmark_import.Builder.source(), including its publisher part-set checks.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from source_pages import DATASETS, audit


CODE = Path(__file__).resolve().parents[2]
LAB_ROOT = Path(os.environ.get("GRAPHMINE_LAB_DATA_ROOT", "/data/labdata/wajid/graphmine_data"))
STACKOVERFLOW_CLEANED = {
    "posts_answers_clean.csv": "posts_answers.csv",
    "posts_questions_clean.csv": "posts_questions.csv",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def receipt(path, *, hash_content=True):
    metadata = path.with_name(path.name + ".verified.json")
    if not path.is_file() or not metadata.is_file():
        raise ValueError(f"Missing verified raw input: {path}")
    record = json.loads(metadata.read_text())
    size = record.get("size_bytes", record.get("bytes"))
    if size != path.stat().st_size or not record.get("sha256"):
        raise ValueError(f"Invalid source receipt: {metadata}")
    if hash_content and sha256(path) != record["sha256"]:
        raise ValueError(f"Source checksum differs from its receipt: {path}")
    return {"file": str(path), "receipt": str(metadata), "size_bytes": size, "sha256": record["sha256"]}


def source_parts(slug, filename):
    raw = LAB_ROOT / "datasets" / slug / "raw"
    direct = raw / filename
    if direct.is_file():
        return [direct]
    parts = sorted(p for p in raw.glob(filename + "*part_*")
                   if not p.name.endswith((".verified.json", ".partial")))
    if not parts:
        raise FileNotFoundError(f"{slug}: missing published input {filename} under {raw}")
    metadata = json.loads((raw.parent / "dataverse-metadata.json").read_text())
    expected = {row["dataFile"].get("originalFileName") or row["dataFile"]["filename"]
                for row in metadata["data"]["latestVersion"]["files"]}
    expected = {name for name in expected if name.startswith(filename) and "part_" in name}
    if {p.name for p in parts} != expected:
        raise ValueError(f"{slug}: incomplete publisher part set for {filename}")
    return parts


def builder(slug, directory):
    path = CODE / "deploy/database-workspace/benchmark_import.py"
    if not path.exists():
        path = CODE / "deploy/database-workspace/legacy/benchmark_import.py"
    spec = importlib.util.spec_from_file_location("benchmark_import", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The full constructor opens PostgreSQL and publishes the legacy catalog.
    # source() itself needs only these paths and log(); never run __init__ here.
    value = module.Builder.__new__(module.Builder)
    value.slug = slug
    value.raw = LAB_ROOT / "datasets" / slug / "raw"
    value.directory = directory
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return value


def link(target, source, *, import_root=None):
    source = source.resolve()
    original = source
    if import_root is not None:
        # APOC 5.26.32 checks the canonical path, rejecting symlinks to raw
        # files outside import/. A hard link inside import/ keeps the same
        # verified bytes/inode without another large copy. Published paths
        # remain symlinks, now resolving within the configured boundary.
        anchor = import_root / ".source-files" / hashlib.sha256(str(source).encode()).hexdigest() / source.name
        anchor.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if anchor.exists():
            if not anchor.samefile(source):
                raise ValueError(f"Existing import anchor is not the verified source: {anchor}")
        else:
            os.link(source, anchor)
        source = anchor
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        if target.resolve() != source.resolve():
            if import_root is not None and target.resolve() == original:
                target.unlink()
                target.symlink_to(source)
            elif not target.samefile(source):
                raise ValueError(f"Refusing to replace an import link: {target}")
    elif target.exists():
        raise ValueError(f"Refusing to overwrite an import file: {target}")
    else:
        target.symlink_to(source.resolve(), target_is_directory=source.is_dir())
    if not target.exists():
        raise ValueError(f"Import path does not resolve: {target}")


def posts_cleaner():
    directory = Path(__file__).parent / "stackoverflow/preprocessing"
    proof = json.loads((directory / "SOURCE.json").read_text())
    script = directory / "clean_posts_csv.py"
    record = next(item for item in proof["scripts"] if item["file"] == script.name)
    if sha256(script) != record["file_sha256"]:
        raise ValueError("Publisher CSV cleaner differs from the copied source")
    return script, record["file_sha256"]


def clean_posts(source, destination, source_hash):
    script, script_hash = posts_cleaner()
    metadata = destination.with_name(destination.name + ".source.json")
    if destination.exists():
        if not metadata.is_file():
            raise ValueError(f"Refusing to adopt a cleaned file without its provenance: {destination}")
        proof = json.loads(metadata.read_text())
        if (proof.get("source_sha256") != source_hash or proof.get("script_sha256") != script_hash
                or proof.get("output_sha256") != sha256(destination)):
            raise ValueError(f"Cleaned file provenance mismatch: {destination}")
        return proof
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Execute the publisher's exact command, with default cleaning options.
    # The publisher writes atomically and rejects malformed/truncated records.
    subprocess.run([sys.executable, str(script), str(source), str(destination)], check=True)
    cleaning = destination.with_name(destination.name + ".cleaning.json")
    result = json.loads(cleaning.read_text())
    proof = {"source": str(source), "source_sha256": source_hash, "script": str(script),
             "script_sha256": script_hash, "output_sha256": sha256(destination),
             "records": result["records"], "cleaning_report": str(cleaning), "options": "publisher defaults"}
    metadata.write_text(json.dumps(proof, indent=2) + "\n")
    metadata.chmod(0o600)
    return proof


def ldbc_plan():
    dataset = LAB_ROOT / "datasets/ldbc-snb"
    snapshots = list((dataset / "extracted").glob("**/initial_snapshot"))
    if len(snapshots) != 1:
        raise FileNotFoundError("Expected one extracted LDBC initial_snapshot directory")
    snapshot = snapshots[0]
    directory = Path(__file__).parent / "ldbc-snb"
    source = audit("ldbc-snb")
    reference = directory / source["reference_scripts"][0]["file"]
    mappings = re.findall(r"^add_(nodes|rels)\s+([A-Za-z_:]+)\s+(static|dynamic)\s+([A-Za-z_]+)",
                          reference.read_text(), flags=re.M)
    if len(mappings) != 31 or sum(kind == "nodes" for kind, *_ in mappings) != 8:
        raise ValueError("Publisher bulk mapping changed: expected eight node and 23 relationship groups")
    header_proof = json.loads((directory / "reference/headers-source.json").read_text())
    headers = {item["path"]: item for item in header_proof["files"]}
    records = []
    for kind, labels, sub, entity in mappings:
        group = snapshot / sub / entity
        header = directory / f"reference/headers/{sub}/{entity}.csv"
        body = header.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if digest != headers[f"headers/{sub}/{entity}.csv"]["git_blob_sha"]:
            raise ValueError(f"Reference header changed: {header}")
        parts = sorted(group.glob("part-*.csv*"))
        if not parts:
            raise FileNotFoundError(f"No LDBC CSV partitions: {group}")
        raw_header = None
        for part in parts:
            opener = gzip.open if part.suffix == ".gz" else open
            with opener(part, "rb") as stream:
                first = stream.readline().rstrip(b"\r\n")
            if not first:  # The publisher explicitly allows empty shards.
                continue
            if raw_header is None:
                raw_header = first
                if len(first.split(b"|")) != len(body.strip().split(b"|")) or not re.fullmatch(rb"[A-Za-z0-9_|]+", first):
                    raise ValueError(f"Unexpected LDBC raw header: {part}")
            elif first != raw_header:
                raise ValueError(f"LDBC shard headers differ within {entity}: {part}")
        if raw_header is None:
            raise ValueError(f"No header available for LDBC group: {group}")
        records.append({"kind": kind, "labels_or_type": labels, "subdirectory": sub, "entity": entity,
                        "header": str(header), "header_sha256": hashlib.sha256(body).hexdigest(),
                        "raw_header": raw_header.decode(), "parts": [str(p) for p in parts]})
    return {"groups": records, "headers_commit": header_proof["commit"], "raw_snapshot": str(snapshot)}


def strip_ldbc_header(source, target, raw_header):
    """Preserve every data byte; remove only the verified first header line."""
    proof_path = target.with_name(target.name + ".source.json")
    source_hash = sha256(source)
    if target.exists():
        if not proof_path.is_file():
            raise ValueError(f"Prepared LDBC shard has no provenance: {target}")
        proof = json.loads(proof_path.read_text())
        if (proof.get("source_sha256") != source_hash or proof.get("raw_header") != raw_header
                or proof.get("output_sha256") != sha256(target)):
            raise ValueError(f"Prepared LDBC shard failed its checksum check: {target}")
        return proof
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rb") as incoming, temporary.open("wb") as outgoing:
        first = incoming.readline()
        if first and first.rstrip(b"\r\n") != raw_header.encode():
            raise ValueError(f"Unexpected first line in LDBC shard: {source}")
        while chunk := incoming.read(16 * 1024 * 1024):
            outgoing.write(chunk)
            digest.update(chunk)
    temporary.replace(target)
    proof = {"source": str(source), "source_sha256": source_hash, "raw_header": raw_header,
             "header_removed": bool(first), "output_sha256": digest.hexdigest(),
             "output_bytes": target.stat().st_size}
    proof_path.write_text(json.dumps(proof, indent=2) + "\n")
    proof_path.chmod(0o600)
    return proof


def ldbc_inputs(root, *, hash_content):
    dataset = LAB_ROOT / "datasets/ldbc-snb"
    proof = receipt(dataset / "bi-sf100-composite-projected-fk.tar.zst", hash_content=hash_content)
    plan = ldbc_plan()
    prepared = root.parent / "source-cache/headerless"
    records = []
    total = sum(len(group["parts"]) for group in plan["groups"])
    completed = 0
    for group in plan["groups"]:
        relative = Path(group["subdirectory"]) / group["entity"]
        link(root / "headers" / relative.with_suffix(".csv"), Path(group["header"]))
        for name in group["parts"]:
            source = Path(name)
            filename = source.name.removesuffix(".gz")
            target = prepared / relative / filename
            record = strip_ldbc_header(source, target, group["raw_header"])
            link(root / "csv/initial_snapshot" / relative / filename, target)
            records.append({"import_path": str(Path("csv/initial_snapshot") / relative / filename), **record})
            completed += 1
            if completed % 20 == 0 or completed == total:
                print(f"LDBC: prepared {completed}/{total} shards; original data rows unchanged", flush=True)
    return {"archive": proof, "plan": plan, "partitions": records,
            "note": "The downloaded archive contains column-name headers. Derived shards remove only each verified first header line; the pinned typed Neo4j headers and the publisher's labels/types are unchanged."}


def prepare(slug, *, check_only=False, hash_content=True):
    published = audit(slug)
    instance = LAB_ROOT / "neo4j-instances" / slug
    root = instance / "import"
    if slug == "ldbc-snb":
        if check_only:
            dataset = LAB_ROOT / "datasets/ldbc-snb"
            receipt(dataset / "bi-sf100-composite-projected-fk.tar.zst", hash_content=False)
            plan = ldbc_plan()
            return {"id": slug, "preflight": "passed", "bulk_groups": len(plan["groups"]),
                    "raw_partitions": sum(len(g["parts"]) for g in plan["groups"]), "header_preparation_required": True}
        report = {"id": slug, "import_root": str(root), "bulk": ldbc_inputs(root, hash_content=hash_content)}
    else:
        inputs = []
        errors = []
        for filename in published["required_files"]:
            relative = Path(filename)
            if relative.is_absolute() or ".." in relative.parts or "$" in filename:
                raise ValueError(f"Unsafe or unresolved import filename: {filename}")
            try:
                original = STACKOVERFLOW_CLEANED.get(relative.name, relative.name) if slug == "stackoverflow" else relative.name
                if original != relative.name:
                    posts_cleaner()
                parts = source_parts(slug, original)
                for part in parts:
                    receipt(part, hash_content=False)
                inputs.append((relative, original, parts))
            except (ValueError, OSError) as error:
                errors.append(str(error))
        if errors:
            raise ValueError("Import preparation stopped:\n" + "\n".join(errors))
        if check_only:
            return {"id": slug, "preflight": "passed", "input_files": len(inputs)}
        joined = builder(slug, instance / "source-cache")
        records = []
        for relative, original, parts in inputs:
            proofs = [receipt(part, hash_content=hash_content) for part in parts]
            source = joined.source(original)
            if len(parts) > 1:
                expected = hashlib.sha256()
                for part in parts:
                    with part.open("rb") as stream:
                        while block := stream.read(16 * 1024 * 1024):
                            expected.update(block)
                checksum = sha256(source)
                if checksum != expected.hexdigest():
                    raise ValueError(f"Joined source is not the exact concatenation of its verified parts: {source}")
            else:
                checksum = proofs[0]["sha256"]
            preprocessing = None
            if original != relative.name:
                destination = instance / "source-cache/cleaned" / relative.name
                preprocessing = clean_posts(source, destination, checksum)
                source, checksum = destination, preprocessing["output_sha256"]
            link(root / relative, source, import_root=root)
            records.append({"import_path": str(relative), "source": str(source), "size_bytes": source.stat().st_size,
                            "sha256": checksum, "parts": proofs, "publisher_preprocessing": preprocessing})
        report = {"id": slug, "import_root": str(root), "files": records}
    report.update(prepared_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  source_page_sha256=published["page_sha256"], content_hashes_checked=hash_content)
    destination = instance / "import-receipt.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=DATASETS)
    parser.add_argument("--check-only", action="store_true", help="Check all names and receipts before copying anything")
    args = parser.parse_args()
    result = prepare(args.dataset, check_only=args.check_only)
    print(json.dumps({k: v for k, v in result.items() if k not in {"files", "bulk"}}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
