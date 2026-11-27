"""Admin-owned provider metadata with credentials kept out of SQLite and responses."""

import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit
import uuid

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .errors import AnalyticsError

ALIAS = r"^[a-z][a-z0-9_]{0,31}$"
BUILTIN = "graphmine"


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    clear_key: bool = False
    expected_revision: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("base_url")
    @classmethod
    def address(cls, value):
        try:
            parsed = urlsplit(value)
            port = parsed.port
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in value)):
                raise ValueError
        except ValueError:
            raise ValueError("Use an HTTP(S) base URL without credentials, query strings or fragments.") from None
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value):
        if value is not None and any(not 33 <= ord(ch) <= 126 for ch in value.get_secret_value()):
            raise ValueError("The API key must contain printable ASCII characters without spaces.")
        return value


class AliasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str = Field(pattern=ALIAS)
    provider_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=256)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("model_id")
    @classmethod
    def model_name(cls, value):
        if not value.strip() or any(ord(ch) < 32 for ch in value):
            raise ValueError("Supply a model ID without control characters.")
        return value


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS semantic_providers (id TEXT PRIMARY KEY, document TEXT NOT NULL, revision INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS semantic_aliases (alias TEXT PRIMARY KEY, provider_id TEXT NOT NULL, model_id TEXT NOT NULL, revision INTEGER NOT NULL)")


def builtin(settings):
    try:
        address = ProviderInput.address(settings.llm_base_url)
    except ValueError:
        address = None  # A legacy credential-bearing URL must never reach the browser.
    return {"id": BUILTIN, "name": "GraphMine vLLM", "base_url": address, "configuration_valid": address is not None,
            "revision": 1, "builtin": True, "key_configured": bool(settings.llm_api_key), "authentication": "server"}


def public(identifier, document, revision):
    return {"id": identifier, "name": document["name"], "base_url": document["base_url"], "revision": revision,
            "builtin": False, "key_configured": bool(document.get("secret_ref")), "authentication": "stored" if document.get("secret_ref") else "none"}


def catalog(runtime):
    with runtime.database._connect() as db:
        initialize(db)
        providers = [builtin(runtime.settings)] + [public(row[0], json.loads(row[1]), row[2]) for row in db.execute("SELECT id,document,revision FROM semantic_providers ORDER BY id")]
        aliases = [{"alias": "qwen", "provider_id": BUILTIN, "model_id": runtime.settings.llm_model, "revision": 1, "builtin": True},
                   {"alias": "mock", "provider_id": None, "model_id": "mock:echo", "revision": 1, "builtin": True}]
        aliases.extend({**dict(row), "builtin": False} for row in db.execute("SELECT * FROM semantic_aliases ORDER BY alias"))
    return {"providers": providers, "aliases": aliases}


def resolve(runtime, alias):
    """Resolve one worker's provider, keeping its credential out of metadata."""
    configured = catalog(runtime)
    selected = next((item for item in configured["aliases"] if item["alias"] == alias), None)
    if selected is None or not selected["provider_id"]:
        raise AnalyticsError("Choose an available live model alias.", "semantic_alias", 422)
    provider = next((item for item in configured["providers"] if item["id"] == selected["provider_id"]), None)
    if provider is None or not provider["base_url"]:
        raise AnalyticsError("The configured provider is unavailable.", "semantic_provider", 503)
    if provider["id"] == BUILTIN:
        credential = runtime.settings.llm_api_key
    else:
        with runtime.database._connect() as db:
            row = db.execute("SELECT document,revision FROM semantic_providers WHERE id=?", (provider["id"],)).fetchone()
        if row is None or row[1] != provider["revision"]:
            conflict()
        reference = json.loads(row[0]).get("secret_ref")
        credential = read_secret(runtime, reference) if reference else ""
    return provider, selected, credential


def conflict():
    raise AnalyticsError("This configuration changed. Reload and review the current values.", "settings_conflict", 409)


def private_directory(runtime):
    path = runtime.settings.data_root / "semantic-credentials"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise AnalyticsError("The semantic credential directory must be private to the server account.", "semantic_credentials", 503)
    return path


def write_secret(runtime, value):
    directory = private_directory(runtime)
    fd, path = tempfile.mkstemp(prefix="key-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(path).name
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def read_secret(runtime, reference):
    if not reference or not re.fullmatch(r"key-[a-zA-Z0-9_]+", reference):
        raise AnalyticsError("The provider credential is unavailable.", "semantic_credentials", 503)
    try:
        path = private_directory(runtime) / reference
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_size > 4096:
                raise ValueError
            return stream.read()
    except (OSError, ValueError):
        raise AnalyticsError("The provider credential is unavailable.", "semantic_credentials", 503) from None


def _remove_secret(runtime, reference):
    if reference:
        try:
            (runtime.settings.data_root / "semantic-credentials" / reference).unlink(missing_ok=True)
        except OSError:
            pass  # An unreferenced private file cannot be used by a provider.


def save_provider(runtime, body, identifier=None):
    if identifier == BUILTIN:
        raise AnalyticsError("GraphMine vLLM follows the server configuration.", "semantic_provider", 409)
    created = identifier is None
    identifier = identifier or "provider_" + uuid.uuid4().hex
    if body.api_key is not None and body.clear_key:
        raise ValueError("Choose either a new key or removal of the saved key.")
    new_secret = old_secret = None
    try:
        with runtime.database._lock, runtime.database._connect() as db:
            initialize(db)
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document,revision FROM semantic_providers WHERE id=?", (identifier,)).fetchone()
            if not created and row is None:
                raise AnalyticsError("The provider is no longer available.", "semantic_provider", 404)
            if row and body.expected_revision != row[1]:
                conflict()
            if created and db.execute("SELECT count(*) FROM semantic_providers").fetchone()[0] >= 32:
                raise AnalyticsError("At most 32 semantic providers can be configured.", "resource_limit")
            old = json.loads(row[0]) if row else {}
            old_secret = old.get("secret_ref")
            if old_secret and old["base_url"] != body.base_url and body.api_key is None and not body.clear_key:
                raise ValueError("Supply a new key or clear the saved key when changing its endpoint.")
            new_secret = write_secret(runtime, body.api_key.get_secret_value()) if body.api_key is not None else None
            document = {"name": body.name, "base_url": body.base_url, "secret_ref": new_secret or (None if body.clear_key else old_secret)}
            revision = row[1] + 1 if row else 1
            before = public(identifier, old, row[1]) if row else {}
            after = public(identifier, document, revision)
            db.execute("INSERT INTO semantic_providers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,revision=excluded.revision",
                       (identifier, json.dumps(document), revision))
            runtime.accounts._audit(db, "semantic.provider.saved", identifier, before=before, after={**after, "credential_changed": body.api_key is not None or body.clear_key})
    except Exception:
        _remove_secret(runtime, new_secret)
        raise
    if old_secret and old_secret != document["secret_ref"]:
        _remove_secret(runtime, old_secret)
    return after


def delete_provider(runtime, identifier, expected_revision):
    if identifier == BUILTIN:
        raise AnalyticsError("The GraphMine provider is managed by the server.", "semantic_provider", 409)
    with runtime.database._lock, runtime.database._connect() as db:
        initialize(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT document,revision FROM semantic_providers WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise AnalyticsError("The provider is no longer available.", "semantic_provider", 404)
        if row[1] != expected_revision:
            conflict()
        if db.execute("SELECT 1 FROM semantic_aliases WHERE provider_id=?", (identifier,)).fetchone():
            raise AnalyticsError("Remove this provider's aliases first.", "semantic_provider_in_use", 409)
        document = json.loads(row[0])
        db.execute("DELETE FROM semantic_providers WHERE id=?", (identifier,))
        runtime.accounts._audit(db, "semantic.provider.deleted", identifier, before=public(identifier, document, row[1]), after={})
    _remove_secret(runtime, document.get("secret_ref"))
    return {"deleted": identifier}


def save_alias(runtime, body):
    if body.alias in {"qwen", "mock"}:
        raise AnalyticsError("The qwen and mock aliases are managed by the server.", "semantic_alias", 409)
    with runtime.database._lock, runtime.database._connect() as db:
        initialize(db)
        db.execute("BEGIN IMMEDIATE")
        if body.provider_id != BUILTIN and not db.execute("SELECT 1 FROM semantic_providers WHERE id=?", (body.provider_id,)).fetchone():
            raise AnalyticsError("Choose an existing provider.", "semantic_provider", 422)
        row = db.execute("SELECT * FROM semantic_aliases WHERE alias=?", (body.alias,)).fetchone()
        if row is not None and row["revision"] != body.expected_revision or row is None and body.expected_revision is not None:
            conflict()
        if row is None and db.execute("SELECT count(*) FROM semantic_aliases").fetchone()[0] >= 64:
            raise AnalyticsError("At most 64 custom aliases can be configured.", "resource_limit")
        after = {"alias": body.alias, "provider_id": body.provider_id, "model_id": body.model_id, "revision": row["revision"] + 1 if row else 1}
        db.execute("INSERT INTO semantic_aliases VALUES (:alias,:provider_id,:model_id,:revision) ON CONFLICT(alias) DO UPDATE SET provider_id=excluded.provider_id,model_id=excluded.model_id,revision=excluded.revision", after)
        runtime.accounts._audit(db, "semantic.alias.saved", body.alias, before=dict(row) if row else {}, after=after)
    return {**after, "builtin": False}


def delete_alias(runtime, alias, expected_revision):
    if alias in {"qwen", "mock"}:
        raise AnalyticsError("The qwen and mock aliases are managed by the server.", "semantic_alias", 409)
    with runtime.database._lock, runtime.database._connect() as db:
        initialize(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM semantic_aliases WHERE alias=?", (alias,)).fetchone()
        if row is None:
            raise AnalyticsError("The alias is no longer available.", "semantic_alias", 404)
        if row["revision"] != expected_revision:
            conflict()
        db.execute("DELETE FROM semantic_aliases WHERE alias=?", (alias,))
        runtime.accounts._audit(db, "semantic.alias.deleted", alias, before=dict(row), after={})
    return {"deleted": alias}


def connection_test(runtime, identifier):
    # No completion endpoint, redirects, proxy environment, or provider response
    # text crosses this boundary. A reachable catalog is not live acceptance.
    with runtime.database._connect() as db:
        initialize(db)
        if identifier == BUILTIN:
            provider, credential = builtin(runtime.settings), runtime.settings.llm_api_key
        else:
            row = db.execute("SELECT document,revision FROM semantic_providers WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise AnalyticsError("The provider is no longer available.", "semantic_provider", 404)
            document = json.loads(row[0])
            provider = public(identifier, document, row[1])
            credential = read_secret(runtime, document["secret_ref"]) if document.get("secret_ref") else None
        aliases = [a for a in catalog(runtime)["aliases"] if a["provider_id"] == identifier]
    started = time.monotonic()
    connected, code, models = False, "unavailable", set()
    try:
        if not provider["base_url"]:
            raise ValueError
        headers = {"Authorization": "Bearer " + credential} if credential else {}
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", provider["base_url"] + "/models", headers=headers) as response:
                if response.status_code in {401, 403}:
                    code = "authentication_failed"
                elif response.status_code != 200:
                    code = "model_catalog_unavailable"
                else:
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 256 * 1024 or time.monotonic() - started > 8:
                            raise ValueError
                    data = json.loads(raw)
                    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                        raise ValueError
                    models = {item["id"] for item in data["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)}
                    connected, code = True, "connected"
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError):
        code = "unavailable"
    result = {"provider_id": identifier, "revision": provider["revision"], "connected": connected, "code": code,
              "checked_at": time.time(), "elapsed_ms": round((time.monotonic() - started) * 1000),
              "models": [{"alias": a["alias"], "available": a["model_id"] in models} for a in aliases],
              "live_execution_verified": False}
    with runtime.database._connect() as db:
        runtime.accounts._audit(db, "semantic.provider.tested", identifier, before={}, after=result)
    return result
