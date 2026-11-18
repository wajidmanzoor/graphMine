#!/usr/bin/env python3
"""Run reproducible backend benchmarks; default warm start is at most 3 rows/operation."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "python/graphmine")]

from graphmine_agent.backend_learning.benchmark import main

if __name__ == "__main__":
    raise SystemExit(main())
