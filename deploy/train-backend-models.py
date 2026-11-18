#!/usr/bin/env python3
"""Fit from a deployed environment's existing run history, without GPU work."""

import argparse
import os
from pathlib import Path

from environments import environment, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--environment", choices=("production", "testing", "devlopment"), default="production")
    args = parser.parse_args()
    role = load_config(args.config)["environments"][args.environment]
    env = environment(role)
    env["CUDA_VISIBLE_DEVICES"] = ""
    os.chdir(role["code"])
    os.execve(role["python"], [role["python"], "-m", "graphmine_agent.backend_learning.model_cli", "train"], env)


if __name__ == "__main__":
    main()
