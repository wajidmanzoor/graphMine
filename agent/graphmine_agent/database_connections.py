"""Private, owner-scoped Neo4j connections with optional PostgreSQL enrichment."""

import hashlib
import ipaddress
import json
import os
import socket
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import Field, SecretStr, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .database_sources import (
    DatabaseSource, EntityMapping, RelationshipMapping, Strict, configured,
    get_source, neo4j_session, sql_connection,
)
from .identity import current_principal
from .database_pools import invalidate, pool_scope
from .neo4j_backend import configured_address, pair_fields, same_pair_endpoint, validate_pair_endpoint


class ConnectionPair(Strict):
    name: str = Field(min_length=1, max_length=160)
    sql_enabled: bool | None = None
    host: str | None = Field(default=None, min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.:-]+$")
    port: int = Field(default=5432, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    password: SecretStr | None = Field(default=None, max_length=4096)
    sslmode: str = Field(default="prefer", pattern=r"^(disable|prefer|require|verify-ca|verify-full)$")
    neo4j_uri: str = Field(min_length=1, max_length=2048)
    neo4j_database: str = Field(default="neo4j", min_length=1, max_length=128)
    neo4j_username: str = Field(default="neo4j", min_length=1, max_length=128)
    neo4j_password: SecretStr | None = Field(default=None, max_length=4096)
    entities: list[EntityMapping] = Field(default_factory=list, max_length=64)
    relationships: list[RelationshipMapping] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def endpoint(self):
        sql_fields = (self.host, self.database, self.username, self.password)
        if self.sql_enabled is None:
            self.sql_enabled = any(value is not None for value in sql_fields)
        if self.sql_enabled and not all((self.host, self.database, self.username)):
            raise ValueError("SQL enrichment needs a host, database and username")
        if not self.sql_enabled and any(value is not None for value in sql_fields):
            raise ValueError("Remove SQL credentials and server details when SQL enrichment is disabled")
        validate_pair_endpoint(self)
        # Validate cross-table keys here so errors never reach the persistence
        # layer (or include the credential-bearing request in a response).
        DatabaseSource(
            id="validation", name=self.name, users=["*"], sql_dsn_env="MANAGED" if self.sql_enabled else None,
            **pair_fields(self), neo4j_password_env="MANAGED",
            entities=self.entities, relationships=self.relationships,
        )
        return self


def owner_directory(settings):
    user = current_principal.get()
    owner = "account:" + user.user_id if user else "local"
    return settings.data_root / "database-connections" / hashlib.sha256(owner.encode()).hexdigest()


def load_source(settings, document):
    source = DatabaseSource.model_validate(document["source"])
    if source.auth_disabled:
        raise ValueError("Saved user connections require Neo4j credentials")
    source._sql_credentials = document.get("sql") or {}
    source._neo4j_password = document["neo4j_password"]
    if not isinstance(source._sql_credentials, dict) or bool(source._sql_credentials) != bool(source.sql_type):
        raise ValueError("SQL credential settings do not match the connection")
    if source.sql_type and not all(source._sql_credentials.get(key) for key in ("host", "database", "username", "password")):
        raise ValueError("SQL credential settings are incomplete")
    if not isinstance(source._neo4j_password, str) or not source._neo4j_password:
        raise ValueError("Neo4j credential settings are incomplete")
    source._managed = True
    source._network_settings = settings
    source._backend_settings = settings
    return source


def managed_sources(settings):
    directory = owner_directory(settings)
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.json")):
        try:
            info = path.stat()
            if info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_size > 1024 * 1024:
                raise ValueError
            source = load_source(settings, json.loads(path.read_text()))
            source._config_stamp = (path, info.st_ino, info.st_mtime_ns, info.st_size)
            result.append(source)
        except (OSError, ValueError, KeyError) as exc:
            raise AnalyticsError("A saved database connection is unreadable.", "database_configuration", 503) from exc
    return result


def network_address(settings, host, port):
    """Keep account connections within the existing connector network policy."""
    allowed = set()
    if settings.accounts_enabled:
        for origin in settings.connector_allowed_origins:
            parsed = urlsplit(origin)
            allowed.add((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)))
        # Only this user's configured pairs authorize local database endpoints.
        principal = current_principal.get()
        for source in configured(settings):
            if "*" not in source.users and not (principal and principal.username in source.users):
                continue
            details = source.connection_details()
            sql = details["sql"] or {}
            if sql.get("host"):
                allowed.add((sql["host"], sql["port"]))
            allowed.add(configured_address(source))
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        if not addresses:
            raise OSError
    except OSError as exc:
        raise AnalyticsError("The database hostname could not be resolved.", "database_connection") from exc
    if settings.accounts_enabled and (host, port) not in allowed and any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise AnalyticsError("This private database address must be allowed in the server's connection settings.", "database_connection")
    return addresses[0]


