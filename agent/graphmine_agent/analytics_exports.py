"""Prepare private exports on disk; downloads never retain whole export buffers."""

import base64
import binascii
import csv
import math
import struct
import hashlib
import html
import json
import re
import zipfile

from fastapi import Query, Request
from pydantic import Field
from .models import StrictModel
from .result_tables import named_rows

from .analytics import AnalyticsError, _json
from .analytics_answers import build_facts
from .export_streams import CHUNK, copy_chunks, prepare_download, temporary, write_json
from .result_cache import read_json


def _cell(value):
    if isinstance(value, (dict, list)) or value is None:
        return _json(value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


class Budget:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def add(self, size):
        if self.limit is not None and self.used + size > self.limit:
            raise AnalyticsError("Export exceeds the byte budget", "resource_limit")
        self.used += size


class Writer:
    def __init__(self, target, budget):
        self.target, self.budget, self.size = target, budget, 0
        self.digest = hashlib.sha256()

    def write(self, raw):
        self.budget.add(len(raw))
        self.target.write(raw); self.digest.update(raw); self.size += len(raw)
        return len(raw)


class TextWriter:
    def __init__(self, target):
        self.target = target

    def write(self, text):
        for offset in range(0, len(text), CHUNK):
            self.target.write(text[offset:offset + CHUNK].encode("utf-8"))
        return len(text)


def columns(rows):
    names = {}
    for row in rows:
        names.update(dict.fromkeys(row if isinstance(row, dict) else ("value",)))
    return list(names) or ["value"]


def write_csv(stream, rows, fields, *, json_booleans=False):
    stream.write(b"\xef\xbb\xbf")
    writer = csv.DictWriter(TextWriter(stream), fieldnames=fields, lineterminator="\r\n")
    writer.writerow({field: _cell(field) for field in fields})
    for row in rows:
        row = row if isinstance(row, dict) else {"value": row}
        writer.writerow({key: _json(value) if json_booleans and isinstance(value, bool) else _cell(value) for key, value in row.items()})


def table_csv(port, stream, graph=None):
    if port.get("type") in {"motif_instances", "graphlet_instances"} and isinstance(port.get("value"), dict):
        write_csv(stream, [port["value"]], columns([port["value"]])); return
    write_csv(stream, named_rows(port, graph), columns(named_rows(port, graph)))


def export_csv(service, workflow_id, step, port, *, expected_revision=None):
    output = temporary()
    try:
        with service._indexed(workflow_id, step=step, expected_revision=expected_revision) as index:
            key = _json(["", port]); metadata, _, _ = index.metadata(key)
            writer = Writer(output, Budget(4 * service.settings.max_result_bytes if service.settings.max_result_bytes is not None else None))
            from .result_views import input_graph
            record = service.get(workflow_id)
            graph = input_graph(service, record, step) if (service._directory(record) / "inputs.json").is_file() else None
            if metadata.get("presentation_only"):
                saved = service._saved(workflow_id, step=step, expected_revision=expected_revision)
                table_csv(saved["result"]["ports"][port], writer, graph)
            else:
                write_csv(writer, named_rows(metadata, graph, index.rows(key)), columns(named_rows(metadata, graph, index.rows(key))))
        return output
    except BaseException:
        output.close(); raise


def export_json(service, workflow_id, *, step=None, expected_revision=None):
    output = temporary()
    try:
        # A warm index establishes validity without retaining another full
        # parsed result; its exit check pins owner, revision and file token.
        with service._indexed(workflow_id, step=step, expected_revision=expected_revision):
            path = service._result_path(workflow_id, step=step, expected_revision=expected_revision)
            with path.open("rb") as source:
                copy_chunks(source, output, service.settings.max_result_bytes)
        return output
    except BaseException:
        output.close(); raise


def export_partial_json(service, workflow_id, *, expected_revision=None):
    record = service.get(workflow_id)
    if expected_revision is not None and record["revision"] != expected_revision:
        raise AnalyticsError("This analysis revision changed. Reopen its results.", "revision_conflict", 409)
    output = temporary()
    writer = Writer(output, Budget(4 * (service.settings.analytics_max_input_bytes + service.settings.max_result_bytes)
                                  if service.settings.analytics_max_input_bytes is not None and service.settings.max_result_bytes is not None else None))
    try:
        writer.write(b'{"partial_workflow":true,"complete":false,"workflow":')
        write_json(writer, record); writer.write(b',"steps":{')
        first = True
        order = record["validation"].get("order") or [step["id"] for step in record["validation"]["plan"]["steps"]]
        for step in order:
            if record.get("steps", {}).get(step, {}).get("status") != "completed":
                continue
            with service._indexed(workflow_id, step=step, expected_revision=record["revision"]):
                path = service._result_path(workflow_id, step=step, expected_revision=record["revision"])
                if not first:
                    writer.write(b',')
                first = False; write_json(writer, step); writer.write(b':')
                with path.open("rb") as source:
                    copy_chunks(source, writer, service.settings.max_result_bytes)
        writer.write(b'}}')
        if service.get(workflow_id)["revision"] != record["revision"]:
            raise AnalyticsError("This analysis revision changed. Reopen its results.", "revision_conflict", 409)
        return output
    except BaseException:
        output.close(); raise


def _escaped(stream, text):
    for offset in range(0, len(text), CHUNK):
        stream.write(html.escape(text[offset:offset + CHUNK], quote=True).encode())


def default_svg(view):
    """A self-contained vector fallback for API clients without a browser image."""
    width, height = 960, 540
    vertices, edges = view.get("vertices", []), view.get("edges", [])
    points = {}
    sides = view.get("bipartite_sides")
    if sides:
        for side, ids in enumerate(sides):
            for i, value in enumerate(ids):
                points[_json(value)] = (120 + i * 720 / max(1, len(ids) - 1) if len(ids) > 1 else 480, 180 + side * 180)
    else:
        for i, vertex in enumerate(vertices):
            angle = i * 2 * math.pi / max(1, len(vertices))
            points[_json(vertex["id"])] = (480 + 320 * math.cos(angle), 255 + 185 * math.sin(angle))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>']
    for edge in edges:
        a, b = points.get(_json(edge["source"])), points.get(_json(edge["target"]))
        if a and b:
            parts.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#a8bac8"/>')
    for vertex in vertices:
        x, y = points[_json(vertex["id"])]
        color = "#d55e00" if vertex.get("view", {}).get("side") == 1 else "#0072b2"
        parts.append(f'<circle cx="{x}" cy="{y}" r="12" fill="{color}"/><text x="{x}" y="{y + 29}" text-anchor="middle" font-size="12" font-family="sans-serif">{html.escape(vertex.get("label", str(vertex["id"])))}</text>')
    if not vertices:
        value = view.get("answer", {}).get("metrics", [{}])[0].get("value", "")
        parts.append(f'<text x="480" y="280" text-anchor="middle" font-size="64" font-family="sans-serif">{html.escape(str(value))}</text>')
    return ("".join(parts) + "</svg>").encode()


def _html(stream, record, plan, manifest, view, rows, image_name, findings=()):
    answer = view["answer"]
    text = TextWriter(stream)
    text.write('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; img-src &#39;self&#39; data:; style-src &#39;unsafe-inline&#39;">'
        '<title>GraphMine analysis report</title><style>body{font:16px system-ui;color:#203b43;max-width:70rem;margin:2rem auto;padding:1rem;line-height:1.5}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1,h2{line-height:1.2}.metrics{display:flex;gap:12px;flex-wrap:wrap}.metric{flex:1;min-width:130px;background:#edf4f1;padding:14px;border-radius:8px}.metric strong{display:block;font-size:28px}.metric small{display:block}img{width:100%;height:auto;border:1px solid #d9e2de;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;text-align:left;border-bottom:1px solid #d9e2de}details{margin:16px 0}</style><h1>')
    _escaped(stream, answer["title"]); text.write('</h1><p>'); _escaped(stream, answer["sentence"]); text.write('</p><div class="metrics">')
    for metric in answer["metrics"]:
        text.write('<div class="metric">'); _escaped(stream, metric["label"]); text.write('<strong>'); _escaped(stream, str(metric["value"])); text.write('</strong>')
        if metric.get("note"):
            text.write('<small>'); _escaped(stream, metric["note"]); text.write('</small>')
        text.write('</div>')
    text.write('</div><p>'); _escaped(stream, ' · '.join(v for v in ((answer.get('quality') or '').capitalize(), (answer.get('device') or '').upper(), 'Validated' if answer['validated'] else '') if v)); text.write('</p>')
    text.write(f'<img src="{image_name}" alt="Default result view"><h2>Result table</h2>')
    fields = [field for field in columns(rows) if field not in {"id", "ids"} and not field.endswith("_ids")]
    text.write('<table><thead><tr>')
    for field in fields:
        text.write('<th>'); _escaped(stream, field.replace('_', ' ').capitalize()); text.write('</th>')
    text.write('</tr></thead><tbody>')
    for row in rows[:200]:
        text.write('<tr>')
        for field in fields:
            text.write('<td>'); _escaped(stream, str(row.get(field, ''))); text.write('</td>')
        text.write('</tr>')
    text.write('</tbody></table><p>Full retained tables:</p><ul>')
    for path, meta in manifest["outputs"].items():
        text.write(f'<li><a href="{html.escape(path, quote=True)}">'); _escaped(stream, f"{meta['step']} / {meta['port']}"); text.write('</a></li>')
    text.write('</ul><h2>Reproduce</h2><p>Use the matching verified GraphMine installation and native build recorded in manifest.json. Set GRAPHMINE_REPOSITORY_ROOT and the native library paths for that installation. Inputs are stored once in inputs.json; request.json references their SHA-256. From the extracted report folder:</p><pre>')
    _escaped(stream, """import hashlib, json, subprocess, sys
from pathlib import Path
request = json.loads(Path('request.json').read_text())
raw = Path(request.pop('inputs_file')).read_bytes()
assert hashlib.sha256(raw).hexdigest() == request.pop('inputs_sha256')
request['inputs'] = json.loads(raw)
request['plan'] = json.loads(Path(request.pop('plan_file')).read_text())
subprocess.run([sys.executable, '-m', 'graphmine.worker'],
               input=json.dumps(request).encode(), check=True)
""")
    text.write('</pre><p>The worker revalidates the workflow and execution evidence. A changed environment can require a new validation; randomized methods may differ.</p><details><summary>Appendix: plan and provenance</summary><pre>')
    for value in (plan, {**manifest, 'rules_applied': view['view_spec']['rules_applied']}):
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, indent=2).iterencode(value):
            _escaped(stream, chunk)
    text.write('</pre><h3>Additional recorded findings</h3><ul>')
    for finding in findings:
        text.write('<li>'); _escaped(stream, finding['text']); text.write('</li>')
    text.write('</ul></details></html>')


