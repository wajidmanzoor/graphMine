"""Local lifecycle tests never invoke a real service or database."""

from dataclasses import replace
import json
import subprocess
from types import SimpleNamespace

import pytest

from graphmine_agent.neo4j_local import LocalNeo4j


class Systemd:
    def __init__(self):
        self.units = {"graphmine-neo4j" + suffix + ".service": {"active": "active", "enabled": "enabled", "pid": str(i + 10)}
                      for i, suffix in enumerate(("", "-browser", "-transfers-demo", "-yelp"))}
        self.units["graphmine-neo4j-ontime.service"] = {"active": "inactive", "enabled": "disabled", "pid": "0"}
        self.calls = []
        self.fail_stop = None
        self.timeout_stop = None
        self.unit_directory = None

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "ps":
            return SimpleNamespace(returncode=0, stdout="4096\n", stderr="")
        assert args[:2] == ["systemctl", "--user"]
        action = args[2]
        if action == "list-unit-files":
            output = json.dumps([{"unit_file": name} for name in self.units])
        elif action == "show":
            unit = self.units[args[3]]
            output = f"ActiveState={unit['active']}\nUnitFileState={unit['enabled']}\nMainPID={unit['pid']}\nControlGroup=\n"
        else:
            name = args[-1]
            unit = self.units[name]
            if action == "stop" and name == self.timeout_stop:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            if action == "stop" and name == self.fail_stop:
                return SimpleNamespace(returncode=1, stdout="", stderr="failure")
            if action == "stop":
                unit.update(active="inactive", pid="0")
            elif action == "disable":
                unit["enabled"] = "disabled"
                if self.unit_directory is not None:
                    path = self.unit_directory / name
                    if path.is_symlink():
                        path.unlink()
                        del self.units[name]
            elif action == "enable":
                assert args[3] == "--now"
                unit.update(active="active", enabled="enabled", pid="99")
            else:
                pytest.fail("Unexpected systemctl command")
            output = ""
        return SimpleNamespace(returncode=0, stdout=output, stderr="")


@pytest.fixture
def control(settings, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"version": 1, "datasets": [{"id": "yelp", "bolt_uri": "bolt://127.0.0.1:17701"}]}))
    settings = replace(settings, neo4j_datasets_registry=registry, database_sources_file=None)
    systemd = Systemd()
    directory = tmp_path / "unit-files"
    directory.mkdir()
    systemd.unit_directory = directory
    return LocalNeo4j(settings, runner=systemd, probe=lambda _: True, unit_directory=directory), systemd


def test_status_is_read_only_and_includes_unsuffixed_service(control):
    manager, systemd = control
    report = manager.status()
    assert report["rss_bytes"] == 4 * 4096 * 1024
    assert any(item["unit"] == "graphmine-neo4j.service" for item in report["units"])
    assert not manager.state.exists()
    assert all(call[0] == "ps" or call[2] in {"list-unit-files", "show"} for call in systemd.calls)


def test_park_stops_then_disables_every_unit_and_reports_ps_rss(control, tmp_path):
    manager, systemd = control
    marker = tmp_path / "database-data"
    marker.write_text("preserve")
    report = manager.park()
    assert report["rss_freed_bytes"] == report["rss_before_bytes"] == 4 * 4096 * 1024
    assert report["rss_after_bytes"] == 0
    operations = [call for call in systemd.calls if call[0] == "systemctl" and call[2] in {"stop", "disable"}]
    assert operations == [command for name in sorted(systemd.units)
                          for command in (["systemctl", "--user", "stop", name], ["systemctl", "--user", "disable", name])]
    assert all(item["active"] == "inactive" and item["enabled"] == "disabled" for item in report["units"])
    assert marker.read_text() == "preserve"
    assert "graphmine-neo4j-ontime.service" not in json.loads(manager.state.read_text())["activate_units"]


def test_park_is_idempotent_and_activate_restores_services_and_waits_for_bolt(control):
    manager, systemd = control
    manager.park()
    retained = manager.state.read_text()
    assert manager.park()["rss_freed_bytes"] == 0
    assert manager.state.read_text() == retained
    addresses = []
    manager.probe = lambda address: addresses.append(address) or True
    result = manager.activate()
    assert set(addresses) == {("127.0.0.1", 17687), ("127.0.0.1", 17700), ("127.0.0.1", 17701)}
    assert systemd.units["graphmine-neo4j-ontime.service"]["active"] == "inactive"
    assert all(item["active"] == "active" and item["enabled"] == "enabled" for item in result["units"] if "ontime" not in item["unit"])


def test_park_preserves_linked_unit_definition_for_later_activation(control, tmp_path):
    manager, systemd = control
    unit = "graphmine-neo4j-browser.service"
    source = tmp_path / unit
    source.write_text("[Service]\nExecStart=/retained/browser\n")
    installed = manager.unit_directory / unit
    installed.symlink_to(source)
    manager.park()
    assert installed.is_file() and not installed.is_symlink()
    assert installed.read_bytes() == source.read_bytes()
    assert systemd.units[unit]["enabled"] == "disabled"
    manager.activate()
    assert systemd.units[unit]["enabled"] == "enabled"
    assert systemd.units[unit]["active"] == "active"


def test_failed_stop_does_not_claim_zero_ram_and_still_disables_units(control):
    manager, systemd = control
    systemd.fail_stop = "graphmine-neo4j.service"
    with pytest.raises(RuntimeError, match="could not be parked"):
        manager.park()
    assert systemd.units[systemd.fail_stop]["active"] == "active"
    assert all(item["enabled"] == "disabled" for item in systemd.units.values())


def test_activation_timeout_restores_previous_service_states(control):
    manager, systemd = control
    manager.park()
    before = {name: dict(item) for name, item in systemd.units.items()}
    now = [0]
    manager.clock = lambda: now[0]
    manager.sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
    manager.probe = lambda _: False
    with pytest.raises(RuntimeError, match="120 seconds"):
        manager.activate()
    assert now[0] == 120 and systemd.units == before


def test_timed_out_stop_still_disables_every_unit_and_reports_failure(control):
    manager, systemd = control
    systemd.timeout_stop = "graphmine-neo4j.service"
    with pytest.raises(RuntimeError, match="could not be parked"):
        manager.park()
    assert systemd.units[systemd.timeout_stop]["active"] == "active"
    assert all(item["enabled"] == "disabled" for item in systemd.units.values())


def test_unknown_retained_unit_is_not_started_without_a_bolt_endpoint(control):
    manager, systemd = control
    systemd.units["graphmine-neo4j-unknown.service"] = {"active": "active", "enabled": "enabled", "pid": "1"}
    manager.park()
    systemd.calls.clear()
    with pytest.raises(ValueError, match="No registered Bolt endpoint"):
        manager.activate()
    assert not any(call[:4] == ["systemctl", "--user", "enable", "--now"] for call in systemd.calls)
