#!/usr/bin/env python3
"""Install a CPU-only nightly model fit for one deployed environment."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path


def units(repository, environment, *, config=False, role="production"):
    spec = importlib.util.spec_from_file_location("service_install", Path(__file__).with_name("install-user-services.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    quote = module.quoted
    if config:
        command = f'{quote(repository / ".venv/bin/python")} {quote(repository / "deploy/train-backend-models.py")} --config {quote(environment)} --environment {role}'
        settings = ""
    else:
        command = f'/bin/bash {quote(repository / "deploy/train-backend-models.sh")}'
        settings = f'Environment={quote("GRAPHMINE_ENV_FILE=" + str(environment))}\n'
    service = f"""[Unit]
Description=GraphMine nightly backend models from observed runs

[Service]
Type=oneshot
WorkingDirectory={str(repository).replace('%', '%%')}
{settings}ExecStart=:{command}
TimeoutStartSec=1800
KillMode=control-group
Nice=10
UMask=0077
NoNewPrivileges=true
"""
    timer = """[Unit]
Description=Fit GraphMine backend models nightly

[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=15m
Persistent=true
Unit=graphmine-backend-model.service

[Install]
WantedBy=timers.target
"""
    return {"graphmine-backend-model.service": service, "graphmine-backend-model.timer": timer}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env-file", type=Path)
    source.add_argument("--config", type=Path, help="Private deployment environment JSON")
    parser.add_argument("--environment", choices=("production", "testing", "devlopment"), default="production")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--check", action="store_true", help="Verify generated units without installing")
    args = parser.parse_args()
    repository, environment = args.repository.absolute(), (args.config or args.env_file).resolve(strict=True)
    info = environment.stat()
    if not environment.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        parser.error("Environment must be a private file owned by this user (chmod 600)")
    destination = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    contents = units(repository, environment, config=bool(args.config), role=args.environment)
    if not args.check and not args.replace and any((destination / name).exists() for name in contents):
        parser.error("Backend model units already exist; use --replace after reviewing them")
    # Unit files contain paths only. Run logs and model data remain under /data.
    with tempfile.TemporaryDirectory(prefix="graphmine-model-units-") as temporary:
        staged = []
        for name, content in contents.items():
            path = Path(temporary) / name
            path.write_text(content)
            staged.append(path)
        subprocess.run(["systemd-analyze", "--user", "verify", *map(str, staged)], check=True)
        if args.check:
            print("Nightly backend model service and timer verified; nothing installed")
            return
        destination.mkdir(parents=True, exist_ok=True)
        for path in staged:
            with tempfile.NamedTemporaryFile(dir=destination, mode="w", delete=False) as handle:
                handle.write(path.read_text())
            Path(handle.name).replace(destination / path.name)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "graphmine-backend-model.timer"], check=True)
    print("Nightly backend fitting enabled; it uses existing runs and generates no training examples")


if __name__ == "__main__":
    main()
