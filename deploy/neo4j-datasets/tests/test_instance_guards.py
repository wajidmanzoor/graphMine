"""Protect existing stores and keep generated passwords out of public metadata."""

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import common
import create_instance


def test_existing_store_is_rejected_before_any_password_or_service_change(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "INSTANCE_ROOT", tmp_path)
    monkeypatch.setattr(common, "verify_inputs", lambda slug: {})
    marker = tmp_path / "yelp/data/databases/neo4j/user-data"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"preserve me")
    monkeypatch.setattr(common, "password", lambda *args, **kwargs: pytest.fail("must not change credentials"))
    with pytest.raises(ValueError, match="already has data"):
        create_instance.create("yelp")
    assert marker.read_bytes() == b"preserve me"


def test_existing_configuration_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "INSTANCE_ROOT", tmp_path)
    monkeypatch.setattr(common, "verify_inputs", lambda slug: {})
    path = tmp_path / "yelp/conf/neo4j.conf"
    path.parent.mkdir(parents=True)
    path.write_text("original settings")
    with pytest.raises(ValueError, match="configuration already exists"):
        create_instance.create("yelp")
    assert path.read_text() == "original settings"


def test_password_is_created_once_only_in_the_private_env_file(tmp_path, monkeypatch):
    path = tmp_path / "demo.env"
    path.write_text("EXISTING_KEY=unchanged\n")
    path.chmod(0o600)
    monkeypatch.setattr(common, "PASSWORD_FILE", path)
    value = common.password("yelp", create=True)
    before = path.read_bytes()
    assert common.password("yelp", create=True) == value
    assert common.password("yelp") == value
    assert path.read_bytes() == before
    values = common.read_env(path.read_text())
    assert values == {"EXISTING_KEY": "unchanged", "GRAPHMINE_NEO4J_YELP_PASSWORD": value}
    assert list(tmp_path.iterdir()) == [path]
    assert value not in str(common.definition("yelp"))


def test_password_file_must_be_private(tmp_path, monkeypatch):
    path = tmp_path / "demo.env"
    path.write_text("GRAPHMINE_NEO4J_YELP_PASSWORD=private-value\n")
    path.chmod(0o644)
    monkeypatch.setattr(common, "PASSWORD_FILE", path)
    with pytest.raises(ValueError, match="mode-600") as error:
        common.password("yelp")
    assert "private-value" not in str(error.value)


def test_password_file_cannot_redirect_writes_through_a_symlink(tmp_path, monkeypatch):
    original, alias = tmp_path / "original", tmp_path / "demo.env"
    original.write_text("existing")
    original.chmod(0o600)
    alias.symlink_to(original)
    monkeypatch.setattr(common, "PASSWORD_FILE", alias)
    with pytest.raises(OSError):
        common.password("yelp", create=True)
    assert original.read_text() == "existing"


def test_private_env_values_are_parsed_without_shell_execution():
    values = common.read_env("export KEY='literal $(command) # value'\nEMPTY=\n")
    assert values == {"KEY": "literal $(command) # value", "EMPTY": ""}
    with pytest.raises(ValueError, match="Duplicate"):
        common.read_env("KEY=one\nKEY=two\n")