def check_connection(source):
    # ContextVars carry the current account into driver resolvers.
    from contextvars import copy_context

    def sql():
        if source.sql_type is None:
            return {"configured": False, "connected": None, "message": "SQL enrichment is not configured."}
        try:
            with sql_connection(source) as connection:
                connection.execute("SELECT 1").fetchone()
            return {"configured": True, "connected": True, "message": "Connected"}
        except Exception:
            return {"configured": True, "connected": False, "message": "Could not connect. Check the server address and credentials."}

    def neo4j():
        try:
            from neo4j import Query, unit_of_work
            with neo4j_session(source) as session:
                if source.auth_disabled:
                    @unit_of_work(timeout=5)
                    def read(transaction):
                        return transaction.run("RETURN 1 AS connected").consume()
                    session.execute_read(read)
                else:
                    session.run(Query("RETURN 1 AS connected", timeout=5)).consume()
            return {"connected": True, "message": "Connected"}
        except Exception:
            return {"connected": False, "message": "Could not connect. Check the server address and credentials."}

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(copy_context().run, sql)
        b = pool.submit(copy_context().run, neo4j)
        result = {"sql": a.result(), "neo4j": b.result()}
    result["connected"] = result["neo4j"]["connected"] and (source.sql_type is None or result["sql"]["connected"])
    result["query_available"] = result["neo4j"]["connected"]
    result["enrichment_available"] = bool(source.capabilities()["enrichment"] and result["sql"]["connected"])
    return result


def save_pair(settings, body, identifier=None):
    previous = get_source(settings, identifier) if identifier else None
    if previous and not previous.managed:
        raise AnalyticsError("Server connections are configured by the administrator. Add a separate connection for another database.", "database_configuration")
    directory = owner_directory(settings)
    if not previous and directory.exists() and len(list(directory.glob("*.json"))) >= 100:
        raise AnalyticsError("The saved connection limit has been reached.", "resource_limit")
    identifier = identifier or "db-" + uuid.uuid4().hex
    same_sql = previous and bool(previous._sql_credentials) and body.sql_enabled and all(
        previous._sql_credentials[key] == getattr(body, key)
        for key in ("host", "port", "database", "username", "sslmode")
    )
    same_neo = same_pair_endpoint(previous, body)
    sql_password = body.password.get_secret_value() if body.password else (
        previous._sql_credentials["password"] if same_sql else None
    )
    neo_password = body.neo4j_password.get_secret_value() if body.neo4j_password else (
        previous._neo4j_password if same_neo else None
    )
    if not neo_password or body.sql_enabled and not sql_password:
        raise AnalyticsError("Enter the password for each configured database. Credentials must be entered again when changing servers or users.", "database_connection")
    # Validate network targets before saving credentials.
    if body.sql_enabled:
        network_address(settings, body.host, body.port)
    host, port = configured_address(body)
    network_address(settings, host, port)
    source = DatabaseSource(
        id=identifier, name=body.name, users=["*"], revision=(previous.revision if previous else 1),
        sql_dsn_env="MANAGED" if body.sql_enabled else None, **pair_fields(body),
        neo4j_password_env="MANAGED", entities=body.entities, relationships=body.relationships,
    )
    document = {
        "source": source.model_dump(),
        "sql": {**body.model_dump(include={"host", "port", "database", "username", "sslmode"}), "password": sql_password} if body.sql_enabled else {},
        "neo4j_password": neo_password,
    }
    source = load_source(settings, document)
    if previous and source.fingerprint() != previous.fingerprint():
        source.revision += 1
        document["source"]["revision"] = source.revision
    # Do not cache uncommitted credentials or retire a valid pool on failed edits.
    with pool_scope(None):
        health = check_connection(source)
    if not health["connected"]:
        failed = " and ".join(name for name in ("sql", "neo4j") if (name != "sql" or body.sql_enabled) and not health[name]["connected"])
        raise AnalyticsError(f"Could not connect to {failed}. Check the address, database name and credentials.", "database_connection", 502)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(document, stream)
        Path(temporary).replace(directory / f"{identifier}.json")
        invalidate(identifier)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**source.public(), "status": health}


def delete_pair(settings, identifier):
    source = get_source(settings, identifier)
    if not source.managed:
        raise AnalyticsError("Server connections are configured by the administrator.", "database_configuration")
    (owner_directory(settings) / f"{source.id}.json").unlink()
    invalidate(source.id)
    return {"deleted": source.id}


def register_connection_routes(router):
    def validate_pair(body):
        try:
            return ConnectionPair.model_validate(body)
        except ValidationError as error:
            # FastAPI's default validation response includes the original input.
            # Never echo a connection body containing passwords.
            detail = error.errors(include_input=False, include_context=False)[0]
            field = ".".join(str(part) for part in detail["loc"])
            message = (field + ": " if field else "") + detail["msg"]
            raise AnalyticsError(message, "database_connection_settings", 422) from None

    async def execute(request, function, *args):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database connections are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(function, *args)

    @router.post("/database-sources", status_code=201)
    async def create(body: dict, request: Request):
        return await execute(request, save_pair, request.app.state.runtime.settings, validate_pair(body))

    @router.put("/database-sources/{source_id}")
    async def update(source_id: str, body: dict, request: Request):
        return await execute(request, save_pair, request.app.state.runtime.settings, validate_pair(body), source_id)

    @router.delete("/database-sources/{source_id}")
    async def delete(source_id: str, request: Request):
        return await execute(request, delete_pair, request.app.state.runtime.settings, source_id)

    @router.post("/database-sources/{source_id}/status")
    async def status(source_id: str, request: Request):
        source = get_source(request.app.state.runtime.settings, source_id)
        return await execute(request, check_connection, source)

    @router.get("/database-sources/{source_id}/settings")
    def detail(source_id: str, request: Request):
        source = get_source(request.app.state.runtime.settings, source_id)
        return {
            **source.public(),
            "entities": [m.model_dump() for m in source.entities],
            "relationships": [m.model_dump() for m in source.relationships],
        }
