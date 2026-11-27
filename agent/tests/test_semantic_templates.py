"""The browser's generated templates must execute on the pinned native engine."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from graphmine_agent.semantic_loader import schema
from graphmine_agent.semantic_worker import run_worker
from test_semantic_native import native_engine, rich_graph  # noqa: F401


@pytest.mark.parametrize("template", ["plain", "extract", "filter", "score", "aggregate", "subgraph", "sg_agg", "path", "path_filter", "previous", "state"])
def test_browser_template_runs_with_actual_schema(template, rich_graph, native_engine, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to evaluate the browser template factory")
    script = Path(__file__).resolve().parents[1] / "graphmine_agent/static/analytics-semantic-details.js"
    output = subprocess.run([node, "-e", "global.window = {}; require(process.argv[1]); let s=''; process.stdin.on('data', b => s+=b); process.stdin.on('end', () => process.stdout.write(JSON.stringify(window.GraphMineSemanticTemplates(JSON.parse(s)))));", str(script)], input=json.dumps(schema(rich_graph)), text=True, capture_output=True, check=True)
    query = next(t[2] for t in json.loads(output.stdout) if t[0] == template)
    result = run_worker(rich_graph, {"statement": query, "model": "mock", "projection": "elements", "call_limit": 100}, temporary_root=tmp_path)
    assert result["effective_settings"]["http_requests"] == 0
    assert bool(result["steps"]) == (template != "plain")
