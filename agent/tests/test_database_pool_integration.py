"""Opt-in PostgreSQL tests; creates its own temporary server, never a user DB."""

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.database_pools import DatabasePools, pool_scope
from graphmine_agent.database_sources import DatabaseSource, EntityMapping, read_rows, sql_connection

pytestmark = pytest.mark.skipif(os.getenv("GRAPHMINE_TEST_DATABASE_INTEGRATION") != "1", reason="requires opt-in temporary PostgreSQL server")


@pytest.fixture(scope="module")
def postgres():
    import psycopg
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/postgres"))
    executable = shutil.which("postgres") or (str(candidates[-1]) if candidates else None)
    if executable is None:
        pytest.fail("Temporary pool integration checks require PostgreSQL server binaries")
    binaries = Path(executable).parent
    with tempfile.TemporaryDirectory(prefix="gm-pool-pg-") as directory:
        root = Path(directory); data = root / "data"
        subprocess.run([str(binaries / "initdb"), "-D", str(data), "-A", "trust", "-U", "pooltest", "--no-locale", "--encoding=UTF8"],
                       check=True, capture_output=True, timeout=30)
        with (root / "server.log").open("wb") as log:
            process = subprocess.Popen([executable, "-D", str(data), "-k", str(root), "-h", "", "-p", "55432"], stdout=log, stderr=log)
            dsn = f"host={root} port=55432 dbname=postgres user=pooltest"
            try:
                for attempt in range(100):
                    try:
                        with psycopg.connect(dsn, autocommit=True) as db:
                            db.execute("CREATE TABLE IF NOT EXISTS entries (id integer PRIMARY KEY)")
                        break
                    except psycopg.OperationalError:
                        if process.poll() is not None:
                            pytest.fail((root / "server.log").read_text())
                        time.sleep(.05)
                else:
                    pytest.fail("Temporary PostgreSQL did not become ready")
                yield dsn
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


@pytest.fixture
def connection(postgres, settings, monkeypatch):
    monkeypatch.setenv("POOL_TEST_SQL", postgres)
    source = DatabaseSource(id="pool-test", name="Temporary database", users=["*"], sql_dsn_env="POOL_TEST_SQL",
                            neo4j_uri="bolt://unused", neo4j_password_env="UNUSED", timeout_seconds=1)
    pools = DatabasePools(replace(settings, database_pool_size=2))
    with pool_scope(pools):
        yield source, pools
    pools.close()


def test_reuses_socket_and_resets_transaction_and_session_state(connection):
    import psycopg
    source, pools = connection
    pools.size = 1
    with sql_connection(source) as db:
        pid = db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        assert db.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] == "repeatable read"
        assert db.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        assert db.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "1s"
        db.execute("SELECT pg_advisory_lock(98765)")
        db.execute("SET application_name = 'dirty borrower'")
        db.commit()
    with sql_connection(source) as db:
        assert db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
        assert db.execute("SHOW application_name").fetchone()["application_name"] != "dirty borrower"
        assert db.execute("SELECT pg_advisory_unlock(98765) AS unlocked").fetchone()["unlocked"] is False
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            db.execute("INSERT INTO entries VALUES (1)")
    with sql_connection(source) as db:
        assert db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid


def test_snapshot_ends_at_return_and_named_cursors_do_not_leak(connection, postgres):
    import psycopg
    source, _ = connection
    with psycopg.connect(postgres, autocommit=True) as writer:
        writer.execute("TRUNCATE entries")
        with sql_connection(source) as db:
            assert db.execute("SELECT count(*) AS n FROM entries").fetchone()["n"] == 0
            cursor = db.cursor(name="temporary_cursor")
            cursor.execute("SELECT * FROM entries")
            writer.execute("INSERT INTO entries VALUES (7)")
            assert db.execute("SELECT count(*) AS n FROM entries").fetchone()["n"] == 0
        with sql_connection(source) as db:
            assert db.execute("SELECT count(*) AS n FROM entries").fetchone()["n"] == 1
            assert not db.execute("SELECT * FROM pg_cursors WHERE name='temporary_cursor'").fetchall()


def test_timeout_and_dead_connection_recover_without_reusing_failed_transaction(connection, postgres):
    import psycopg
    source, _ = connection
    with pytest.raises(psycopg.errors.QueryCanceled):
        with sql_connection(source) as db:
            db.execute("SELECT pg_sleep(2)")
    with sql_connection(source) as db:
        pid = db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    with psycopg.connect(postgres, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
    with sql_connection(source) as db:
        assert db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid


def test_pool_size_and_credential_generation_are_bounded(connection, postgres, monkeypatch):
    source, pools = connection
    pools.wait_seconds = .05
    with sql_connection(source) as first, sql_connection(source) as second:
        first_pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        second_pid = second.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        assert first_pid != second_pid
        with pytest.raises(AnalyticsError, match="Timed out"):
            with sql_connection(source):
                pass
    monkeypatch.setenv("POOL_TEST_SQL", postgres + " password=rotated-test-value")
    with sql_connection(source) as fresh:
        assert fresh.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] not in {first_pid, second_pid}


def test_failed_connections_retire_and_successful_borrowing_can_recover(connection, postgres, monkeypatch):
    source, pools = connection
    pools.wait_seconds = .1
    monkeypatch.setenv("POOL_TEST_SQL", postgres.replace("dbname=postgres", "dbname=does_not_exist"))
    with pytest.raises(AnalyticsError, match="acquire a database connection"):
        with sql_connection(source):
            pass
    assert not pools._entries
    monkeypatch.setenv("POOL_TEST_SQL", postgres)
    pools.wait_seconds = 1
    with sql_connection(source) as db:
        assert db.execute("SELECT 1 AS healthy").fetchone()["healthy"] == 1


def test_repeated_reads_use_bounded_backend_connections_and_shutdown_closes_them(connection, postgres):
    import psycopg
    source, pools = connection
    pids = set()
    for _ in range(30):
        with sql_connection(source) as db:
            pids.add(db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
    assert 1 <= len(pids) <= pools.size
    pools.close()
    # The server observes socket closure asynchronously; use fresh snapshots.
    with psycopg.connect(postgres, autocommit=True) as admin:
        deadline = time.monotonic() + 2
        while admin.execute("SELECT pid FROM pg_stat_activity WHERE pid = ANY(%s)", (list(pids),)).fetchall():
            assert time.monotonic() < deadline, "Pool left PostgreSQL sessions open"
            time.sleep(.01)


def test_qualified_mapped_reads_and_removed_enrichment_columns(connection, postgres):
    import psycopg
    source, _ = connection
    mapping = EntityMapping(id="mapped", table="sync_entries", key=["id"], label="Entry", attributes=["name", "detail"], graph_attributes=["name"])
    with psycopg.connect(postgres, autocommit=True) as writer:
        writer.execute("CREATE TABLE sync_entries (id integer PRIMARY KEY, name text, detail text)")
        writer.execute("INSERT INTO sync_entries VALUES (1, 'one', 'extra'), (2, 'two', 'more')")
        with sql_connection(source) as db:
            assert read_rows(db, source, mapping, keys=[[2]], fields=["name"], validate_schema=True) == [{"id": 2, "name": "two"}]
        writer.execute("ALTER TABLE sync_entries RENAME COLUMN detail TO changed")
        with pytest.raises(psycopg.errors.UndefinedColumn):
            with sql_connection(source) as db:
                read_rows(db, source, mapping, fields=["name"], validate_schema=True)
        with sql_connection(source) as db:
            assert read_rows(db, source, mapping, fields=["name"]) == [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}]
