#!/usr/bin/env python3
"""Decide whether level-1 sleep can safely keep the model weights in RAM."""
import os
from pathlib import Path
import sys


def weight_bytes(env):
    override = env.get("GRAPHMINE_LLM_WEIGHT_BYTES", "").strip()
    if override:
        value = int(override)
        if value <= 0:
            raise ValueError("GRAPHMINE_LLM_WEIGHT_BYTES must be a positive integer")
        return value
    model = env.get("GRAPHMINE_LLM_MODEL", "Qwen/Qwen3.8-27B-FP8")
    directory = Path(model).expanduser()
    if not directory.is_dir():
        home = Path(env.get("HF_HOME") or (Path(env.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "huggingface"))
        hub = Path(env.get("HF_HUB_CACHE") or env.get("HUGGINGFACE_HUB_CACHE") or home / "hub")
        cached = hub / ("models--" + model.replace("/", "--"))
        revision = env.get("GRAPHMINE_LLM_REVISION", "").strip()
        if not revision:
            reference = cached / "refs/main"
            if reference.is_file():
                revision = reference.read_text().strip()
            else:
                snapshots = list((cached / "snapshots").glob("*"))
                if len(snapshots) == 1:
                    revision = snapshots[0].name
        if not revision:
            raise OSError("the active model snapshot could not be identified")
        directory = cached / "snapshots" / revision
    files = list(directory.rglob("*.safetensors"))
    if not files:
        raise OSError("no model safetensors were found; set GRAPHMINE_LLM_WEIGHT_BYTES if necessary")
    return sum(path.stat().st_size for path in files)


def available_bytes(path=Path("/proc/meminfo")):
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == "MemAvailable:":
            if len(fields) != 3 or fields[2] != "kB":
                break
            return int(fields[1]) * 1024
    raise OSError("MemAvailable is missing from /proc/meminfo")


def sleep_is_safe(env, *, meminfo=Path("/proc/meminfo")):
    try:
        weights = weight_bytes(env)
        available = available_bytes(meminfo)
    except OSError as error:
        print(f"Warning: vLLM sleep mode disabled: {error}.", file=sys.stderr)
        return False
    if available * 4 < weights * 5:
        print(f"Warning: vLLM sleep mode disabled: MemAvailable={available} bytes; "
              f"level 1 needs at least {(weights * 5 + 3) // 4} bytes (1.25 times model weights).", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    try:
        print("1" if sleep_is_safe(os.environ) else "0")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
