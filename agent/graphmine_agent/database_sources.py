"""Operator-configured local SQL/Neo4j pairs and bounded source reads.

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
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .identity import current_principal

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
    attributes: list[str] = Field(default_factory=list, max_length=64)
    graph_attributes: list[str] | None = Field(default=None, max_length=64)
    display: str | None = None


class RelationshipMapping(EntityMapping):
    source_entity: str
    target_entity: str
    source_columns: list[str] = Field(min_length=1, max_length=8)
    target_columns: list[str] = Field(min_length=1, max_length=8)
    weight: str | None = None
    timestamp: str | None = None


class DatabaseSource(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=160)
    users: list[str] = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    sql_type: Literal["postgres", "sqlite"] = "postgres"
    sql_dsn_env: str | None = None
    sqlite_path: str | None = None
    neo4j_uri: str
    neo4j_database: str = "neo4j"
    neo4j_username: str = "neo4j"
    neo4j_password_env: str
    neo4j_writer_username: str | None = None
    neo4j_writer_password_env: str | None = None
    entities: list[EntityMapping] = Field(min_length=1, max_length=64)
    relationships: list[RelationshipMapping] = Field(
        default_factory=list, max_length=64
    )
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_rows: int = Field(default=100_000, ge=1, le=100_000)
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)

    @model_validator(mode="after")
    def mappings(self):
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
        return self

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
                "neo4j_uri": self.neo4j_uri,
                "neo4j_database": self.neo4j_database,
            },
            "entities": [m.model_dump() for m in self.entities],
            "relationships": [m.model_dump() for m in self.relationships],
        }
        return hashlib.sha256(_json(value).encode()).hexdigest()

    def public(self):
        return {
            "id": self.id,
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
        return sources
    except (OSError, ValueError, TypeError) as exc:
        raise AnalyticsError(
            "Database source configuration is unavailable.",
            "database_configuration",
            503,
        ) from exc


def available(settings):
    principal = current_principal.get()
    return [
        s
        for s in configured(settings)
        if "*" in s.users or principal and principal.username in s.users
    ]


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


def stable_id(source, mapping, keys):
    if any(value is None for value in keys):
        raise AnalyticsError("Mapped keys cannot be null.", "database_mapping")
    return (
        f"{source.id}:{mapping.id}:"
        + hashlib.sha256(_json(json_value(keys)).encode()).hexdigest()
    )


@contextmanager
def sql_connection(source):
    db = None
    try:
        if source.sql_type == "sqlite":
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
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise AnalyticsError(
                    "Install the agent databases extra to connect PostgreSQL.",
                    "database_driver",
                    503,
                ) from exc
            db = psycopg.connect(
                secret(source.sql_dsn_env), row_factory=dict_row, connect_timeout=5
            )
            db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            db.read_only = True
            db.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(source.timeout_seconds * 1000),),
            )
        yield db
    finally:
        if db is not None:
            try:
                db.rollback()
            finally:
                db.close()


def read_rows(db, source, mapping, *, keys=None, where_keys=None, fields=None):
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
    table = (
        quote(mapping.table)
        if source.sql_type == "sqlite"
        else quote(mapping.schema_name) + "." + quote(mapping.table)
    )
    marker = "?" if source.sql_type == "sqlite" else "%s"
    clauses, parameters = [], []
    groups = [(mapping.key, keys)] if keys is not None else where_keys
    if groups is not None:
        for fields, values in groups:
            for values_row in values:
                if len(fields) != len(values_row):
                    raise AnalyticsError("Invalid source key", "database_mapping")
                clauses.append(
                    "(" + " AND ".join(quote(f) + "=" + marker for f in fields) + ")"
                )
                parameters.extend(values_row)
        if not clauses:
            return []
    statement = "SELECT " + ",".join(quote(c) for c in columns) + " FROM " + table
    if groups is not None:
        statement += " WHERE " + " OR ".join(clauses)
    statement += (
        " ORDER BY " + ",".join(quote(c) for c in mapping.key) + " LIMIT " + marker
    )
    parameters.append(source.max_rows + 1)
    rows, used = [], 0
    import uuid

    # PostgreSQL server cursors avoid buffering the full SQL result in libpq.
    cursor = (
        db.cursor(name="gm_" + uuid.uuid4().hex)
        if source.sql_type == "postgres"
        else db.cursor()
    )
    try:
        cursor.execute(statement, parameters)
        for row in cursor:
            item = dict(row)
            used += len(_json(json_value(item)).encode())
            if len(rows) >= source.max_rows or used > source.max_bytes:
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
    words, semicolons = [], 0
    for match in token.finditer(statement):
        value = match.group()
        if value.startswith(("'", '"', "`", "//", "/*")):
            continue
        if value == ";":
            semicolons += 1
            if statement[match.end() :].strip():
                raise AnalyticsError(
                    "Run one Cypher statement at a time.", "cypher_read_only"
                )
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            words.append(value.upper())
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
    if (
        not words
        or words[0] not in {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN"}
        or forbidden.intersection(words)
        or semicolons > 1
    ):
        raise AnalyticsError(
            "Use one read Cypher query returning nodes, relationships or paths. Write clauses, procedures and database switching are unavailable in this editor.",
            "cypher_read_only",
        )


@contextmanager
def neo4j_session(source, *, write=False):
    try:
        from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase
    except ImportError as exc:
        raise AnalyticsError(
            "Install the agent databases extra to connect Neo4j.",
            "database_driver",
            503,
        ) from exc
    user = (
        (source.neo4j_writer_username or source.neo4j_username)
        if write
        else source.neo4j_username
    )
    password = (
        source.neo4j_writer_password_env
        if write and source.neo4j_writer_password_env
        else source.neo4j_password_env
    )
    with (
        GraphDatabase.driver(
            source.neo4j_uri,
            auth=(user, secret(password)),
            connection_timeout=5,
            max_connection_pool_size=4,
        ) as driver,
        driver.session(
            database=source.neo4j_database,
            default_access_mode=WRITE_ACCESS if write else READ_ACCESS,
        ) as session,
    ):
        yield session
