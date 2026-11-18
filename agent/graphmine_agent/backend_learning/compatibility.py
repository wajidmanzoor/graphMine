"""Prove that historical benchmark timings differ only in the CLI dispatcher.

The native inventory includes the standalone CLI even though it is not linked
into the runtime library. This exception applies to model fitting only; native
admission still requires fresh evidence for the exact current binary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CLI = "library/src/cli/graphmine.cpp"


def benchmark_compatibility(evidence_path, implementation):
    builds = json.loads(Path(evidence_path).read_text())["builds"]
    current = next(b for b in builds if b["implementation_sha256"] == implementation)
    result = {}
    for prior in builds:
        original = prior["implementation_sha256"]
        if original == implementation or set(prior["sources"]) != set(current["sources"]):
            continue
        changed = [p for p in current["sources"] if prior["sources"][p] != current["sources"][p]]
        if changed != [CLI]:
            continue
        profiles = lambda b: {name: (p["profile_sha256"], sorted(p["backends"])) for name, p in b["profiles"].items()}
        workers = lambda b: sorted((Path(p).name, digest) for p, digest in b["workers"].items())
        if (profiles(prior) != profiles(current) or workers(prior) != workers(current)
                or prior["dependencies"] != current["dependencies"]
                or prior["isolated_build_recipes"] != current["isolated_build_recipes"]):
            continue
        common = {p: h for p, h in current["sources"].items() if p != CLI}
        result[original] = dict(observed_implementation_sha256=original,
            current_implementation_sha256=implementation, changed_sources=changed,
            algorithm_sources_sha256=hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest(),
            previous_cli_sha256=prior["sources"][CLI], current_cli_sha256=current["sources"][CLI],
            observed_binary_sha256=prior["binary_sha256"], current_binary_sha256=current["binary_sha256"],
            identical_profiles_workers_dependencies=True,
            scope="Historical benchmark observations only; no native admission or shadow-history exemption")
    return result
