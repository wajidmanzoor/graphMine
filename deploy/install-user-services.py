#!/usr/bin/env python3
"""Install and enable GraphMine user services without starting or stopping them."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


def quoted(value):
    value = str(value)
    if any(char in value for char in "\n\r\0"):
        raise ValueError("Service paths must not contain line breaks or NUL")
    return (
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    )


def unit(repository, environment, component):
    dependency = (
        "After=graphmine-vllm.service\nWants=graphmine-vllm.service\n"
        if component == "agent"
        else ""
    )
    return f"""[Unit]
Description=GraphMine {component} (user installation)
{dependency}StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
WorkingDirectory={str(repository).replace("%", "%%")}
Environment={quoted("GRAPHMINE_ENV_FILE=" + str(environment))}
ExecStart=:{quoted(repository / "deploy" / ("start-" + component + ".sh"))}
Restart=on-failure
RestartSec=5
TimeoutStopSec={420 if component == "agent" else 180}
KillMode=control-group
UMask=0077
NoNewPrivileges=true
LimitNOFILE=65536

[Install]
WantedBy=default.target
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--vllm-env-file",
        type=Path,
        help="Separate model environment, for example for CUDA compatibility libraries",
    )
    parser.add_argument(
        "--replace", action="store_true", help="Replace existing GraphMine units"
    )
    args = parser.parse_args()
    repository, environment = (
        args.repository.absolute(),
        args.env_file.resolve(strict=True),
    )
    model_environment = (args.vllm_env_file or args.env_file).resolve(strict=True)
    for path in (environment, model_environment):
        info = path.stat()
        if not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            parser.error(
                "Environment files must be private regular files owned by this user (chmod 600)"
            )
    units = {
        f"graphmine-{name}.service": unit(
            repository, model_environment if name == "vllm" else environment, name
        )
        for name in ("vllm", "agent")
    }
    destination = (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "systemd/user"
    )
    for name in units:
        if (destination / name).exists() and not args.replace:
            parser.error(
                f"{destination / name} already exists; use --replace after reviewing it"
            )
    with tempfile.TemporaryDirectory(prefix="graphmine-units-") as temporary:
        staged = []
        for name, content in units.items():
            path = Path(temporary) / name
            path.write_text(content)
            staged.append(path)
        subprocess.run(
            ["systemd-analyze", "--user", "verify", *map(str, staged)], check=True
        )
        destination.mkdir(parents=True, exist_ok=True)
        for path in staged:
            # Replace each unit atomically, keeping the file private.
            with tempfile.NamedTemporaryFile(
                dir=destination, mode="w", delete=False
            ) as handle:
                handle.write(path.read_text())
            Path(handle.name).replace(destination / path.name)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", *units], check=True)
    print(
        "Installed and enabled GraphMine services. No processes were started or stopped."
    )
    print(
        "After stopping older processes: systemctl --user start graphmine-agent.service"
    )
    print("For startup without login: loginctl enable-linger " + str(os.getuid()))


if __name__ == "__main__":
    main()
