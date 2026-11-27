"""Lazy access to the pinned Tentō wheel; importing this module needs no engine.

Native loading belongs in a disposable semantic worker (Phase 2), not startup.
The Phase 1 smoke tool also uses this boundary. Installation is distinct from
passing the live-provider and complete integration gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import importlib
from importlib import metadata, resources
import json
from pathlib import Path
from types import ModuleType

from .errors import AnalyticsError


def engine_lock() -> dict:
    return json.loads(resources.files(__package__).joinpath("semantic_engine.lock.json").read_text())


@dataclass(frozen=True)
class SemanticEngine:
    module: ModuleType
    manifest: dict


@lru_cache(maxsize=1)
def load_engine() -> SemanticEngine:
    """Reject missing, foreign, or mismatched bindings with the normal HTTP 503."""
    lock = engine_lock()
    try:
        distribution = metadata.distribution(lock["distribution"])
    except metadata.PackageNotFoundError:
        raise AnalyticsError(
            "Semantic support is not installed. Ask an administrator to build Tentō "
            "with deploy/tento/build.sh and install the agent semantic extra.",
            "semantic_unavailable", 503,
        ) from None
    try:
        if distribution.version != lock["version"]:
            raise ValueError("Different engine distribution")
        package = Path(distribution.locate_file("ladybug")).resolve()
        manifest = json.loads((package / "_graphmine_tento.json").read_text())
        if (manifest["commit"] != lock["commit"] or manifest["backend"] != "pybind"
                or manifest.get("patches", []) != lock.get("patches", [])):
            raise ValueError("Different engine source")
        native_path = (package / manifest["native_file"]).resolve()
        if native_path.parent != package:
            raise ValueError("Native artifact is outside the package")
        with native_path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["native_sha256"]:
                raise ValueError("Different native artifact")
        ladybug = importlib.import_module("ladybug")
        if Path(ladybug.__file__).resolve().parent != package:
            raise ValueError("Another Ladybug shadows the installed wheel")
        backend = importlib.import_module("ladybug._backend").get_pybind_module()
        if backend is None or Path(backend.__file__).resolve() != native_path:
            raise ValueError("The pinned pybind backend is not available")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError):
        raise AnalyticsError(
            "The semantic engine installation does not match this GraphMine release. "
            "Rebuild and reinstall it with deploy/tento/build.sh.",
            "semantic_incompatible", 503,
        ) from None
    return SemanticEngine(ladybug, manifest)


def require_live_controls() -> None:
    """Fail before contacting a model when the pinned engine lacks its controls."""
    lock = engine_lock()
    if (lock["live_blockers"] or lock["integration_blockers"] or not lock.get("patches")
            or lock.get("contract") != "supervised-live-v1"):
        raise AnalyticsError(
            "Live semantic execution requires the verified native request controls, "
            "query budget and independent answer store for this GraphMine release.",
            "semantic_controls_unsupported", 503,
        )


def live_supported():
    try:
        require_live_controls()
        return metadata.version(engine_lock()["distribution"]) == engine_lock()["version"]
    except (AnalyticsError, metadata.PackageNotFoundError):
        return False