def report_bundle(service, workflow_id, *, expected_revision=None, default_image=None, step=None, port=None):
    from .result_index import file_stamp

    record = service.get(workflow_id)
    if expected_revision is not None and record["revision"] != expected_revision:
        raise AnalyticsError("This analysis revision changed. Reopen the analysis to load its current result.", "revision_conflict", 409)
    path = service._result_path(workflow_id, expected_revision=record["revision"])
    input_path = service._directory(record) / "inputs.json"
    stamps = [file_stamp(path), file_stamp(input_path)]
    saved = service._saved(workflow_id, expected_revision=record["revision"])
    inputs = read_json(input_path, service.settings.analytics_max_input_bytes)
    manifest = {
        "format": "graphmine-report-v1", "workflow_id": workflow_id, "revision": record["revision"],
        "status": record["status"], "created_at": record.get("created_at"), "finished_at": record.get("finished_at"),
        "workflow_hash": record["validation"]["workflow_hash"], "environment": record["validation"].get("environment"),
        "implementation_sha256": record["validation"].get("implementation_sha256"),
        "input_provenance": record.get("input_provenance", {}), "input_fingerprints": record["validation"].get("inputs", {}),
        "csv_text_formula_escaped": True,
        "csv_note": "JSON artifacts preserve exact identifier types, nested data and precision. CSV is a spreadsheet-safe view.", "outputs": {},
    }
    from .result_views import input_graph, profile, default_index, focus_graph, view_items, _bipartite_sides
    from .view_data import enrich_view
    from .result_summary import summary
    completed = [(name, item["result"]) for name, item in saved.get("steps", {}).items() if item.get("status", record.get("steps", {}).get(name, {}).get("status")) == "completed" and item.get("result", {}).get("ports")]
    if not completed:
        raise AnalyticsError("No completed result is available for this report", "invalid_view")
    if (step is None) != (port is None):
        raise AnalyticsError("Choose both a report step and output", "invalid_view")
    if step is not None and step not in dict(completed):
        raise AnalyticsError("The report step has no completed result", "invalid_view")
    main_step, main_result = (step, dict(completed)[step]) if step is not None else completed[-1]
    preferred = profile(main_result.get("problem")).get("preferred_ports", [])
    main_port = port or next((name for name in preferred if name in main_result["ports"]), next(iter(main_result["ports"])))
    if main_port not in main_result["ports"]:
        raise AnalyticsError("The report output is unavailable", "invalid_view")
    manifest["primary_output"] = {"step": main_step, "port": main_port}
    main_graph = input_graph(service, record, main_step)
    selected_port = main_result["ports"][main_port]
    index = default_index(selected_port, None)
    focused, note, selected, selected_edges = focus_graph(main_graph, main_result, main_port, index)
    graph = focused or {"vertices": [], "edges": []}
    view = {"workflow_id": workflow_id, "revision": record["revision"], "step": main_step, "port": main_port,
            "profile": profile(main_result.get("problem")), "index": index, "context": False,
            "complete": selected_port.get("complete", True), "graph_available": focused is not None,
            "vertices": graph["vertices"][:2000], "edges": graph["edges"][:5000], "graph": graph.get("graph", {}),
            "vertex_count": len(graph["vertices"]), "edge_count": len(graph["edges"]),
            "selected_vertices": selected, "selected_edges": selected_edges, "note": note}
    if selected_port.get("type") == "bipartite_groups" and index is not None:
        view["bipartite_sides"] = _bipartite_sides(view_items(selected_port)[index])
    view = enrich_view(view, main_result, main_port, main_graph, focused)
    view["answer"] = summary(view, main_result, record, service._question(record))
    from itertools import islice
    report_rows = list(islice(named_rows(main_result["ports"][main_port], main_graph), 200))
    output, files = temporary(), {}
    budget = Budget(4 * (service.settings.analytics_max_input_bytes + service.settings.max_result_bytes)
                    if service.settings.analytics_max_input_bytes is not None and service.settings.max_result_bytes is not None else None)
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            def entry(name, write, *, include=True):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
                with archive.open(info, "w", force_zip64=True) as target:
                    writer = Writer(target, budget); write(writer)
                if include:
                    files[name] = {"sha256": writer.digest.hexdigest(), "size_bytes": writer.size}
            plan = record["validation"]["plan"]
            for name, value in (("plan.json", plan), ("inputs.json", inputs), ("result.json", saved)):
                entry(name, lambda stream: write_json(stream, value))
            request = {"command": "run", "plan_file": "plan.json", "inputs_file": "inputs.json", "inputs_sha256": files["inputs.json"]["sha256"], "expected_hash": record["validation"]["workflow_hash"]}
            entry("request.json", lambda stream: write_json(stream, request))
            image_name = "default-view.png" if default_image else "default-view.svg"
            entry(image_name, lambda stream: stream.write(default_image or default_svg(view)))
            for step, artifact in saved.get("steps", {}).items():
                for port_name, port in (artifact.get("result") or {}).get("ports", {}).items():
                    safe = re.sub(r"[^A-Za-z0-9_-]", "_", step + "-" + port_name)
                    name = f"tables/{len(manifest['outputs']) + 1}-{safe}.csv"
                    manifest["outputs"][name] = {"step": step, "port": port_name, "type": port["type"], "complete": port.get("complete")}
                    entry(name, lambda stream: table_csv(port, stream, input_graph(service, record, step)))
            entry("report.html", lambda stream: _html(stream, record, plan, manifest, view, report_rows, image_name, build_facts(saved, {}, {})))
            manifest["files"] = files
            entry("manifest.json", lambda stream: write_json(stream, manifest), include=False)
        service._result_path(workflow_id, expected_revision=record["revision"])
        if stamps != [file_stamp(path), file_stamp(input_path)]:
            raise AnalyticsError("The analysis changed while its report was prepared. Retry the download.", "revision_conflict", 409)
        return output
    except BaseException:
        output.close(); raise


