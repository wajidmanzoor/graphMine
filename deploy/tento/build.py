#!/usr/bin/env python3
"""Build unchanged Tentō sources and package a local, interpreter-specific wheel."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "agent/graphmine_agent/semantic_engine.lock.json"
BUILD_REQUIREMENTS = ["setuptools==80.9.0", "wheel==0.45.1", "numpy==2.5.5"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def output(command):
    return subprocess.check_output(command, text=True).strip()


def checked_source(source, lock):
    if not (source / "ladybug/tools/python_api/Makefile").is_file():
        raise ValueError("Initialize the private submodule: git submodule update --init third_party/tento")
    commit = output(["git", "-C", str(source), "rev-parse", "HEAD"])
    if commit != lock["commit"]:
        raise ValueError("Tentō HEAD does not match semantic_engine.lock.json")
    if output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Tentō has tracked changes; build the unmodified pinned source")


def stage_package(stage, source, native, lock):
    package = stage / "ladybug"
    shutil.copytree(source / "ladybug/tools/python_api/src_py", package,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(native, package / native.name)
    manifest = {
        "repository": lock["repository"], "commit": lock["commit"],
        "backend": "pybind", "native_file": native.name, "native_sha256": digest(native),
    }
    (package / "_graphmine_tento.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(source / "ladybug/LICENSE", stage / "LICENSE")
    # Keep bundled dependency notices with the binary, without editing the submodule.
    for path in (source / "ladybug/third_party").rglob("*"):
        if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            target = package / "_licenses" / path.relative_to(source / "ladybug")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (stage / "pyproject.toml").write_text(f'''[build-system]
requires = ["setuptools==80.9.0", "wheel==0.45.1"]
build-backend = "setuptools.build_meta"

[project]
name = "{lock['distribution']}"
version = "{lock['version']}"
description = "GraphMine's pinned source build of Tentō (pybind backend)"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy>=1.26,<3"]
license = {{file = "LICENSE"}}

[tool.setuptools]
packages = ["ladybug"]
include-package-data = true

[tool.setuptools.package-data]
ladybug = ["*.so", "*.pyd", "*.json", "py.typed", "_licenses/**/*"]
''')
    # The extension is already compiled from Tentō. Mark the wheel as native so
    # pip cannot install it on a different platform or Python ABI.
    (stage / "setup.py").write_text('''from setuptools import Distribution, setup

class NativeDistribution(Distribution):
    def has_ext_modules(self):
        return True

setup(distclass=NativeDistribution)
''')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path,
                        help="Target virtualenv interpreter; production environments must not be used")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/tento")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--install", action="store_true", help="Also install the wheel into --python's virtualenv")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    for tool in ("git", "make", "cmake", "ninja", "uv", "c++"):
        if not shutil.which(tool):
            parser.error(f"Required build tool is missing: {tool}")
    # Do not resolve the interpreter symlink: doing so would bypass its virtualenv.
    target_python = str(args.python.absolute())
    target = json.loads(output([target_python, "-c",
        "import json,sys,sysconfig; print(json.dumps(dict(venv=sys.prefix != sys.base_prefix, "
        "implementation=sys.implementation.name, version=list(sys.version_info[:2]), "
        "platform=sys.platform, suffix=sysconfig.get_config_var('EXT_SUFFIX'))))"]))
    if not target["venv"] or target["implementation"] != "cpython" or target["platform"] != "linux":
        parser.error("Use a Linux CPython virtualenv (the validated source-build platform)")
    if not (3, 12) <= tuple(target["version"]) < (3, 15):
        parser.error("The pinned build dependencies require Python 3.12–3.14; 3.12 is the tested ABI")
    if args.install:
        conflicts = output([target_python, "-c",
            "from importlib.metadata import packages_distributions; "
            "print(', '.join(n for n in packages_distributions().get('ladybug', []) "
            "if n.lower().replace('_','-') != 'graphmine-tento'))"])
        if conflicts:
            parser.error("Another distribution owns ladybug; use a fresh virtualenv")
    source = ROOT / "third_party/tento"
    lock = json.loads(LOCK_PATH.read_text())
    checked_source(source, lock)
    project = tomllib.loads((ROOT / "agent/pyproject.toml").read_text())
    if project["project"]["optional-dependencies"]["semantic"] != [f"{lock['distribution']}=={lock['version']}"]:
        parser.error("The semantic extra and engine lock disagree")
    build_dir = args.build_dir.resolve()
    if build_dir == source or source in build_dir.parents:
        parser.error("The packaging directory must be outside the Tentō submodule")
    build_dir.mkdir(parents=True, exist_ok=True)
    build_python = build_dir / "venv/bin/python"
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "OPENROUTER_API_KEY", "LLM_API_KEY", "GRAPHMINE_LLM_API_KEY"):
        env.pop(name, None)
    env["UV_CACHE_DIR"] = str(build_dir / "uv-cache")
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    env["GEN"] = "Ninja"
    env["BUILD_CLEAN"] = "0"
    log_path = build_dir / "build.log"
    print(f"Building Tentō {lock['commit']}; log: {log_path}", flush=True)
    with log_path.open("w") as log:
        def run(command):
            subprocess.run([str(x) for x in command], env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
        # A build-only environment keeps compiler dependencies out of the target.
        if not build_python.exists():
            run(["uv", "venv", "--python", target_python, build_python.parent.parent])
        elif output([str(build_python), "-c", "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"]) != target["suffix"]:
            raise ValueError("Use a separate --build-dir for each Python ABI")
        run(["uv", "pip", "install", "--python", build_python, *BUILD_REQUIREMENTS])
        run(["make", "-C", source / "ladybug/tools/python_api", "-o", "requirements", "build-pybind-subdir",
             f"LBUG_SOURCE_DIR={source / 'ladybug'}", f"PYTHON_BIN={build_python}"])
        native = source / "ladybug/tools/python_api/build/ladybug" / ("_lbug" + target["suffix"])
        if not native.is_file():
            raise ValueError("The source build did not produce the requested Python ABI")
        wheels = build_dir / "wheels"
        wheels.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="package-", dir=build_dir) as temporary:
            stage = Path(temporary)
            manifest = stage_package(stage, source, native, lock)
            run(["uv", "build", "--wheel", "--offline", "--no-build-isolation", "--python", build_python,
                 "--out-dir", wheels, stage])
        tag = "cp" + "".join(str(n) for n in target["version"])
        wheel, = wheels.glob(f"graphmine_tento-{lock['version']}-{tag}-{tag}-*.whl")
        if args.install:
            run(["uv", "pip", "install", "--python", target_python,
                 "--reinstall-package", lock["distribution"], wheel])
    checked_source(source, lock)
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "source": manifest,
        "target": target, "build_requirements": BUILD_REQUIREMENTS, "jobs": args.jobs,
        "wheel": str(wheel), "wheel_sha256": digest(wheel), "installed": args.install,
        "log": str(log_path), "live_blockers": lock["live_blockers"],
    }
    (build_dir / "build-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"Tentō build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, subprocess.CalledProcessError) as error:
        # Native build output stays in build.log; never echo an inherited credential.
        print(f"Tentō build failed ({type(error).__name__}). Check prerequisites, the pinned source, and build.log.", file=sys.stderr)
        raise SystemExit(1)
