#!/usr/bin/env python3
"""Read only validated launcher overrides; output never contains executable shell."""
import json
import os
from pathlib import Path
import sqlite3


def main():
    root = Path(__file__).resolve().parents[1]
    path = Path(os.getenv("GRAPHMINE_AGENT_DATA_ROOT", str(root / ".graphmine-agent"))) / "agent.sqlite3"
    if not path.is_file():
        return
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='settings_overrides'").fetchone():
            return
        for key, raw in db.execute("SELECT key,value FROM settings_overrides WHERE key IN ('GRAPHMINE_LLM_SLEEP_MODE','GRAPHMINE_LLM_MAX_NUM_SEQS')"):
            value = json.loads(raw)
            if key == "GRAPHMINE_LLM_SLEEP_MODE" and type(value) is bool:
                print(key + "=" + str(int(value)))
            elif key == "GRAPHMINE_LLM_MAX_NUM_SEQS" and type(value) is int and 1 <= value <= 32:
                print(key + "=" + str(value))
            else:
                raise ValueError("Invalid stored model setting: " + key)


if __name__ == "__main__":
    main()
