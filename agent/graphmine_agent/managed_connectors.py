"""Account-owned connections; credentials and SQLite bytes stay in the private store."""

import base64
import hashlib
import ipaddress
import socket
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .identity import AccountError, current_principal
from .models import new_id


class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    type: Literal["sqlite", "rest", "neo4j"]
    url: str | None = Field(default=None, max_length=2048)
    table: str | None = Field(default=None, max_length=256)
    format: Literal["json_rows", "graph", "csv"] = "json_rows"
    rows_field: str | None = Field(default=None, max_length=256)
    source_column: str = Field(default="source", min_length=1, max_length=256)
    target_column: str = Field(default="target", min_length=1, max_length=256)
    directed: bool = False
    complete_response: bool = False
    bearer_token: str | None = Field(default=None, max_length=4096)
    database: str = Field(default="neo4j", pattern=r"^[a-zA-Z0-9_.-]{1,63}$")
    username: str = Field(default="neo4j", min_length=1, max_length=256)
    password: str | None = Field(default=None, max_length=4096)
    node_label: str | None = Field(default=None, max_length=256)
    relationship_type: str | None = Field(default=None, max_length=256)


def principal():
    user = current_principal.get()
    if user is None:
        raise AccountError("Sign in to manage connections.", "unauthorized", 401)
    return user


def endpoint(url):
    try:
        parsed = httpx.URL(url or "")
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.host
            or parsed.userinfo
            or parsed.fragment
        ):
            raise ValueError
        origin = str(parsed.copy_with(path="/", query=None, fragment=None)).rstrip("/")
        return parsed, origin
    except (ValueError, httpx.InvalidURL) as exc:
        raise AnalyticsError(
            "Use an HTTP(S) endpoint without embedded credentials or a URL fragment.",
            "connector_endpoint",
        ) from exc


def network_target(settings, url):
    """Resolve once, validate every address, and pin the connection to that IP.

    The original Host and TLS server name remain intact. An explicit operator
    origin allowlist permits local Node.js and Neo4j installations.
    """
    parsed, origin = endpoint(url)
    permitted = origin in {
        endpoint(item)[1] for item in settings.connector_allowed_origins
    }
    if parsed.scheme != "https" and not permitted:
        raise AnalyticsError(
            "Use HTTPS. For a local server, ask the administrator to allow this connection's origin.",
            "connector_endpoint",
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = sorted(
            {
                record[4][0]
                for record in socket.getaddrinfo(
                    parsed.host, port, type=socket.SOCK_STREAM
                )
            }
        )
    except OSError as exc:
        raise AnalyticsError(
            "The connection hostname could not be resolved.", "connector_endpoint"
        ) from exc
    if (
        not addresses
        or any(not ipaddress.ip_address(address).is_global for address in addresses)
        and not permitted
    ):
        raise AnalyticsError(
            "This endpoint is on a private or reserved network. Ask the administrator to allow its origin.",
            "connector_endpoint",
        )
    host = parsed.host if ":" not in parsed.host else f"[{parsed.host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    authority = host + (f":{port}" if port != default_port else "")
    return parsed.copy_with(host=addresses[0]), authority, parsed.host


def records(runtime):
    user = current_principal.get()
    if user is None:
        return []
    with runtime.database._connect() as db:
        rows = db.execute(
            "SELECT document FROM user_connectors WHERE owner_id=? ORDER BY rowid",
            (user.user_id,),
        ).fetchall()
    from .connectors import Connector

    return [Connector.model_validate_json(row[0]) for row in rows]


def saved(runtime, identifier):
    user = principal()
    with runtime.database._connect() as db:
        row = db.execute(
            "SELECT document,content,size_bytes,sha256 FROM user_connectors WHERE id=? AND owner_id=?",
            (identifier, user.user_id),
        ).fetchone()
    if row is None:
        raise RecordNotFound("Connection not found")
    if len(row[1]) != row[2] or hashlib.sha256(row[1]).hexdigest() != row[3]:
        raise AnalyticsError(
            "The saved connection failed its integrity check.", "data_integrity", 409
        )
    from .connectors import Connector

    return Connector.model_validate_json(row[0]), row[1]


@contextmanager
def sqlite_file(content):
    if not content.startswith(b"SQLite format 3\x00"):
        raise AnalyticsError("Choose a valid SQLite database file.", "connector_input")
    with tempfile.TemporaryDirectory(prefix="graphmine-sqlite-") as temporary:
        path = Path(temporary) / "source.sqlite3"
        path.write_bytes(content)
        path.chmod(0o600)
        yield path


def sqlite_tables(content):
    try:
        with (
            sqlite_file(content) as path,
            closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db,
        ):
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
            # Bound schema traversal as well as the eventual table read.
            import time

            started = time.monotonic()
            db.set_progress_handler(lambda: int(time.monotonic() - started > 5), 1000)
            tables = []
            for name, sql in db.execute(
                "SELECT name,sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 101"
            ).fetchall():
                if not sql or "VIRTUAL TABLE" in sql.upper():
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [row[1] for row in db.execute(f"PRAGMA table_info({quoted})")]
                if 2 <= len(columns) <= 64:
                    tables.append({"name": name, "columns": columns})
            if not tables or len(tables) > 100:
                raise ValueError("unsupported table inventory")
            return tables
    except (sqlite3.Error, ValueError, OSError) as exc:
        raise AnalyticsError(
            "The SQLite file needs a regular table with 2–64 columns (at most 100 tables). Export a consistent database backup before uploading.",
            "connector_input",
        ) from exc


def public(config):
    values = config.model_dump(
        include={
            "id",
            "name",
            "type",
            "url",
            "table",
            "format",
            "rows_field",
            "source_column",
            "target_column",
            "directed",
            "complete_response",
            "database",
            "username",
            "node_label",
            "relationship_type",
        }
    )
    return {**values, "managed": True, "has_credentials": bool(config.headers)}


def detail(runtime, identifier):
    config, content = saved(runtime, identifier)
    return {
        **public(config),
        "tables": sqlite_tables(content) if config.type == "sqlite" else [],
    }


def persist(runtime, config, content, *, updating=False):
    user = principal()
    serialized = _json(config.model_dump())
    cost = len(content) + len(serialized.encode())
    with runtime.database._lock, runtime.database._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT size_bytes+length(CAST(document AS BLOB)) FROM user_connectors WHERE id=? AND owner_id=?",
            (config.id, user.user_id),
        ).fetchone()
        if updating and previous is None:
            raise RecordNotFound("Connection not found")
        if (
            not updating
            and db.execute(
                "SELECT count(*) FROM user_connectors WHERE owner_id=?", (user.user_id,)
            ).fetchone()[0]
            >= 50
        ):
            raise AccountError(
                "Remove an unused connection before adding another (limit 50).",
                "resource_limit",
            )
        if cost > user.accounts.upload_remaining(user.user_id) + (
            previous[0] if previous else 0
        ):
            raise AccountError(
                "Your storage allowance is full. Remove unused data or connections.",
                "storage_limit",
            )
        db.execute(
            "INSERT INTO user_connectors VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,content=excluded.content,size_bytes=excluded.size_bytes,sha256=excluded.sha256",
            (
                config.id,
                user.user_id,
                serialized,
                content,
                len(content),
                hashlib.sha256(content).hexdigest(),
            ),
        )
    runtime.database.path.chmod(0o600)
    return public(config)


