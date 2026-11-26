"""Verified benchmark instances on explicitly permitted endpoints."""

import hashlib
import json
import os
import re
import shlex
from urllib.parse import urlsplit

from .analytics import AnalyticsError
from .neo4j_backend import registry_endpoint, registry_fields


def read_json(path, limit=1024 * 1024):
    if path.stat().st_size > limit:
        raise ValueError("Registry metadata exceeds its size limit")
    return json.loads(path.read_text())


def ready_datasets(settings):
    path, root = settings.neo4j_datasets_registry, settings.neo4j_instances_root
    if path is None:
        return []
    try:
        if root is None:
            raise ValueError("An instance root is required")
        registry = read_json(path)
        if registry.get("version") != 1 or len(registry["datasets"]) > 64:
            raise ValueError("Unsupported registry")
        result, identifiers = [], set()
        for entry in registry["datasets"]:
            identifier = entry["id"]
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identifier) or identifier in identifiers:
                raise ValueError("Invalid or duplicate dataset ID")
            identifiers.add(identifier)
            endpoint, workload = registry_endpoint(entry), urlsplit(entry["workload_url"])
            if (workload.scheme != "https" or workload.hostname != "pgraphbenchweb.vercel.app"
                    or not endpoint.auth_disabled and not re.fullmatch(
                        r"GRAPHMINE_NEO4J_[A-Z0-9_]+_PASSWORD", entry.get("password_env", ""))):
                raise ValueError("Invalid benchmark connection metadata")
            directory = root / identifier
            try:
                state = read_json(directory / "status.json")
            except FileNotFoundError:
                continue
            if state.get("status") != "ready" or state.get("phase") != "ready":
                continue
            report_path = directory / "verify_report.json"
            try:
                report = read_json(report_path)
            except FileNotFoundError:
                continue
            if (state.get("id") != identifier or report.get("id") != identifier or not report.get("passed")
                    or hashlib.sha256(report_path.read_bytes()).hexdigest() != state.get("verify_report_sha256")
                    or report.get("script_hashes") != state.get("script_hashes")
                    or not state.get("load_finished_at") or not state.get("script_hashes")):
                continue
            counts = state["counts"]
            result.append({
                "id": identifier, "name": entry["name"], "status": "ready", "registry": True,
                "graph_label": None, "schemas": [], "tables": [], "workload_url": entry["workload_url"],
                "default_query": entry["default_query"], "bolt_uri": endpoint.uri,
                "password_env": entry.get("password_env"), "auth_disabled": endpoint.auth_disabled,
                "node_count": counts["total_nodes"], "relationship_count": counts["total_relationships"],
                "label_counts": counts["nodes"], "relationship_counts": counts["relationships"],
                "load_finished_at": state["load_finished_at"], "load_seconds": state["load_seconds"],
                "script_hashes": state["script_hashes"], "verified_at": state["verified_at"],
            })
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise AnalyticsError("The verified benchmark registry is unavailable.", "database_configuration", 503) from error


def sources(settings):
    from .database_sources import DatabaseSource

    result = []
    for entry in ready_datasets(settings):
        source = DatabaseSource(id="benchmark-" + entry["id"], name=entry["name"], users=["*"],
                                **registry_fields(entry))
        source._backend_settings = settings
        source._configured = True
        if source.auth_disabled:
            source._network_settings = settings
        source._catalog = {key: entry[key] for key in ("id", "registry", "load_finished_at", "load_seconds", "script_hashes", "workload_url")}
        source._registry_password_file = settings.neo4j_datasets_password_file
        result.append(source)
    return result


def password(path, name):
    """Read only the requested reference from the owner's private env file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536:
                raise ValueError("Private environment file required")
            matches = []
            for line in stream:
                line = line.strip().removeprefix("export ")
                key, separator, value = line.partition("=")
                if separator and key == name:
                    parsed = shlex.split(value, comments=True)
                    if len(parsed) != 1 or not parsed[0]:
                        raise ValueError("Invalid credential assignment")
                    matches.append(parsed[0])
            if len(matches) != 1:
                raise ValueError("Missing or duplicate credential")
            return matches[0]
    except (OSError, ValueError) as error:
        raise AnalyticsError("A database credential is not configured.", "database_configuration", 503) from error
