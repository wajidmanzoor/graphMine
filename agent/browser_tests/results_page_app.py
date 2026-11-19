"""Isolated real API serving the immutable saved Yelp acceptance fixtures.

Run with GRAPHMINE_RESULTS_TEST_ROOT pointing at a disposable directory.
Only the saved native results are replayed; views, selections, persistence,
downloads and the browser use the actual application implementation.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from graphmine_agent.models import FileRole, SessionRecord
from graphmine_agent.analytics import WorkflowRequest

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ["GRAPHMINE_RESULTS_TEST_ROOT"]).resolve()
CASES = {
    "bicliques": ("06-maximal-bicliques.json", "Find maximal bicliques between Yelp users and businesses."),
    "communities": ("02-community-detection.json", "Which communities are present in the Yelp graph?"),
    "density": ("01-densest-subgraph.json", "Find the densest part of the Yelp graph."),
    "count": ("17-maximal-biclique-counting.json", "How many maximal bicliques are in the Yelp graph?"),
}
settings = replace(
    Settings.from_env(ROOT), data_root=DATA, accounts_enabled=False,
    account_cookie_secure=False, api_token="results-acceptance-test",
    llm_enabled=False, graph_gpu_uuid=None, llm_gpu_uuid=None,
    analytics_gpu_uuids=(), analytics_python=Path(sys.executable),
    native_runtime_library=ROOT / "library/build/runtime/libgraphmine_runtime.so",
    native_runtime_binary=ROOT / "library/build/runtime/graphmine-native",
    backend_data_dir=DATA / "backend-data", backend_model_dir=DATA / "backend-models",
    capture_enabled=False, retention_days=0, backup_directory=None,
)
app = create_app(settings)
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def seeded_lifespan(application):
    async with original_lifespan(application):
        runtime = application.state.runtime
        manifest = DATA / "acceptance-cases.json"
        if not manifest.is_file():
            session = runtime.database.create_session(SessionRecord(title="Yelp", domain_id="general"))
            cases = {}
            for name, (filename, question) in CASES.items():
                directory = os.environ.get("GRAPHMINE_RESULTS_FIXTURES")
                source = Path(directory) / (name + ".json") if directory else ROOT / "agent/tests/fixtures/view-goldens" / filename
                fixture = json.loads(source.read_text())
                if not directory:
                    # Stable example names make mouse/action assertions portable;
                    # source identifiers and attributes remain anonymized.
                    for vertex in fixture["input"]["vertices"]:
                        vertex["type"] = {"Type 1": "User", "Type 2": "Business"}.get(vertex.get("type"), vertex.get("type"))
                        vertex["label"] = {"entity-0": "Tracy", "entity-5": "Mesa Verde"}.get(vertex["id"], vertex.get("label", str(vertex["id"])))
                # Captured database snapshots omit upload-only graph flags.
                fixture["input"]["graph"].setdefault("allows_self_loops", True)
                fixture["input"]["graph"].setdefault("allows_parallel_edges", True)
                uploaded = runtime.graph_store.ingest(
                    session_id=session.id, role=FileRole.graph, filename="Yelp.json",
                    content=json.dumps(fixture["input"]).encode(), media_type="application/json",
                )
                result = fixture["result"]
                parameters = dict(fixture.get("parameters", result.get("parameters", {})))
                if not directory and result["operation"] == "maximal-bicliques":
                    # The anonymized fixture retains the two declared types,
                    # while its sanitized parameters omit source identifiers.
                    for side, kind in (("left_partition", "User"), ("right_partition", "Business")):
                        parameters[side] = [v["id"] for v in fixture["input"]["vertices"] if v.get("type") == kind]
                body = WorkflowRequest.model_validate({
                    "mode": "expert", "inputs": {"main": {"kind": "graph", "file_id": uploaded.id}},
                    "plan": {"version": 1, "device": "cpu", "steps": [{
                        "id": "analysis", "operation": result["operation"],
                        "input": {"input": "main"}, "parameters": parameters,
                    }]},
                })
                record = await runtime.analytics.create(session.id, body)
                record.update(status="completed", complete=True, question=question,
                              steps={"analysis": {"status": "completed"}})
                directory = runtime.analytics._directory(record)
                step = {"status": "completed", "result": result}
                runtime.analytics._write(directory / "step-analysis.json", step)
                runtime.analytics._write(directory / "result.json", {
                    "status": "completed", "complete": True, "steps": {"analysis": step},
                })
                runtime.analytics._save(record)
                cases[name] = {"workflow": record["id"], "session": session.id,
                               "file": uploaded.id, "fixture": filename, "question": question}
            manifest.write_text(json.dumps(cases, indent=2))
        yield


app.router.lifespan_context = seeded_lifespan
