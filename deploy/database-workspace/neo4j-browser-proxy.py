"""Launcher for the retained local Browser service and its backend resolver."""

from pathlib import Path
import runpy
import sys

# Both the tracked deploy directory and the host's private deployment directory
# sit two levels below the checkout root.
repository = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repository / "agent"))

if __name__ == "__main__":
    runpy.run_module("graphmine_agent.neo4j_browser", run_name="__main__")
