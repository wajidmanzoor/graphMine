"""Source fidelity and raw-data preservation checks; no running databases needed."""

from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import sys

import pytest


TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
import source_pages
import prepare_import_dir as preparation


def verified(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.with_name(path.name + ".verified.json").write_text(json.dumps({
        "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    }))


def test_copied_workloads_match_the_archived_pages():
    for slug in source_pages.DATASETS:
        source_pages.audit(slug)


def test_gql_alternatives_do_not_become_neo4j_queries():
    html = '''<h3>Schema Diagram and Graph Statistics</h3>
    <table><tr><td>User</td><td>1</td></tr></table>
    <table><tr><td>FRIEND</td><td>0</td></tr></table>
    <h3>Data Loading</h3><h4>Nodes</h4>
    <div class="code-wrapper"><div class="code-header"><span>cypher</span></div>
    <pre>CREATE (:User)</pre></div>
    <h3>Queries</h3><h4>Q1. Friends</h4>
    <div class="code-wrapper"><div class="code-header"><span>cypher</span></div>
    <pre>MATCH (start:User) RETURN start</pre></div>
    <div class="code-wrapper"><div class="code-header"><span>gql</span></div>
    <pre>MATCH SHORTEST (start:Other) RETURN start</pre></div>'''
    files, manifest = source_pages.artifacts("yelp", html, "https://example.test/source", "2026-11-15")
    assert "MATCH (start:User) RETURN start" in files["queries/Q01.cypher"]
    assert "Other" not in files["queries/Q01.cypher"]
    assert len(manifest["queries"][0]["source_blocks"]) == 1


def test_import_symlinks_resolve_inside_root_without_copying_source_bytes(tmp_path):
    source = tmp_path / "raw.json"
    source.write_bytes(b'{"id": 1}\n')
    root = tmp_path / "import"
    target = root / "yelp/data.json"
    preparation.link(target, source, import_root=root)
    assert target.is_symlink()
    assert target.resolve().is_relative_to(root)
    assert target.samefile(source)
    before = source.read_bytes()
    preparation.link(target, source, import_root=root)
    assert source.read_bytes() == before


def test_original_external_import_alias_can_be_anchored_without_touching_data(tmp_path):
    source = tmp_path / "raw.json"
    source.write_bytes(b"original")
    root = tmp_path / "import"
    target = root / "data.json"
    preparation.link(target, source)
    preparation.link(target, source, import_root=root)
    assert target.resolve().is_relative_to(root)
    assert source.read_bytes() == b"original"


def test_receipt_detects_equal_size_content_tampering(tmp_path):
    path = tmp_path / "raw.csv"
    verified(path, b"id\n1\n")
    path.write_bytes(b"id\n2\n")
    with pytest.raises(ValueError, match="checksum"):
        preparation.receipt(path)


def test_missing_receipt_stops_before_import(tmp_path):
    path = tmp_path / "raw.csv"
    path.write_bytes(b"id\n1\n")
    with pytest.raises(ValueError, match="Missing verified"):
        preparation.receipt(path)


def test_missing_split_part_is_rejected_even_when_other_parts_have_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "LAB_ROOT", tmp_path)
    raw = tmp_path / "datasets/yelp/raw"
    verified(raw / "users.json.part_aa", b'{"id":')
    (raw.parent / "dataverse-metadata.json").write_text(json.dumps({"data": {"latestVersion": {"files": [
        {"dataFile": {"filename": "users.json.part_aa"}},
        {"dataFile": {"filename": "users.json.part_ab"}},
    ]}}}))
    with pytest.raises(ValueError, match="incomplete"):
        preparation.source_parts("yelp", "users.json")
    verified(raw / "users.json.part_ab", b'1}\n')
    assert b"".join(p.read_bytes() for p in preparation.source_parts("yelp", "users.json")) == b'{"id":1}\n'


def test_existing_import_file_and_different_link_are_never_replaced(tmp_path):
    original, other, target = (tmp_path / name for name in ("original", "other", "import.csv"))
    original.write_bytes(b"old data")
    other.write_bytes(b"new data")
    target.write_bytes(b"existing import")
    with pytest.raises(ValueError, match="overwrite"):
        preparation.link(target, other)
    assert target.read_bytes() == b"existing import"
    target.unlink()
    target.symlink_to(original)
    with pytest.raises(ValueError, match="replace"):
        preparation.link(target, other)
    assert target.resolve() == original


def test_ldbc_preparation_preserves_all_bytes_after_the_header(tmp_path):
    source, target = tmp_path / "part.csv.gz", tmp_path / "prepared.csv"
    payload = b'id|content\r\n1|"a\nquoted, multiline value"\r\n2|another\\value\n'
    with gzip.open(source, "wb") as stream:
        stream.write(payload)
    original = source.read_bytes()
    proof = preparation.strip_ldbc_header(source, target, "id|content")
    assert source.read_bytes() == original
    assert target.read_bytes() == payload.split(b"\n", 1)[1]
    assert proof["header_removed"] is True
    assert preparation.strip_ldbc_header(source, target, "id|content") == proof
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        preparation.strip_ldbc_header(source, target, "id|content")


def test_ldbc_first_record_is_not_discarded_if_a_header_is_missing(tmp_path):
    source, target = tmp_path / "part.csv.gz", tmp_path / "prepared.csv"
    with gzip.open(source, "wb") as stream:
        stream.write(b"42|actual data\n")
    with pytest.raises(ValueError, match="first line"):
        preparation.strip_ldbc_header(source, target, "id|content")
    assert not target.exists()


def test_legitimate_empty_ldbc_shards_are_preserved(tmp_path):
    source, target = tmp_path / "part.csv.gz", tmp_path / "prepared.csv"
    with gzip.open(source, "wb"):
        pass
    proof = preparation.strip_ldbc_header(source, target, "id|content")
    assert target.read_bytes() == b""
    assert proof["header_removed"] is False


def test_publisher_cleaner_provenance_prevents_adopting_an_unknown_output(tmp_path):
    source, target = tmp_path / "original.csv", tmp_path / "cleaned.csv"
    source.write_bytes(b"id,body\n1,hello\n")
    target.write_bytes(b"id,body\n2,other\n")
    with pytest.raises(ValueError, match="without its provenance"):
        preparation.clean_posts(source, target, preparation.sha256(source))


def test_publisher_cleaner_uses_defaults_and_keeps_the_original(tmp_path):
    source, target = tmp_path / "original.csv", tmp_path / "cleaned.csv"
    original = b'id,body\n1,"line one\nline two"\n'
    source.write_bytes(original)
    proof = preparation.clean_posts(source, target, preparation.sha256(source))
    assert source.read_bytes() == original
    assert b"line one\nline two" in target.read_bytes()
    assert proof["records"] == 1
    assert proof["options"] == "publisher defaults"
    assert preparation.clean_posts(source, target, preparation.sha256(source)) == proof
