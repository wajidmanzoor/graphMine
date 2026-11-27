"""Neo4j connections with optional SQL mappings and bounded source reads.

SQL identifiers and joins come from the saved mapping, never browser text.
User Cypher is a single read statement. Stored credentials are environment
references and are never included in public metadata or graph provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from urllib.parse import urlsplit

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .identity import current_principal
from .neo4j_backend import get_active_neo4j, source_details, source_origin, validate_configured_source

IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"
MAX_SOURCE_ROWS = 100_000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityMapping(Strict):
    id: str = Field(pattern=IDENTIFIER)
    table: str = Field(pattern=IDENTIFIER)
    schema_name: str = Field(default="public", pattern=IDENTIFIER)
    key: list[str] = Field(min_length=1, max_length=8)
    label: str = Field(pattern=IDENTIFIER)
    attributes: list[str] = Field(default_factory=list, max_length=256)
    graph_attributes: list[str] | None = Field(default=None, max_length=256)
    display: str | None = None


class RelationshipMapping(EntityMapping):
    source_entity: str
    target_entity: str
    source_columns: list[str] = Field(min_length=1, max_length=8)
    target_columns: list[str] = Field(min_length=1, max_length=8)
    weight: str | None = None
    timestamp: str | None = None


class DatabaseSource(Strict):
    # Browser-managed credentials are loaded from the private store and never
    # serialized with mappings, provenance, validation errors, or public metadata.
    _sql_credentials: dict = PrivateAttr(default_factory=dict)
    _neo4j_password: str | None = PrivateAttr(default=None)
    _network_settings: object = PrivateAttr(default=None)
    _backend_settings: object = PrivateAttr(default=None)
    _catalog: dict = PrivateAttr(default_factory=dict)
    _config_stamp: tuple | None = PrivateAttr(default=None)
    _managed: bool = PrivateAttr(default=False)
    _configured: bool = PrivateAttr(default=False)
    _registry_password_file: Path | None = PrivateAttr(default=None)
    _credentials_file: Path | None = PrivateAttr(default=None)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=160)
    users: list[str] = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    backend_id: Literal["local", "iu-remote"] | None = None
    sql_type: Literal["postgres", "sqlite"] | None = None
    sql_dsn_env: str | None = None
    sqlite_path: str | None = None
    neo4j_uri: str
    neo4j_database: str = "neo4j"
    neo4j_username: str = "neo4j"
    neo4j_password_env: str | None = None
    auth_disabled: bool = Field(default=False, strict=True)
    neo4j_writer_username: str | None = None
    neo4j_writer_password_env: str | None = None
    entities: list[EntityMapping] = Field(default_factory=list, max_length=64)
    relationships: list[RelationshipMapping] = Field(
        default_factory=list, max_length=64
    )
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_rows: int = Field(default=100_000, ge=1, le=100_000)
    max_bytes: int | None = Field(default=None, ge=1024)

    @model_validator(mode="after")
    def mappings(self):
        from .neo4j_backend import source_backend_id
        expected = source_backend_id(self)
        if self.backend_id is not None and self.backend_id != expected:
            raise ValueError("The source backend does not match its configured endpoint")
        self.backend_id = expected
        # Older configurations inferred PostgreSQL from the DSN reference.
        if self.sql_type is None:
            self.sql_type = "sqlite" if self.sqlite_path else "postgres" if self.sql_dsn_env else None
        mappings = self.entities + self.relationships
        if len({m.id for m in mappings}) != len(mappings):
            raise ValueError("Mapping IDs must be unique")
        for m in mappings:
            columns = m.key + m.attributes + ([m.display] if m.display else [])
            if isinstance(m, RelationshipMapping):
                columns += (
                    m.source_columns
                    + m.target_columns
                    + [x for x in (m.weight, m.timestamp) if x]
                )
            if any(
                not re.fullmatch(IDENTIFIER, c) or c.startswith("gm_") for c in columns
            ):
                raise ValueError(
                    "Source columns must be plain identifiers outside the gm_ namespace"
                )
            if m.display and m.display not in m.attributes:
                raise ValueError("Display column must be an exposed attribute")
            if m.graph_attributes is not None and not set(m.graph_attributes).issubset(
                m.attributes
            ):
                raise ValueError("Graph attributes must be exposed source attributes")
        entities = {m.id: m for m in self.entities}
        for relation in self.relationships:
            for alias, columns in (
                (relation.source_entity, relation.source_columns),
                (relation.target_entity, relation.target_columns),
            ):
                if alias not in entities or len(columns) != len(entities[alias].key):
                    raise ValueError(
                        "Relationship endpoints must match an entity primary key"
                    )
        if self.sql_type == "sqlite" and not self.sqlite_path:
            raise ValueError("A SQLite source needs a path")
        if self.sql_type == "postgres" and not self.sql_dsn_env:
            raise ValueError("A PostgreSQL source needs a DSN environment reference")
        if self.sql_type is None and mappings:
            raise ValueError("Table mappings require an SQL source")
        return self

    @property
    def managed(self):
        return self._managed or bool(self._sql_credentials)

    def capabilities(self):
        return {"cypher": True, "sql": self.sql_type is not None,
                "enrichment": self.sql_type is not None and bool(self.entities),
                "expansion": self.sql_type is not None and bool(self.relationships),
                "sync": self.sql_type is not None and bool(self.entities)}

    def mapping(self, identifier):
        for item in self.entities + self.relationships:
            if item.id == identifier:
                return item
        raise RecordNotFound("Source mapping not found")

    def fingerprint(self):
        value = {
            "id": self.id,
            "revision": self.revision,
            "origin": {
                "sql_type": self.sql_type,
                "sql_dsn_env": self.sql_dsn_env,
                "sqlite_path": self.sqlite_path,
                **source_origin(self),
            },
            "entities": [m.model_dump() for m in self.entities],
            "relationships": [m.model_dump() for m in self.relationships],
        }
        if self._sql_credentials:
            value["origin"]["sql_connection"] = {
                k: v for k, v in self._sql_credentials.items() if k != "password"
            }
        if self._catalog:
            value["catalog"] = self._catalog
        return hashlib.sha256(_json(value).encode()).hexdigest()

    def public(self):
        sql = self.connection_details()
        return {
            "id": self.id,
            "backend_id": self.backend_id,
            "name": self.name,
            "revision": self.revision,
            "mapping_hash": self.fingerprint(),
            "sql_type": self.sql_type,
            "entities": [
                m.model_dump(exclude={"schema_name", "table"}) for m in self.entities
            ],
            "relationships": [
                m.model_dump(exclude={"schema_name", "table"})
                for m in self.relationships
            ],
            "max_rows": self.max_rows,
            "catalog_dataset": self._catalog.get("id"),
            "managed": self.managed,
            "capabilities": self.capabilities(),
            "connection": sql,
        }

    def connection_details(self):
        sql = {k: v for k, v in self._sql_credentials.items() if k != "password"}
        if not sql and self.sql_type == "postgres":
            try:
                from psycopg.conninfo import conninfo_to_dict

                fields = conninfo_to_dict(source_secret(self, self.sql_dsn_env))
                sql = {
                    "host": fields.get("host", ""),
                    "port": int(fields.get("port") or 5432),
                    "database": fields.get("dbname", ""),
                    "username": fields.get("user", ""),
                    "sslmode": fields.get("sslmode", "prefer"),
                }
            except (ImportError, ValueError, AnalyticsError):
                sql = {}
        if self.sql_type == "sqlite":
            sql = {"database": Path(self.sqlite_path).name}
        return {
            "sql": {"type": self.sql_type, **sql} if self.sql_type else None,
            "neo4j": source_details(self),
        }


def configured(settings):
    path = settings.database_sources_file
    if path is None:
        return []
    try:
        info = path.stat()
        if (
            not path.is_file()
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 1024 * 1024
        ):
            raise ValueError("Private source configuration required")
        sources = [
            DatabaseSource.model_validate(row) for row in json.loads(path.read_text())
        ]
        if len(sources) > 100 or len({s.id for s in sources}) != len(sources):
            raise ValueError("Invalid source inventory")
        for source in sources:
            validate_configured_source(source)
            source._configured = True
            source._backend_settings = settings
            if source.auth_disabled:
                source._network_settings = settings
            source._config_stamp = (path, info.st_ino, info.st_mtime_ns, info.st_size)
            source._credentials_file = settings.database_credentials_file
        return sources
    except (OSError, ValueError, TypeError) as exc:
        raise AnalyticsError(
            "Database source configuration is unavailable.",
            "database_configuration",
            503,
        ) from exc


def available(settings):
    from .database_connections import managed_sources
    from .neo4j_registry import sources as registry_sources

    from .neo4j_backend import active_backend_id
    active = active_backend_id(settings)
    principal = current_principal.get()
    sources = [
        s
        for s in configured(settings)
        if s.backend_id == active and ("*" in s.users or principal and principal.username in s.users)
    ]
    benchmarks = [source for source in registry_sources(settings) if source.backend_id == active]
    allowlist = settings.database_dataset_allowlist
    if allowlist:
        # The configured demo and verified registries are the only routes in
        # curated mode, including requests made directly to the query API.
        choices = {"default": s for s in sources if s.id == "local-transfers"
                   or active == "iu-remote" and s.neo4j_database == "neo4j"}
        if active == "iu-remote":
            # IU databases share one server, but each configured database is a
            # separate dataset. The operator allowlist selects their source IDs.
            choices.update({s.id: s for s in sources})
        choices.update({s._catalog["id"]: s for s in benchmarks})
        selected = {choices[key].id: choices[key] for key in dict.fromkeys(allowlist) if key in choices}
        return list(selected.values())
    return sources + benchmarks + [source for source in managed_sources(settings) if source.backend_id == active]


def get_source(settings, identifier):
    for source in available(settings):
        if source.id == identifier:
            return source
    raise RecordNotFound("Database source not found")


def secret(name):
    value = os.environ.get(name or "")
    if not value:
        raise AnalyticsError(
            "A database credential is not configured.", "database_configuration", 503
        )
    return value


def source_secret(source, name):
    path = source._registry_password_file or source._credentials_file
    if path is not None:
        from .neo4j_registry import password
        return password(path, name)
    return secret(name)


def json_value(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_value(x) for x in value]
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    raise AnalyticsError("A source value has an unsupported type.", "database_value")


def source_keys(source, mapping, values, columns=None):
    """Match catalog key types across original graph properties and SQL joins."""
    types = source._catalog.get("types", {}).get(mapping.id, {})
    try:
        result = []
        for column, value in zip(columns or mapping.key, values):
            if value is not None and types.get(column) == "bigint":
                integer = int(value)
                if isinstance(value, bool) or isinstance(value, float) and value != integer:
                    raise ValueError("Non-integral source key")
                value = integer
            elif value is not None and types.get(column) == "text":
                value = str(value)
            result.append(value)
        return result
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalyticsError("A graph source key does not match its SQL type.", "database_mapping") from exc


def stable_id(source, mapping, keys):
    keys = source_keys(source, mapping, keys)
    if any(value is None for value in keys):
        raise AnalyticsError("Mapped keys cannot be null.", "database_mapping")
    return (
        f"{source.id}:{mapping.id}:"
        + hashlib.sha256(_json(json_value(keys)).encode()).hexdigest()
    )


@contextmanager
def sql_connection(source):
    if source.sql_type is None:
        raise AnalyticsError("This connection has no SQL source. Add SQL and table mappings to use enrichment or synchronization.", "sql_unavailable", 409)
    if source.sql_type == "postgres":
        with _postgres_connection(source) as db:
            yield db
        return
    db = None
    try:
        from .database_pools import check_source_stamp
        check_source_stamp(source)
        db = sqlite3.connect(
            Path(source.sqlite_path).resolve().as_uri() + "?mode=ro", uri=True
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        import time

        deadline = time.monotonic() + source.timeout_seconds
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute("BEGIN")
        yield db
    finally:
        if db is not None:
            try:
                db.rollback()
            finally:
                db.close()


@contextmanager
def _postgres_connection(source):
    try:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool, PoolTimeout, TooManyRequests
    except ImportError as exc:
        raise AnalyticsError("Install the agent databases extra to connect PostgreSQL.", "database_driver", 503) from exc
    from .database_job_context import checkpoint
    from .database_pools import check_source_stamp, current_database_pools, resource

    if source._sql_credentials:
        from .database_connections import network_address
        values = source._sql_credentials
        address = network_address(source._network_settings, values["host"], values["port"])
        kwargs = dict(host=values["host"], hostaddr=address, port=values["port"],
                      dbname=values["database"], user=values["username"],
                      password=values["password"], sslmode=values["sslmode"])
    else:
        kwargs = conninfo_to_dict(source_secret(source, source.sql_dsn_env))
    # The connection default also bounds pool checks/reset after a rollback.
    kwargs.update(connect_timeout=5, options=kwargs.get("options", "") + f" -c statement_timeout={source.timeout_seconds * 1000}")
    signature = [kwargs, {key: value for key, value in os.environ.items() if key.startswith("PG")}]
    pools = current_database_pools.get()
    size, timeout, idle = (pools.size, pools.wait_seconds, pools.idle_seconds) if pools else (1, 10, 1)

    def configure(db):
        db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        db.read_only = True
        db.row_factory = dict_row

    def reset(db):
        db.autocommit = True
        db.execute("DISCARD ALL")
        db.autocommit = False
        configure(db)

    def create():
        return ConnectionPool(kwargs={**kwargs, "row_factory": dict_row, "prepare_threshold": None},
                              min_size=0, max_size=size, max_waiting=size, timeout=timeout,
                              max_idle=idle, max_lifetime=1800, num_workers=1, open=True,
                              configure=configure, check=ConnectionPool.check_connection,
                              name="graphmine-postgres")

    with resource(source, "postgres", signature, create) as pool:
        try:
            db = pool.getconn(timeout=timeout)
        except (PoolTimeout, TooManyRequests):
            if pools is not None:
                pools.retire(pool)
            raise AnalyticsError("Could not acquire a database connection. Check its status and retry.", "database_busy", 429) from None
        try:
            checkpoint()
            check_source_stamp(source)
            configure(db)
            db.execute("SELECT set_config('statement_timeout', %s, true)", (str(source.timeout_seconds * 1000),))
            yield db
        finally:
            try:
                db.rollback()
                # Finish reset before return/retirement. No queued reset may
                # retain a socket after the registry closes its owning pool.
                reset(db)
            except Exception:
                db.close()
            finally:
                pool.putconn(db)


def read_rows(db, source, mapping, *, keys=None, where_keys=None, fields=None, validate_schema=False):
    fields = mapping.attributes if fields is None else fields
    if not set(fields).issubset(mapping.attributes):
        raise AnalyticsError("Unknown mapped source fields", "database_mapping")
    columns = list(
        dict.fromkeys(
            mapping.key + fields + ([mapping.display] if mapping.display else [])
        )
    )
    if isinstance(mapping, RelationshipMapping):
        columns = list(
            dict.fromkeys(
                columns
                + mapping.source_columns
                + mapping.target_columns
                + [x for x in (mapping.weight, mapping.timestamp) if x]
            )
        )
    quote = lambda name: '"' + name + '"'
    # SQLite may treat an unknown unqualified double-quoted column as a string
    # literal. Qualifying every column makes missing mappings fail on both SQL
    # engines, including predicates and ordering keys.
    column = lambda name: '"gm_rows".' + quote(name)
    table = (
        quote(mapping.table)
        if source.sql_type == "sqlite"
        else quote(mapping.schema_name) + "." + quote(mapping.table)
    )
    marker = "?" if source.sql_type == "sqlite" else "%s"
    if validate_schema and not set(mapping.attributes).issubset(columns):
        cursor = db.cursor()
        try:
            # Check SQL-only enrichment fields too, without reading their values.
            cursor.execute("SELECT " + ",".join(column(name) for name in dict.fromkeys(columns + mapping.attributes)) + " FROM " + table + ' AS "gm_rows" WHERE 1=0')
        finally:
            cursor.close()
    clauses, parameters = [], []
    groups = [(mapping.key, keys)] if keys is not None else where_keys
    if groups is not None:
        for fields, values in groups:
            for values_row in values:
                if len(fields) != len(values_row):
                    raise AnalyticsError("Invalid source key", "database_mapping")
                clauses.append(
                    "(" + " AND ".join(column(f) + "=" + marker for f in fields) + ")"
                )
                parameters.extend(source_keys(source, mapping, values_row, fields))
        if not clauses:
            return []
    statement = "SELECT " + ",".join(column(c) for c in columns) + " FROM " + table + ' AS "gm_rows"'
    if groups is not None:
        statement += " WHERE " + " OR ".join(clauses)
    statement += (
        " ORDER BY " + ",".join(column(c) for c in mapping.key) + " LIMIT " + marker
    )
    parameters.append(source.max_rows + 1)
    rows, used, seen = [], 0, set()
    import uuid

    # PostgreSQL server cursors avoid buffering the full SQL result in libpq.
    cursor = (
        db.cursor(name="gm_" + uuid.uuid4().hex)
        if source.sql_type == "postgres"
        else db.cursor()
    )
    try:
        cursor.execute(statement, parameters)
        from .database_job_context import checkpoint

        for row in cursor:
            checkpoint()
            item = dict(row)
            identity = _json(json_value([item[key] for key in mapping.key]))
            if identity in seen:
                raise AnalyticsError("This source key matches multiple rows. Use a unique table mapping.", "database_mapping", 409)
            seen.add(identity)
            used += len(_json(json_value(item)).encode())
            if len(rows) >= source.max_rows or (source.max_bytes is not None and used > source.max_bytes):
                raise AnalyticsError(
                    "Source read exceeds the row or byte limit; narrow the selection.",
                    "resource_limit",
                )
            rows.append(item)
    finally:
        cursor.close()
    return rows


def validate_cypher(statement):
    # Lex strings, quoted identifiers and comments before checking clauses.
    # Procedures, external loading and USE are intentionally outside this read
    # editor's contract; EXPLAIN additionally checks the server's query type.
    token = re.compile(
        r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"|`(?:``|[^`])*`|//[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_][A-Za-z0-9_]*|;|[^\s]",
        re.MULTILINE,
    )
    tokens = [match.group() for match in token.finditer(statement)
              if not match.group().startswith(("//", "/*"))]
    forbidden = {
        "CREATE",
        "MERGE",
        "SET",
        "DELETE",
        "DETACH",
        "REMOVE",
        "DROP",
        "ALTER",
        "RENAME",
        "GRANT",
        "DENY",
        "REVOKE",
        "LOAD",
        "CALL",
        "USE",
        "FOREACH",
        "INSERT",
        "TERMINATE",
        "START",
        "STOP",
    }
    def reject():
        raise AnalyticsError(
            "Use one read Cypher query returning nodes, relationships or paths. Write clauses, procedures and database switching are unavailable in this editor.",
            "cypher_read_only",
        )
    if not tokens or tokens[0].upper() not in {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN"}:
        reject()
    if ";" in tokens[:-1] or tokens.count(";") > 1:
        raise AnalyticsError("Run one Cypher statement at a time.", "cypher_read_only")
    # Delimiters distinguish pattern/expression identifiers from clauses.
    # A query block starts a fresh clause scope even inside an expression.
    stack = []
    expression_prefixes = {"RETURN", "WITH", "UNWIND", "WHERE", "AND", "OR", "XOR", "NOT", "IN",
                           "WHEN", "THEN", "ELSE", "BY", "DISTINCT", "AS", "IS", "CONTAINS",
                           ",", ".", ":", "$", "=", "<", ">", "+", "-", "*", "/", "%", "^", "|"}
    for index, value in enumerate(tokens):
        previous = tokens[index - 1].upper() if index else ""
        if value in {"(", "["}:
            stack.append((value, "expression"))
        elif value == "{":
            # EXISTS/COUNT/COLLECT subqueries can contain nested MATCH clauses.
            following = tokens[index + 1].upper() if index + 1 < len(tokens) else ""
            next_symbol = tokens[index + 2] if index + 2 < len(tokens) else ""
            query = (previous in {"EXISTS", "COUNT", "COLLECT", "CALL"}
                     and following in {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN", "CALL"}
                     and next_symbol != ":")
            stack.append((value, "query" if query else "expression"))
        elif value in {")", "]", "}"}:
            if not stack or stack[-1][0] != {")": "(", "]": "[", "}": "{"}[value]:
                reject()
            stack.pop()
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) and value.upper() in forbidden:
            scope = max((i + 1 for i, (_, kind) in enumerate(stack) if kind == "query"), default=0)
            if not stack[scope:] and previous not in expression_prefixes:
                reject()
    if stack:
        reject()


@contextmanager
def neo4j_session(source, *, write=False, wake=True):
    from .database_pools import current_database_pools
    from .neo4j_access import session as access
    pools = current_database_pools.get()
    settings = source._backend_settings or source._network_settings or (pools.settings if pools else None)
    with access(settings), _neo4j_session(source, write=write, wake=wake) as session:
        yield session


@contextmanager
def _neo4j_session(source, *, write=False, wake=True):
    if write and source._catalog.get("registry"):
        raise AnalyticsError("Benchmark connections allow read queries only.", "cypher_read_only", 409)
    try:
        from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase
    except ImportError as exc:
        raise AnalyticsError(
            "Install the agent databases extra to connect Neo4j.",
            "database_driver",
            503,
        ) from exc
    from .database_pools import current_database_pools, resource
    from .identity import identity_scope

    backend = get_active_neo4j(source=source, write=write)
    endpoint = backend.connection
    credential = endpoint.auth
    options, address_key = {}, None
    if source._network_settings is not None:
        from .database_connections import network_address
        settings, principal = source._network_settings, current_principal.get()
        host, port = endpoint.address
        address_key = network_address(settings, host, port)
        # Check and pin every routing address, including discovered cluster hosts.
        def resolver(address):
            with identity_scope(principal):
                return [(network_address(settings, address.host, address.port), address.port)]

        options["resolver"] = resolver
    pools = current_database_pools.get()
    signature = [backend.id, endpoint.uri, endpoint.database, credential, address_key]
    from .remote_neo4j import get_remote
    settings = source._backend_settings or source._network_settings or (pools.settings if pools else None)
    activity = get_remote(settings).request(wake=wake) if backend.id == "iu-remote" else nullcontext()

    def create():
        return GraphDatabase.driver(
            endpoint.uri,
            auth=credential,
            connection_timeout=5,
            connection_acquisition_timeout=pools.wait_seconds if pools else 10,
            max_connection_pool_size=pools.size if pools else 4,
            max_connection_lifetime=1800,
            liveness_check_timeout=60,
            **options,
        )

    with (
        activity,
        resource(source, "neo4j-write" if write else "neo4j-read", signature, create) as driver,
        driver.session(
            database=endpoint.database,
            default_access_mode=WRITE_ACCESS if write else READ_ACCESS,
        ) as session,
    ):
        yield session


def neo4j_read(session, source, work, *, timeout):
    """IU reads use driver-managed read transactions; local rollback behavior stays intact."""
    if source.auth_disabled:
        from neo4j import unit_of_work
        return session.execute_read(unit_of_work(timeout=timeout)(work))
    with session.begin_transaction(timeout=timeout) as transaction:
        result = work(transaction)
        transaction.rollback()
        return result
