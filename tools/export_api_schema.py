#!/usr/bin/env python3
"""Export the API's schema without starting services, jobs or source connections."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "python/graphmine")]

from graphmine_agent.api import create_app  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True))