class ReportImage(StrictModel):
    expected_revision: int = Field(ge=1)
    default_image: str = Field(max_length=12 * 1024 * 1024)
    step: str = Field(min_length=1, max_length=128)
    port: str = Field(min_length=1, max_length=128)


def report_png(encoded):
    try:
        value = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AnalyticsError("The report image must be a PNG", "invalid_view") from exc
    if len(value) < 33 or value[:8] != b"\x89PNG\r\n\x1a\n" or value[12:16] != b"IHDR":
        raise AnalyticsError("The report image must be a PNG", "invalid_view")
    width, height = struct.unpack(">II", value[16:24])
    if width < 1 or height < 1 or width * height > 32000000:
        raise AnalyticsError("Report image dimensions exceed the export budget", "resource_limit", 413)
    return value


def register_export_routes(router):
    @router.post("/workflows/{workflow_id}/report")
    async def report_with_image(workflow_id: str, body: ReportImage, request: Request):
        service = request.app.state.runtime.analytics
        image = report_png(body.default_image)
        async with service.edit_lock:
            return await prepare_download(service, report_bundle, service, workflow_id, expected_revision=body.expected_revision,
                                          default_image=image, step=body.step, port=body.port,
                                          filename="graphmine-report.zip", media_type="application/zip")

    @router.get("/workflows/{workflow_id}/report")
    async def report(workflow_id: str, request: Request, expected_revision: int | None = Query(None, ge=1)):
        service = request.app.state.runtime.analytics
        async with service.edit_lock:
            return await prepare_download(service, report_bundle, service, workflow_id, expected_revision=expected_revision,
                                          filename="graphmine-report.zip", media_type="application/zip")

    @router.get("/workflows/{workflow_id}/steps/{step}/ports/{port}/csv")
    async def port_csv(workflow_id: str, step: str, port: str, request: Request, expected_revision: int | None = Query(None, ge=1)):
        service = request.app.state.runtime.analytics
        async with service.edit_lock:
            return await prepare_download(service, export_csv, service, workflow_id, step, port, expected_revision=expected_revision,
                                          filename="graphmine-table.csv", media_type="text/csv; charset=utf-8")
