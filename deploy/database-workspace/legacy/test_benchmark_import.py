"""Small source-integrity checks; run with the benchmark import environment."""

import csv
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
from pathlib import Path

import duckdb

from benchmark_import import Builder, publish_catalog
from benchmark_parquet import write_parquet


class RecordingDatabase:
    def __init__(self):
        self.fragments = []

    def execute(self, query, parameters=None):
        if "INSERT INTO graphmine_catalog.source_fragments" in query:
            self.fragments.append(parameters)
        return Mock(fetchone=lambda: None)


class ImportRecoveryTest(unittest.TestCase):
    def test_installed_store_retry_repairs_catalog_only_after_verification(self):
        import importlib.util
        from benchmark_import import graph_signature
        spec = importlib.util.spec_from_file_location("build_benchmark_graphs", Path(__file__).with_name("build-benchmark-graphs.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "imports" / "yelp"
            directory.mkdir(parents=True)
            manifest = {"id": "yelp", "graph_label": "GM_Yelp", "node_count": 2, "tables": [
                {"name": "people", "kind": "nodes", "rows": 2, "key": "id"},
            ]}
            (directory / "manifest.json").write_text(json.dumps(manifest))
            receipt = {"nodes": 2, "relationships": 1, "graph_signatures": {"yelp": graph_signature(manifest)}}
            graph, session, db = Mock(), Mock(), Mock()
            graph.__enter__ = Mock(return_value=graph); graph.__exit__ = Mock(return_value=False)
            session.__enter__ = Mock(return_value=session); session.__exit__ = Mock(return_value=False)
            graph.session.return_value = session
            db.__enter__ = Mock(return_value=db); db.__exit__ = Mock(return_value=False)
            db.transaction.return_value.__enter__ = Mock()
            db.transaction.return_value.__exit__ = Mock(return_value=False)
            with patch.object(module, "ROOT", root), patch.object(module, "NAMES", {"yelp": "Yelp"}), \
                 patch.object(module, "driver", return_value=graph), patch.object(module, "postgres", return_value=db), \
                 patch.object(module, "publish_catalog") as publish:
                session.run.side_effect = [Mock(single=Mock(return_value={"count": count})) for count in (2, 1, 2)]
                module.restore_installed_catalog(receipt)
                publish.assert_called_once_with(db, "yelp", manifest, "ready")
                publish.reset_mock()
                session.run.side_effect = [Mock(single=Mock(return_value={"count": count})) for count in (3, 1)]
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    module.restore_installed_catalog(receipt)
                publish.assert_not_called()

    def test_preparation_does_not_downgrade_installed_dataset(self):
        manifest = {"tables": [{"name": "people", "kind": "nodes", "rows": 2, "key": "id"}]}
        db = Mock()
        db.execute.return_value.fetchone.return_value = ("ready", manifest)
        publish_catalog(db, "yelp", {**manifest, "prepared": True, "parquet_bytes": 999}, "preparing_graph")
        assert db.execute.call_args.args[1][4] == "ready"
        changed = {"tables": [{**manifest["tables"][0], "rows": 3}]}
        publish_catalog(db, "yelp", changed, "preparing_graph")
        assert db.execute.call_args.args[1][4] == "preparing_graph"

    def test_commit_receipt_recovers_missing_local_manifest_without_second_copy(self):
        with tempfile.TemporaryDirectory() as temp, duckdb.connect() as db:
            builder = Builder.__new__(Builder)
            builder.directory = Path(temp)
            builder.manifest_path = Path(temp) / "manifest.json"
            builder.manifest = {"tables": []}
            builder.slug = builder.schema = "yelp"
            builder.db = db
            committed = {}
            in_transaction = False
            pg = Mock()

            @contextmanager
            def transaction():
                nonlocal in_transaction
                in_transaction = True
                try:
                    yield
                finally:
                    in_transaction = False

            def execute(query, parameters=None):
                query = str(query)
                if "SELECT fingerprint,record" in query:
                    return Mock(fetchone=lambda: committed.get("receipt"))
                if "INSERT INTO graphmine_catalog.imported_tables" in query:
                    assert in_transaction, "Receipt must commit atomically with table data"
                    committed["receipt"] = (parameters[2], parameters[3].obj)
                return Mock(fetchone=lambda: None)

            pg.execute.side_effect = execute
            pg.transaction.side_effect = transaction
            cursor = Mock(rowcount=2)
            pg.cursor.return_value.__enter__ = Mock(return_value=cursor)
            pg.cursor.return_value.__exit__ = Mock(return_value=False)
            copy = Mock()
            cursor.copy.return_value.__enter__ = Mock(return_value=copy)
            cursor.copy.return_value.__exit__ = Mock(return_value=False)
            builder.pg = pg
            with patch("benchmark_import.write_json", side_effect=OSError("simulated crash after commit")):
                with self.assertRaises(OSError):
                    builder.table("people", "SELECT * FROM (VALUES (1, 'Ada'), (2, 'Ben')) AS x(id,name)", key="id", labels=["Person"])
            assert committed["receipt"]
            builder.manifest = {"tables": []}
            copied = copy.write.call_count
            builder.table("people", "SELECT * FROM (VALUES (1, 'Ada'), (2, 'Ben')) AS x(id,name)", key="id", labels=["Person"])
            assert copy.write.call_count == copied
            assert json.loads(builder.manifest_path.read_text())["tables"][0]["rows"] == 2


class CompleteCsvTest(unittest.TestCase):
    def builder(self, directory):
        builder = Builder.__new__(Builder)
        builder.directory = directory
        builder.manifest_path = directory / "manifest.json"
        builder.manifest = {"tables": []}
        builder.slug = "stackoverflow"
        builder.pg = RecordingDatabase()
        return builder

    def test_complete_multiline_csv_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "source.csv"
            content = b'id,body\n1,"multiple\nlines with ""quotes"""\n2,plain'
            source.write_bytes(content)
            builder = self.builder(directory)
            self.assertEqual(builder.complete_csv(source), source)
            self.assertEqual(source.read_bytes(), content)
            self.assertEqual(builder.pg.fragments, [])

    def test_truncated_multiline_record_preserves_all_complete_rows_and_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "source.csv"
            complete = b'id,body\r\n1,"one\nline with ""quotes"""\r\n2,plain\r\n'
            fragment = b'3,"unfinished\nrecord with ""escaped""\nand more'
            source.write_bytes(complete + fragment)
            builder = self.builder(directory)
            normalized = builder.complete_csv(source)
            self.assertEqual(normalized.read_bytes(), complete)
            with normalized.open(newline="") as stream:
                self.assertEqual(list(csv.reader(stream, strict=True)), [
                    ["id", "body"], ["1", 'one\nline with "quotes"'], ["2", "plain"],
                ])
            self.assertEqual(source.read_bytes(), complete + fragment)
            self.assertEqual(builder.pg.fragments[0][4], fragment)
            self.assertEqual(
                (directory / "incomplete-source-records/source.csv.tail").read_bytes(),
                fragment,
            )
            self.assertEqual(builder.complete_csv(source), normalized)
            self.assertEqual(len(builder.pg.fragments), 1)

    def test_truncated_first_record_keeps_header(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "source.csv"
            source.write_bytes(b'id,body\n1,"unfinished')
            builder = self.builder(directory)
            self.assertEqual(builder.complete_csv(source).read_bytes(), b"id,body\n")

    def test_json_scalars_remain_values_and_nested_objects_remain_json(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            builder = self.builder(directory)
            builder.raw = directory
            source = directory / "sample.json"
            source.write_text(json.dumps({"id": "business-a", "score": 5, "attributes": {"wifi": "free"}}) + "\n")
            source.with_name("sample.json.verified.json").write_text("{}")
            with duckdb.connect() as db:
                value = db.execute(
                    "SELECT id,score,to_json(attributes),typeof(id),typeof(score) FROM " + builder.json("sample.json")
                ).fetchone()
            self.assertEqual(value[:2], ("business-a", 5))
            self.assertEqual(json.loads(value[2]), {"wifi": "free"})
            self.assertEqual(value[3:], ("VARCHAR", "BIGINT"))

    def test_graph_reexport_preserves_multiline_text_and_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            builder = self.builder(directory)
            builder.db = duckdb.connect()
            builder.db.execute("CREATE TABLE records(_gm_node_id BIGINT, body VARCHAR, score BIGINT)")
            original = [(1, 'First\nline with "quotes" and a slash\\', 7), (9007199254740993, "", None)]
            builder.db.executemany("INSERT INTO records VALUES (?,?,?)", original)
            path = directory / "records.psv"
            record = {"name": "records", "kind": "nodes", "rows": 2, "data_file": str(path)}
            builder.manifest["tables"] = [record]
            builder.reexport_graph(record)
            with path.open(newline="") as stream:
                rows = list(csv.reader(stream, delimiter="|", strict=True))
            self.assertEqual(rows, [
                ["1", original[0][1], "7"], ["9007199254740993", "", ""],
            ])
            self.assertEqual(builder.db.execute("SELECT * FROM records ORDER BY _gm_node_id").fetchall(), original)
            self.assertTrue(record["multiline"])
            self.assertTrue(path.read_bytes().startswith(b"1|"))
            builder.db.close()

    def test_lone_carriage_return_requires_multiline_parser(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            builder = self.builder(directory)
            builder.db = duckdb.connect()
            builder.db.execute("CREATE TABLE records(_gm_node_id BIGINT, body VARCHAR)")
            builder.db.execute("INSERT INTO records VALUES (1,?)", ["one\rtwo"])
            path = directory / "records.psv"
            record = {"name": "records", "kind": "nodes", "rows": 1, "data_file": str(path)}
            builder.manifest["tables"] = [record]
            builder.reexport_graph(record)
            self.assertTrue(record["multiline"])
            with path.open(newline="") as stream:
                self.assertEqual(list(csv.reader(stream, delimiter="|")), [["1", "one\rtwo"]])
            builder.db.close()

    def test_parquet_preserves_text_typed_ids_and_nested_properties(self):
        with tempfile.TemporaryDirectory() as temp, duckdb.connect() as db:
            directory = Path(temp)
            text = 'HTML with "quotes"\ncarriage\rreturn and slash\\ — café'
            db.execute("CREATE TABLE records(_gm_node_id BIGINT, body VARCHAR, properties JSON)")
            db.execute("INSERT INTO records VALUES (?,?,?)", [
                9007199254740993, text, '{"enabled":true,"tags":["a","b"]}',
            ])
            header = directory / "records.header"
            header.write_text(":ID(records)|body:string|properties:string\n")
            table = {"name": "records", "rows": 1, "header_file": str(header)}
            output = directory / "records.parquet"
            write_parquet(db, table, output, materialized=True)
            value = db.execute("SELECT * FROM read_parquet(?)", [str(output)]).fetchone()
            self.assertEqual(value[:2], (9007199254740993, text))
            self.assertEqual(json.loads(value[2]), {"enabled": True, "tags": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
