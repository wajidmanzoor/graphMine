"""The two Neo4j backends, their private selection, and all endpoint resolution.

Discovery is local metadata only. Resolving an endpoint never connects to it,
starts a service, or follows a server's advertised addresses. Local maintenance
tools must explicitly select ``target='local'``; they can never load data into IU
merely because IU is the active application backend.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from types import SimpleNamespace
from urllib.parse import urlsplit

BACKENDS = ("local", "iu-remote")
IU_HOST = "10.2.147.169"
IU_PORT = 7689
IU_URI = "bolt://10.2.147.169:7689"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _configuration_error():
    from .analytics import AnalyticsError
    return AnalyticsError("Neo4j backend configuration is unavailable.", "database_configuration", 503)


def _parse(uri, *, local=False):
    try:
        parsed = urlsplit(uri)
        if (parsed.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or not 1 <= (parsed.port or 7687) <= 65535):
            raise ValueError
        if parsed.hostname == IU_HOST and uri != IU_URI:
            raise ValueError
        if local and (parsed.scheme != "bolt" or parsed.hostname not in LOCAL_HOSTS or not parsed.port or parsed.path):
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise ValueError("Invalid Neo4j endpoint") from None


def local_uri(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid local Bolt port")
    return f"bolt://127.0.0.1:{port}"


@contextmanager
def state_lock(settings):
    root = Path(settings.data_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / "neo4j_backend.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def atomic_json(path, value):
    """Publish complete private state; concurrent readers never see partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_state(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise ValueError
        value = json.load(stream)
    if (not isinstance(value, dict) or value.get("version") != 1
            or value.get("active_backend") not in BACKENDS):
        raise ValueError
    return value["active_backend"]


def active_backend_id(settings):
    try:
        with state_lock(settings):
            path = Path(settings.data_root) / "neo4j_backend.json"
            try:
                return _read_state(path)
            except FileNotFoundError:
                atomic_json(path, {"version": 1, "active_backend": "iu-remote"})
                return "iu-remote"
    except (OSError, ValueError, TypeError):
        raise _configuration_error() from None


def set_active_backend(settings, backend_id):
    """Persistence primitive. The admin switch must verify/drain before using it."""
    if backend_id not in BACKENDS:
        raise ValueError("Unknown Neo4j backend")
    try:
        with state_lock(settings):
            atomic_json(Path(settings.data_root) / "neo4j_backend.json",
                        {"version": 1, "active_backend": backend_id})
    except OSError:
        raise _configuration_error() from None


@dataclass(frozen=True)
class Neo4jEndpoint:
    identifier: str
    uri: str
    database: str = "neo4j"
    _source: object = field(default=None, repr=False, compare=False)
    _write: bool = field(default=False, repr=False)
    _password_env: str | None = field(default=None, repr=False)
    _password_file: Path | None = field(default=None, repr=False)
    _credentials: tuple | None = field(default=None, repr=False, compare=False)
    auth_disabled: bool = False
    transport: str = "bolt"

    @property
    def address(self):
        parsed = _parse(self.uri)
        return parsed.hostname, parsed.port or 7687

    @property
    def auth(self):
        if self.auth_disabled:
            return None
        if self._credentials is not None:
            return self._credentials
        if self._source is not None:
            from .database_sources import source_secret
            source = self._source
            user = (source.neo4j_writer_username or source.neo4j_username) if self._write else source.neo4j_username
            name = (source.neo4j_writer_password_env or source.neo4j_password_env) if self._write else source.neo4j_password_env
            return user, source._neo4j_password or source_secret(source, name)
        if self._password_file is not None:
            from .neo4j_registry import password
            return "neo4j", password(self._password_file, self._password_env)
        from .database_sources import secret
        return "neo4j", secret(self._password_env)


@dataclass(frozen=True)
class Neo4jBackend:
    id: str
    endpoints: tuple[Neo4jEndpoint, ...]

    @property
    def connection(self):
        if len(self.endpoints) != 1:
            raise ValueError("Choose one local Neo4j instance")
        return self.endpoints[0]


def registry_endpoint(entry, password_file=None, credentials=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", entry["id"]):
        raise ValueError("Invalid Neo4j instance identifier")
    uri = entry["bolt_uri"]
    _parse(uri, local=True)
    return Neo4jEndpoint(entry["id"], uri, _password_env=entry.get("password_env"),
                         _password_file=password_file, _credentials=credentials)


def local_registry(settings):
    path = getattr(settings, "neo4j_datasets_registry", None)
    if path is None:
        return ()
    try:
        path = Path(path)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError
        document = json.loads(path.read_text())
        if document.get("version") != 1 or len(document["datasets"]) > 64:
            raise ValueError
        result = tuple(registry_endpoint(entry, getattr(settings, "neo4j_datasets_password_file", None))
                       for entry in document["datasets"])
        if len({item.identifier for item in result}) != len(result):
            raise ValueError
        return result
    except (OSError, ValueError, KeyError, TypeError):
        raise _configuration_error() from None


def backend_registry(settings):
    return {
        "local": Neo4jBackend("local", local_registry(settings)),
        "iu-remote": Neo4jBackend("iu-remote", (Neo4jEndpoint("iu-remote", IU_URI, auth_disabled=True),)),
    }


def _settings(settings, source):
    if settings is not None:
        return settings
    if source is not None:
        value = getattr(source, "_backend_settings", None) or getattr(source, "_network_settings", None)
        if value is not None:
            return value
    from .database_pools import current_database_pools
    pools = current_database_pools.get()
    if pools is not None:
        return pools.settings
    raise _configuration_error()


def get_active_neo4j(settings=None, source=None, *, write=False, target=None,
                     local_record=None, credentials=None, connector=None):
    """Resolve the active backend, or an explicitly requested maintenance target.

    A source retains its identity: an old local mapping is never silently aimed
    at the shared remote database. Target overrides are for local provisioning
    and the admin switch's pre-publication connectivity check, not public input.
    Credentials are read lazily only when a driver asks for ``endpoint.auth``.
    """
    settings = _settings(settings, source)
    identifier = active_backend_id(settings) if target is None else target
    if identifier not in BACKENDS:
        raise ValueError("Unknown Neo4j backend")
    if connector is not None:
        try:
            url = urlsplit(connector.url or "")
            if (url.scheme not in {"http", "https"} or not url.hostname
                    or url.username or url.password or url.fragment):
                raise ValueError
            remote = url.hostname == IU_HOST and (url.port or 80) == 7474
            if remote != (identifier == "iu-remote"):
                from .database import RecordNotFound
                raise RecordNotFound("Connection not found")
        except (TypeError, ValueError):
            raise ValueError("Invalid Neo4j connector endpoint") from None
        if identifier == "local":
            uri = connector.url.rstrip("/") + f"/db/{connector.database}/query/v2"
            return Neo4jBackend(identifier, (Neo4jEndpoint(connector.id, uri,
                connector.database, transport="http"),))
    if identifier == "iu-remote":
        if local_record is not None or source is not None and source.neo4j_uri != IU_URI:
            from .database import RecordNotFound
            raise RecordNotFound("Database source not found")
        return Neo4jBackend(identifier, (Neo4jEndpoint(identifier, IU_URI, auth_disabled=True),))
    if local_record is not None:
        return Neo4jBackend(identifier, (registry_endpoint(local_record,
            getattr(settings, "neo4j_datasets_password_file", None), credentials),))
    if source is not None:
        parsed = _parse(source.neo4j_uri)
        if parsed.hostname == IU_HOST:
            from .database import RecordNotFound
            raise RecordNotFound("Database source not found")
        return Neo4jBackend(identifier, (Neo4jEndpoint(source.id, source.neo4j_uri,
            source.neo4j_database, _source=source, _write=write),))
    return backend_registry(settings)[identifier]


def source_origin(source):
    """Stable persisted identity, independent of the currently selected backend."""
    return {"neo4j_uri": source.neo4j_uri, "neo4j_database": source.neo4j_database}


def source_details(source):
    parsed = _parse(source.neo4j_uri)
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return {"uri": f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else ""),
            "database": source.neo4j_database, "username": source.neo4j_username}


def configured_address(source):
    parsed = _parse(source.neo4j_uri)
    return parsed.hostname, parsed.port or 7687


def validate_pair_endpoint(body):
    try:
        _parse(body.neo4j_uri)
    except ValueError:
        raise ValueError("Use a Neo4j or Bolt server URI without embedded credentials") from None


def pair_fields(body):
    return body.model_dump(include={"neo4j_uri", "neo4j_database", "neo4j_username"})


def same_pair_endpoint(previous, body):
    return bool(previous) and all(getattr(previous, key) == getattr(body, key)
                                 for key in ("neo4j_uri", "neo4j_database", "neo4j_username"))


def registry_fields(entry):
    endpoint = registry_endpoint(entry)
    return {"neo4j_uri": endpoint.uri, "neo4j_password_env": entry["password_env"]}


def matches_registry(source, entry):
    return source.neo4j_uri == registry_endpoint(entry).uri and source.neo4j_password_env == entry["password_env"]


def deployment_settings(repository, *, registry=None, password_file=None, data_root=None):
    """Minimal context for local administrative tools; no secret file is loaded."""
    repository = Path(repository)
    return SimpleNamespace(data_root=Path(data_root or os.getenv("GRAPHMINE_AGENT_DATA_ROOT", repository / ".graphmine-agent")),
        neo4j_datasets_registry=Path(registry or repository / "deploy/neo4j-datasets/registry.json"),
        neo4j_datasets_password_file=Path(password_file) if password_file else None)


def legacy_local_record(port=None):
    return {"id": "legacy", "bolt_uri": local_uri(int(port or os.getenv("GRAPHMINE_DEMO_BOLT_PORT", "17687"))),
            "password_env": "GRAPHMINE_DEMO_NEO4J_PASSWORD"}


def local_control_endpoints(settings, units):
    """Bolt targets for registered stores and retained legacy/demo services."""
    result = {f"graphmine-neo4j-{endpoint.identifier}.service": endpoint
              for endpoint in get_active_neo4j(settings, target="local").endpoints}
    result["graphmine-neo4j.service"] = get_active_neo4j(settings, target="local",
        local_record=legacy_local_record()).connection
    demo = {"id": "transfers-demo", "bolt_uri": local_uri(17700)}
    path = getattr(settings, "database_sources_file", None)
    if path is not None:
        try:
            for source in json.loads(Path(path).read_text()):
                if source.get("id") == "local-transfers":
                    _parse(source["neo4j_uri"], local=True)
                    demo["bolt_uri"] = source["neo4j_uri"]
        except (OSError, ValueError, TypeError, KeyError):
            raise _configuration_error() from None
    result["graphmine-neo4j-transfers-demo.service"] = get_active_neo4j(
        settings, target="local", local_record=demo).connection
    unknown = set(units) - set(result) - {"graphmine-neo4j-browser.service"}
    if unknown:
        raise ValueError("No registered Bolt endpoint for local unit: " + ", ".join(sorted(unknown)))
    return {unit: result[unit] for unit in units if unit in result}


def local_browser_endpoints(settings):
    """The retained local Browser proxy must not bypass active-backend selection."""
    endpoint = get_active_neo4j(settings, local_record=legacy_local_record()).connection
    host, port = endpoint.address
    http_port = int(os.getenv("GRAPHMINE_DEMO_NEO4J_HTTP_PORT", "17474"))
    if not 1 <= http_port <= 65535:
        raise ValueError("Invalid local Neo4j HTTP port")
    return f"http://{host}:{http_port}", f"ws://{host}:{port}"
