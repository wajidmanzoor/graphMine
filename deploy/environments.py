#!/usr/bin/env python3
"""Manage isolated app environments while sharing an already running vLLM server.

Host paths and credentials live in a private JSON configuration outside Git.
This controller never starts, stops, or changes the vLLM or database services.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request


ROLES = ("production", "devlopment", "testing")
ACTIVE = ("queued", "running", "planning", "executing")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def overlaps(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


def writable_paths(role):
    env = role["env"]
    root = Path(env["GRAPHMINE_AGENT_DATA_ROOT"])
    return [root, Path(env.get("GRAPHMINE_HISTORY_ROOT", root / "history")),
            Path(env.get("GRAPHMINE_CAPTURE_ROOT", root / "captures")),
            Path(env["GRAPHMINE_BACKUP_DIR"]), Path(role["studio_workspace"]),
            Path(role["studio_data_root"])]


def validate_config(config):
    if config.get("version") != 1 or set(config["environments"]) != set(ROLES):
        raise ValueError("Configure production, devlopment, and testing with version 1")
    roles = config["environments"]
    services, ports = [], []
    for name, role in roles.items():
        if role["branch"] != name:
            raise ValueError(f"{name}: branch must match its environment")
        for path in [role["code"], role["python"], *writable_paths(role)]:
            if not Path(path).is_absolute():
                raise ValueError(f"{name}: use absolute paths")
        services.extend(role["services"])
        ports.extend([int(role["env"]["GRAPHMINE_API_PORT"]), int(role["studio_port"])])
        if name != "production":
            if role["env"].get("GRAPHMINE_API_HOST") != "127.0.0.1" or role["studio_host"] != "127.0.0.1":
                raise ValueError("Development and testing must bind to loopback")
            for key in ("GRAPHMINE_DATABASE_SOURCES_FILE", "GRAPHMINE_CONNECTORS_FILE"):
                path, prod = role["env"].get(key), roles["production"]["env"].get(key)
                if path and prod and Path(path).resolve() == Path(prod).resolve():
                    raise ValueError(f"{name}: production connections must not be reused")
        if name == "devlopment" and (role["env"].get("GRAPHMINE_LLM_ENABLED") != "false"
                                     or role["env"].get("CUDA_VISIBLE_DEVICES") != "-1"):
            raise ValueError("Development defaults to CPU work with live LLM calls disabled")
    if len(set(services)) != len(services) or len(set(ports)) != len(ports):
        raise ValueError("Each environment needs distinct services and app ports")
    for i, first in enumerate(ROLES):
        for second in ROLES[i + 1:]:
            if overlaps(roles[first]["code"], roles[second]["code"]):
                raise ValueError("Code checkouts must be separate")
            if Path(roles[first]["python"]).parent.parent == Path(roles[second]["python"]).parent.parent:
                raise ValueError("Application virtual environments must be separate")
            for a in writable_paths(roles[first]):
                for b in writable_paths(roles[second]):
                    if overlaps(a, b):
                        raise ValueError(f"Writable data overlaps between {first} and {second}")


def load_config(path):
    config = json.loads(Path(path).read_text())
    validate_config(config)
    return config


def command(args, *, cwd=None, env=None, capture=True):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            text=True, capture_output=capture)
    if result.returncode:
        detail = (result.stderr or "").strip() if capture else "see command output"
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {detail}")
    return result.stdout.strip() if capture else ""


def git(role, *args):
    return command(["git", "-C", role["code"], *args])


def clean(role):
    if git(role, "branch", "--show-current") != role["branch"]:
        raise RuntimeError(f"Expected {role['branch']} in {role['code']}")
    if git(role, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError(f"Commit or remove pending source changes in {role['code']}")


def systemctl(action, services):
    return command(["systemctl", "--user", action, *services])


def active(service):
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", service])
    return result.returncode == 0


def environment(role):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GRAPHMINE_") and key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({key: str(value) for key, value in role["env"].items()})
    code = Path(role["code"])
    env.update(PYTHONPATH=os.pathsep.join((str(code / "agent"), str(code / "python/graphmine"))),
               PYTHONDONTWRITEBYTECODE="1", GRAPHMINE_REPO=str(code))
    return env


def launch(config, name, app):
    role = config["environments"][name]
    if name == "testing" and any(active(s) for s in config["environments"]["production"]["services"]):
        raise RuntimeError("Stop production through begin-testing before starting testing")
    if name == "production" and any(active(s) for s in config["environments"]["testing"]["services"]):
        raise RuntimeError("Testing is active; use promote or cancel-testing")
    code = Path(role["code"])
    if app == "agent":
        args = [role["python"], "-m", "graphmine_agent", "serve"]
    else:
        args = [role["python"], str(code / "dataset-studio/studio.py"), "--repo", str(code),
                "--workspace", role["studio_workspace"], "--data-root", role["studio_data_root"],
                "--graphmine-data", role["env"]["GRAPHMINE_AGENT_DATA_ROOT"],
                "--host", role["studio_host"], "--port", str(role["studio_port"])]
        if role["env"].get("GRAPHMINE_TLS_CERTFILE"):
            args.extend(["--tls-certfile", role["env"]["GRAPHMINE_TLS_CERTFILE"],
                         "--tls-keyfile", role["env"]["GRAPHMINE_TLS_KEYFILE"]])
    os.chdir(code)
    os.execve(role["python"], args, environment(role))


def pending(role):
    root = Path(role["env"]["GRAPHMINE_AGENT_DATA_ROOT"])
    count = 0
    for path in [root / "agent.sqlite3", root / "analytics/workflows.sqlite3"]:
        if not path.exists():
            continue
        with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("jobs", "database_jobs", "workflows"):
                if table in tables and "status" in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
                    count += db.execute(f"SELECT count(*) FROM {table} WHERE status IN (?,?,?,?)", ACTIVE).fetchone()[0]
            if "account_leases" in tables:
                count += db.execute("SELECT count(*) FROM account_leases WHERE expires_at>?", (time.time(),)).fetchone()[0]
    return count


def wait_idle(role, seconds=120):
    deadline = time.monotonic() + seconds
    while pending(role):
        if time.monotonic() >= deadline:
            raise RuntimeError("Work is still active; leave the environment running and retry after it finishes")
        time.sleep(1)


def health(role, seconds=30):
    scheme = "https" if role["env"].get("GRAPHMINE_TLS_CERTFILE") else "http"
    urls = [f"{scheme}://127.0.0.1:{role['env']['GRAPHMINE_API_PORT']}/",
            f"{scheme}://127.0.0.1:{role['studio_port']}/"]
    deadline = time.monotonic() + seconds
    while True:
        try:
            for url in urls:
                with urllib.request.urlopen(url, timeout=3, context=ssl._create_unverified_context()) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{role['branch']} did not pass its local HTTP checks") from None
            time.sleep(1)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def snapshot(role):
    target = Path(role["env"]["GRAPHMINE_BACKUP_DIR"]) / ("before-deploy-" + stamp())
    target.mkdir(parents=True, mode=0o700)
    script = ("from pathlib import Path; from graphmine_agent.backup import online_snapshot, verify_snapshot; "
              "import sys; online_snapshot(Path(sys.argv[1]),Path(sys.argv[2])); verify_snapshot(Path(sys.argv[2]))")
    command([role["python"], "-c", script, role["env"]["GRAPHMINE_AGENT_DATA_ROOT"], target / "graphmine"],
            env=environment(role))
    shutil.copytree(role["studio_workspace"], target / "studio-workspace", symlinks=True)
    shutil.copytree(role["studio_data_root"], target / "studio-datasets", symlinks=True)
    return str(target)


def begin_testing(config, candidate):
    roles = config["environments"]
    prod, test, dev = roles["production"], roles["testing"], roles["devlopment"]
    state_path = Path(config["state_directory"]) / "testing-session.json"
    if state_path.exists():
        raise RuntimeError("A testing session already exists; promote or cancel it first")
    for role in (prod, test, dev):
        clean(role)
    if candidate.startswith("-"):
        raise ValueError("Expected a commit or branch name")
    commit = git(dev, "rev-parse", "--verify", candidate + "^{commit}")
    git(test, "merge-base", "--is-ancestor", "HEAD", commit)
    git(prod, "merge-base", "--is-ancestor", "HEAD", commit)
    git(test, "merge", "--ff-only", commit)
    wait_idle(prod)
    state = {"commit": commit, "previous_production": git(prod, "rev-parse", "HEAD"), "started_at": stamp()}
    write_json(state_path, state)
    systemctl("stop", dev["services"])
    systemctl("stop", prod["services"])
    try:
        systemctl("start", test["services"])
        health(test)
    except Exception:
        systemctl("stop", test["services"])
        systemctl("start", prod["services"])
        health(prod)
        state_path.unlink()
        raise
    print(f"Testing {commit}; production apps are stopped. vLLM and databases remain running.")


def verify_testing(config):
    role = config["environments"]["testing"]
    path = Path(config["state_directory"]) / "testing-session.json"
    state = json.loads(path.read_text())
    clean(role)
    if git(role, "rev-parse", "HEAD") != state["commit"]:
        raise RuntimeError("Testing code changed after the session started")
    state.pop("verified_at", None)
    write_json(path, state)
    health(role)
    env = {k: v for k, v in environment(role).items() if not k.startswith("GRAPHMINE_")}
    for key in ("GRAPHMINE_RUNTIME_REPOSITORY", "GRAPHMINE_BINARY", "GRAPHMINE_NATIVE_BINARY",
                "GRAPHMINE_NATIVE_LIBRARY", "GRAPHMINE_ANALYTICS_PYTHON",
                "GRAPHMINE_WORKER_DIR"):
        if key in role["env"]:
            env[key] = role["env"][key]
    env["GRAPHMINE_REPO"] = role["code"]
    # Backend run/model stores reject /tmp; keep isolated validation data under
    # the controller's private state directory and remove it after the checks.
    with tempfile.TemporaryDirectory(prefix="graphmine-release-check-", dir=config["state_directory"]) as scratch:
        env["GRAPHMINE_AGENT_DATA_ROOT"] = scratch
        for args in config["validation_commands"]:
            expanded = [item.replace("{python}", role["python"]).replace("{code}", role["code"]) for item in args]
            command(expanded, cwd=role["code"], env=env, capture=False)
    clean(role)
    if git(role, "rev-parse", "HEAD") != state["commit"]:
        raise RuntimeError("Testing code changed during validation")
    state["verified_at"] = stamp()
    write_json(path, state)
    print("Configured checks passed for " + state["commit"])


def promote(config, push=False):
    prod, test = (config["environments"][n] for n in ("production", "testing"))
    path = Path(config["state_directory"]) / "testing-session.json"
    state = json.loads(path.read_text())
    for role in (prod, test):
        clean(role)
    if not state.get("verified_at") or git(test, "rev-parse", "HEAD") != state["commit"]:
        raise RuntimeError("Run verify-testing on the exact candidate before promotion")
    if git(prod, "rev-parse", "HEAD") != state["previous_production"]:
        raise RuntimeError("Production changed during testing")
    if any(active(s) for s in prod["services"]):
        raise RuntimeError("Production must stay stopped during the testing session")
    wait_idle(test)
    state["backup"] = snapshot(prod)
    write_json(path, state)
    systemctl("stop", test["services"])
    git(prod, "merge", "--ff-only", state["commit"])
    try:
        systemctl("start", prod["services"])
        health(prod)
    except Exception:
        raise RuntimeError("Production health failed. The testing-session record retains the previous commit and backup. "
                           "Review schema compatibility before restoring code or data.") from None
    worktrees = git(prod, "worktree", "list", "--porcelain")
    if "branch refs/heads/main\n" in worktrees + "\n":
        raise RuntimeError("Production is running; update main in its checked-out worktree before pushing")
    old_main = git(prod, "rev-parse", "main")
    git(prod, "merge-base", "--is-ancestor", old_main, state["commit"])
    git(prod, "update-ref", "refs/heads/main", state["commit"], old_main)
    state["promoted_at"] = stamp()
    write_json(Path(config["state_directory"]) / "last-promotion.json", state)
    path.unlink()
    if push:
        git(prod, "push", "--atomic", "origin", "main", "production", "testing", "devlopment")
    print("Production is running " + state["commit"])


def cancel_testing(config):
    prod, test = (config["environments"][n] for n in ("production", "testing"))
    path = Path(config["state_directory"]) / "testing-session.json"
    state = json.loads(path.read_text())
    if git(prod, "rev-parse", "HEAD") != state["previous_production"]:
        raise RuntimeError("Production code already changed; review the deployment record before rollback")
    wait_idle(test)
    systemctl("stop", test["services"])
    systemctl("start", prod["services"])
    health(prod)
    path.unlink()
    print("Testing stopped; the previous production release is running")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    run = commands.add_parser("run")
    run.add_argument("environment", choices=ROLES)
    run.add_argument("app", choices=("agent", "studio"))
    commands.add_parser("start-dev")
    commands.add_parser("stop-dev")
    begin = commands.add_parser("begin-testing")
    begin.add_argument("--commit", default="devlopment")
    commands.add_parser("verify-testing")
    promotion = commands.add_parser("promote")
    promotion.add_argument("--push", action="store_true")
    commands.add_parser("cancel-testing")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "run":
        launch(config, args.environment, args.app)
        return 0
    state_dir = Path(config["state_directory"])
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "status":
            for name, role in config["environments"].items():
                print(name, git(role, "rev-parse", "--short", "HEAD"),
                      {s: active(s) for s in role["services"]})
        elif args.command in ("start-dev", "stop-dev"):
            role = config["environments"]["devlopment"]
            systemctl("start" if args.command == "start-dev" else "stop", role["services"])
            if args.command == "start-dev":
                health(role)
        elif args.command == "begin-testing":
            begin_testing(config, args.commit)
        elif args.command == "verify-testing":
            verify_testing(config)
        elif args.command == "promote":
            promote(config, args.push)
        else:
            cancel_testing(config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Environment problem failed: {error}", file=sys.stderr)
        raise SystemExit(1)