def save(runtime, body, identifier=None):
    from .connectors import Connector

    user = principal()
    previous, content = saved(runtime, identifier) if identifier else (None, b"")
    if previous and previous.type != body.type:
        raise AnalyticsError("Create a new connection to change its type.")
    values = body.model_dump(exclude={"password", "bearer_token"})
    values["name"] = body.name.strip()
    if not values["name"]:
        raise AnalyticsError("A connection needs a name.")
    headers = {}
    if body.type == "sqlite":
        if previous is None:
            raise AnalyticsError("Upload a SQLite file to create this connection.")
        table = next(
            (t for t in sqlite_tables(content) if t["name"] == body.table), None
        )
        if table is None or not {body.source_column, body.target_column} <= set(
            table["columns"]
        ):
            raise AnalyticsError(
                "Choose a table and source/target columns from this database."
            )
        values["url"] = None
    else:
        network_target(runtime.settings, body.url)
        same_endpoint = (
            previous is not None and endpoint(previous.url)[1] == endpoint(body.url)[1]
        )
        if body.type == "rest":
            secret = body.bearer_token
            if secret is None and same_endpoint:
                headers = previous.headers
            elif secret:
                if any(ord(c) < 32 or ord(c) > 126 for c in secret):
                    raise AnalyticsError(
                        "The API token contains unsupported characters."
                    )
                headers = {"Authorization": "Bearer " + secret}
        else:
            parsed, _ = endpoint(body.url)
            if parsed.query:
                raise AnalyticsError(
                    "Use the Neo4j server address without query parameters."
                )
            if ":" in body.username:
                raise AnalyticsError("The Neo4j username cannot contain a colon.")
            if (
                body.password is None
                and same_endpoint
                and previous.username == body.username
            ):
                headers = previous.headers
            elif body.password:
                credential = base64.b64encode(
                    f"{body.username}:{body.password}".encode()
                ).decode()
                headers = {"Authorization": "Basic " + credential}
            if not headers:
                raise AnalyticsError("Enter the Neo4j username and password.")
            values.update(source_column="source", target_column="target", directed=True)
    config = Connector(
        id=identifier or new_id("connection"),
        users=[user.username],
        headers=headers,
        managed=True,
        **values,
    )
    return persist(runtime, config, content, updating=previous is not None)


def upload_sqlite(runtime, name, content):
    from .connectors import Connector

    user = principal()
    table = sqlite_tables(content)[0]
    columns = table["columns"]
    source = "source" if "source" in columns else columns[0]
    target = (
        "target" if "target" in columns else next(c for c in columns if c != source)
    )
    config = Connector(
        id=new_id("connection"),
        name=name[:160] or "SQLite database",
        type="sqlite",
        users=[user.username],
        table=table["name"],
        source_column=source,
        target_column=target,
        managed=True,
    )
    persist(runtime, config, content)
    return detail(runtime, config.id)


def delete(runtime, identifier):
    user = principal()
    with runtime.database._lock, runtime.database._connect() as db:
        result = db.execute(
            "DELETE FROM user_connectors WHERE id=? AND owner_id=?",
            (identifier, user.user_id),
        )
        if result.rowcount != 1:
            raise RecordNotFound("Connection not found")
