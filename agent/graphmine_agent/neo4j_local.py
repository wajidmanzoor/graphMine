"""Explicit user-systemd controls for retained local Neo4j stores. No sudo."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tempfile
import time

from .neo4j_backend import atomic_json, get_active_neo4j, local_control_endpoints

UNIT = re.compile(r"graphmine-neo4j(?:-[^\s/]+)?\.service\Z")
STOPPED = {"inactive", "failed"}


def bolt_answers(address):
    try:
        with socket.create_connection(address, timeout=1):
            return True
    except OSError:
        return False


class LocalNeo4j:
    def __init__(self, settings, *, runner=None, probe=None, clock=None, sleep=None, unit_directory=None):
        self.settings = settings
        self.runner = runner or subprocess.run
        self.probe = probe or bolt_answers
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.state = Path(settings.data_root) / "neo4j_local_units.json"
        self.unit_directory = Path(unit_directory) if unit_directory is not None else (
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user")

    def _retain_linked_units(self, units):
        # systemctl disable removes a linked unit's registration as well as its
        # boot links. Keep the same definition installed as a regular file;
        # its original external source stays untouched and activation can find it.
        for unit in units:
            path = self.unit_directory / unit
            if not path.is_symlink():
                continue
            source = path.resolve(strict=True)
            info = source.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise ValueError("Invalid retained local Neo4j unit definition")
            content = source.read_bytes()
            fd, temporary = tempfile.mkstemp(prefix="." + unit + "-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def _systemctl(self, *arguments, check=True):
        # Allow a database time to flush its store during an orderly stop.
        timeout = 330 if arguments[0] == "stop" else 120 if arguments[0] == "enable" else 30
        try:
            result = self.runner(["systemctl", "--user", *arguments], text=True, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Local Neo4j service command failed: " + " ".join(arguments[:2])) from None
        if check and result.returncode:
            # Do not expose driver/systemd error text or a process environment.
            raise RuntimeError("Local Neo4j service command failed: " + " ".join(arguments[:2]))
        return result

    @contextmanager
    def _lock(self):
        self.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.state.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def _units(self):
        rows = json.loads(self._systemctl("list-unit-files", "--no-pager", "--output=json", "graphmine-neo4j*.service").stdout)
        units = sorted(row["unit_file"] for row in rows if UNIT.fullmatch(row["unit_file"]))
        return units

    def _rss(self, group, pid):
        pids = {int(pid)} if pid and int(pid) else set()
        if group and group.startswith("/") and ".." not in Path(group).parts:
            for path in Path("/sys/fs/cgroup" + group).rglob("cgroup.procs"):
                try:
                    pids.update(int(value) for value in path.read_text().split())
                except (OSError, ValueError):
                    continue
        if not pids:
            return 0
        result = self.runner(["ps", "-o", "rss=", "-p", ",".join(map(str, sorted(pids)))],
                             text=True, capture_output=True, timeout=5)
        if result.returncode not in (0, 1):
            raise RuntimeError("Could not measure local Neo4j process RSS")
        return sum(int(value) for value in result.stdout.split()) * 1024

    def status(self):
        units = []
        for unit in self._units():
            raw = self._systemctl("show", unit, "--property=ActiveState,UnitFileState,MainPID,ControlGroup").stdout
            fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            units.append({"unit": unit, "active": fields.get("ActiveState", "unknown"),
                          "enabled": fields.get("UnitFileState", "unknown"),
                          "rss_bytes": self._rss(fields.get("ControlGroup"), fields.get("MainPID"))})
        return {"units": units, "rss_bytes": sum(unit["rss_bytes"] for unit in units)}

    def _activation_units(self, status):
        installed = {item["unit"] for item in status["units"]}
        if self.state.exists():
            fd = os.open(self.state, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size > 16384
                        or info.st_uid != os.getuid() or info.st_mode & 0o077):
                    raise ValueError("Invalid local Neo4j activation state")
                saved = json.load(stream)
            if not isinstance(saved, dict):
                raise ValueError("Invalid local Neo4j activation state")
            wanted = saved.get("activate_units")
            if saved.get("version") != 1 or not isinstance(wanted, list) or any(
                    not isinstance(unit, str) or not UNIT.fullmatch(unit) for unit in wanted):
                raise ValueError("Invalid local Neo4j activation state")
            if set(wanted) - installed:
                raise ValueError("A retained local Neo4j unit is missing")
            return sorted(set(wanted))
        registered = {f"graphmine-neo4j-{endpoint.identifier}.service"
                      for endpoint in get_active_neo4j(self.settings, target="local").endpoints}
        registered.update({"graphmine-neo4j.service", "graphmine-neo4j-transfers-demo.service", "graphmine-neo4j-browser.service"})
        # Preserve disabled, incomplete stores such as OnTime. Only registered
        # databases, the retained demo/legacy units, or previously enabled units
        # become activation targets; parking still covers every discovered unit.
        registered.update(item["unit"] for item in status["units"]
                          if item["active"] not in STOPPED or item["enabled"].startswith("enabled"))
        return sorted(registered & installed)

    def park(self):
        with self._lock():
            before = self.status()
            wanted = self._activation_units(before)
            atomic_json(self.state, {"version": 1, "activate_units": wanted})
            self._retain_linked_units(item["unit"] for item in before["units"])
            failures = []
            for item in before["units"]:
                for action in ("stop", "disable"):
                    try:
                        result = self._systemctl(action, item["unit"], check=False)
                    except RuntimeError:
                        failures.append(item["unit"])
                    else:
                        if result.returncode:
                            failures.append(item["unit"])
            after = self.status()
            pending = [item["unit"] for item in after["units"]
                       if item["active"] not in STOPPED or item["enabled"].startswith("enabled") or item["rss_bytes"]]
            if failures or pending:
                raise RuntimeError("Some local Neo4j services could not be parked: " + ", ".join(sorted(set(failures + pending))))
            return {**after, "rss_before_bytes": before["rss_bytes"], "rss_after_bytes": after["rss_bytes"],
                    "rss_freed_bytes": before["rss_bytes"] - after["rss_bytes"]}

    def activate(self, timeout=120):
        with self._lock():
            before = self.status()
            wanted = self._activation_units(before)
            endpoints = local_control_endpoints(self.settings, wanted)
            try:
                for unit in wanted:
                    self._systemctl("enable", "--now", unit)
                deadline = self.clock() + timeout
                pending = dict(endpoints)
                while pending:
                    pending = {unit: endpoint for unit, endpoint in pending.items()
                               if not self.probe(endpoint.address)}
                    if not pending:
                        break
                    if self.clock() >= deadline:
                        raise RuntimeError("Local Neo4j did not accept Bolt connections within 120 seconds: " + ", ".join(sorted(pending)))
                    self.sleep(min(2, max(0, deadline - self.clock())))
                after = self.status()
                if any(item["unit"] in wanted and (item["active"] != "active" or not item["enabled"].startswith("enabled"))
                       for item in after["units"]):
                    raise RuntimeError("Local Neo4j activation did not complete")
                return after
            except Exception:
                # Undo only the service changes this activation introduced.
                for item in before["units"]:
                    if item["unit"] not in wanted:
                        continue
                    for action, needed in (("stop", item["active"] in STOPPED),
                                           ("disable", not item["enabled"].startswith("enabled"))):
                        if needed:
                            try:
                                self._systemctl(action, item["unit"], check=False)
                            except RuntimeError:
                                pass  # Continue rollback and preserve the activation error.
                raise


def cli_settings(repository):
    from .config import Settings
    settings = Settings.from_env(repository)
    # This host's environment controller is authoritative for manual operations.
    # Read only path fields; do not source an env file or load its credentials.
    config = repository.parent / "graphmine-data/environments/config/environments.json"
    if not os.environ.get("GRAPHMINE_AGENT_DATA_ROOT") and config.is_file():
        role = json.loads(config.read_text())["environments"]["production"]["env"]
        paths = {"data_root": "GRAPHMINE_AGENT_DATA_ROOT", "neo4j_datasets_registry": "GRAPHMINE_NEO4J_DATASETS_REGISTRY",
                 "neo4j_datasets_password_file": "GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE", "database_sources_file": "GRAPHMINE_DATABASE_SOURCES_FILE"}
        settings = replace(settings, **{name: Path(role[key]) for name, key in paths.items() if role.get(key)})
    elif settings.neo4j_datasets_registry is None:
        settings = replace(settings, neo4j_datasets_registry=repository / "deploy/neo4j-datasets/registry.json")
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "park", "activate"))
    args = parser.parse_args(argv)
    repository = Path(__file__).resolve().parents[2]
    manager = LocalNeo4j(cli_settings(repository))
    try:
        report = getattr(manager, args.command)()
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(report, indent=2))
    if args.command == "park":
        print(f"RSS freed: {report['rss_freed_bytes']} bytes (ps before: {report['rss_before_bytes']}; after: {report['rss_after_bytes']})")


if __name__ == "__main__":
    main()
