"""Fail-closed native capability gate, tied to exact builds and oracle reports.

This is a local reproducibility check, not a signature against malicious edits.
Python reference reports cannot authorize execution through this gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .dispatch import execution_environment, native_library
from .exceptions import GraphMineError


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def profile_hash(card):
    return hashlib.sha256(
        json.dumps(card, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Evidence source is missing or outside the repository")
    return path


def _check_hashes(root, files):
    if not files:
        raise ValueError("Empty evidence file inventory")
    for name, digest in files.items():
        if sha(_path(root, name)) != digest:
            raise ValueError(f"Evidence file changed: {name}")


def verify_report(root, report, implementation, binary):
    try:
        if not {report["report"], report["metadata"]} <= set(report["artifacts"]):
            raise ValueError("Report and metadata both need artifact hashes")
        _check_hashes(root, report["artifacts"])
        metadata = json.loads(_path(root, report["metadata"]).read_text())
        if metadata["implementation_sha256"] != implementation:
            raise ValueError("Report was produced by a different native implementation")
        if metadata["native_library_sha256"] != binary:
            raise ValueError("Report was produced by a different native binary")
        if (
            not metadata["sources_unchanged_during_run"]
            or not metadata["build_unchanged_during_run"]
        ):
            raise ValueError("Sources or build changed during verification")
        _check_hashes(root, metadata["source_files"])
        path = _path(root, report["report"])
        if report["format"] == "junit":
            document = ET.parse(path).getroot()
            suites = (
                [document]
                if document.tag == "testsuite"
                else document.findall("testsuite")
            )
            counts = {
                key: sum(int(s.attrib[key]) for s in suites)
                for key in ("tests", "failures", "errors", "skipped")
            }
            if counts["tests"] < 1 or any(
                counts[k] for k in ("failures", "errors", "skipped")
            ):
                raise ValueError(
                    "Report is empty or contains failures, errors or skips"
                )
            passed = counts["tests"]
            if passed != metadata["collected_test_count"]:
                raise ValueError("Report and collected test count disagree")
        elif report["format"] == "native_suites":
            rows = json.loads(path.read_text())
            if not rows or any(
                row["failed"]
                or row["passed_requests"] < 1
                or row["implementation_sha256"] != implementation
                for row in rows
            ):
                raise ValueError(
                    "Native suite is empty, failed, or belongs to another build"
                )
            passed = sum(row["passed_requests"] for row in rows)
        else:
            raise ValueError("Unknown native evidence format")
        if passed != report["passed"]:
            raise ValueError("Evidence execution count changed")
        if metadata["device"] != report["device"]:
            raise ValueError("Evidence device policy differs")
        if report["device"] not in {"cpu", "gpu"}:
            raise ValueError("Unknown evidence device")
        if report["device"] == "cpu" and metadata["cuda_visible_devices"] != "":
            raise ValueError("CPU verification must hide CUDA devices")
        if report["device"] == "gpu" and not metadata.get("gpu_hardware"):
            raise ValueError("GPU verification needs actual device evidence")
        return {
            "id": report["id"],
            "status": "passed",
            "device": report["device"],
            "tests": passed,
            "report": report["report"],
            "gpu_hardware": metadata.get("gpu_hardware"),
        }
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        return {
            "id": report.get("id", "unknown"),
            "status": "unverified",
            "reason": str(exc),
        }


def _verify_build(root, build, library, catalog):
    if build["implementation_sha256"] != catalog["implementation_sha256"]:
        raise ValueError("Native implementation differs from verified build")
    if sha(library.path) != build["binary_sha256"]:
        raise ValueError("Native binary differs from verified build")
    _check_hashes(root, build["sources"])
    runtime_files = {
        str(path.relative_to(root))
        for path in (root / "library/runtime").rglob("*")
        if path.suffix in {".cpp", ".hpp", ".in"} and path.is_file()
    }
    if not runtime_files <= set(build["sources"]):
        raise ValueError("Native source inventory changed")
    linkage = subprocess.check_output(["ldd", library.path], text=True)
    if "not found" in linkage:
        raise ValueError("Native dependency is unavailable")
    dependencies = {
        str(Path(match).resolve()) for match in re.findall(r"=> (/\S+)", linkage)
    }
    if dependencies != set(build["dependencies"]):
        raise ValueError("Native dependency inventory changed")
    for name, digest in build["dependencies"].items():
        if sha(name) != digest:
            raise ValueError(f"Native dependency changed: {name}")
    # Isolated research workers are part of a backend, not optional evidence.
    for name, digest in build.get("workers", {}).items():
        if sha(name) != digest:
            raise ValueError(f"Native worker changed: {name}")


def capabilities(repository_root):
    root = Path(repository_root).resolve()
    library = native_library()
    catalog = library.catalog()
    try:
        inventory = json.loads(
            (root / "catalog/native_execution_evidence.json").read_text()
        )
    except (OSError, ValueError):
        inventory = {}
    reports, profiles, reasons = [], {}, []
    for build in inventory.get("builds", []):
        if build.get("implementation_sha256") != catalog["implementation_sha256"]:
            continue
        try:
            _verify_build(root, build, library, catalog)
            profiles = build["profiles"]
            reports = [
                verify_report(
                    root,
                    report,
                    catalog["implementation_sha256"],
                    build["binary_sha256"],
                )
                for report in build["reports"]
            ]
            break
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            subprocess.SubprocessError,
        ) as exc:
            reasons.append(str(exc))
    verified = {
        report["id"]: report for report in reports if report["status"] == "passed"
    }
    failures = {
        (entry["operation"], entry["backend"])
        for entry in inventory.get("known_failures", [])
        if entry.get("implementation_sha256")
        in (None, catalog["implementation_sha256"])
    }
    cards = catalog["operations"]
    for card in cards:
        profile = profiles.get(card["id"], {})
        digest = profile_hash(card)
        matched = profile.get("profile_sha256") == digest
        available = []
        for backend in card["backends"]:
            evidence = profile.get("backends", {}).get(backend["id"], [])
            valid = bool(
                matched
                and backend["compiled"]
                and evidence
                and all(
                    name in verified and verified[name]["device"] == backend["device"]
                    for name in evidence
                )
                and (card["id"], backend["id"]) not in failures
            )
            backend["verified"] = valid
            backend["evidence"] = evidence
            backend["verified_devices"] = sorted(
                {
                    verified[name]["gpu_hardware"]["uuid"]
                    for name in evidence
                    if name in verified and verified[name].get("gpu_hardware")
                }
            )
            if valid:
                available.append(backend["id"])
        card["profile_sha256"] = digest
        card["verified_backends"] = available
        card["execution"] = {
            device: any(
                b["verified"] and b["device"] == device for b in card["backends"]
            )
            for device in ("cpu", "gpu")
        }
        card["evidence_state"] = (
            "verified_profile" if available else "verification_required"
        )
    return {
        "schema_version": "2.0.0",
        "implementation_sha256": catalog["implementation_sha256"],
        "environment": execution_environment(),
        "families": catalog["families"],
        "operations": cards,
        "reports": reports,
        "verification_issues": reasons,
        "scope": "Native profiles whose source, binary, dependencies and independent reports match this process",
    }


def require_workflow_evidence(checked, caps):
    cards = {card["id"]: card for card in caps["operations"]}
    for step in checked["plan"]["steps"]:
        card = cards[step["operation"]]
        device = "gpu" if step["device"] == "gpu" else "cpu"
        if not card["execution"][device]:
            raise GraphMineError(
                f"Current native {device} correctness evidence is missing or stale for {step['operation']}"
            )
