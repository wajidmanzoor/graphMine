"""Prepare private exports on disk; downloads never retain whole export buffers."""

import csv
import hashlib
import html
import json
import re
import zipfile

from fastapi import Query, Request

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
        if self.used + size > self.limit:
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


def table_csv(port, stream):
    value = port["value"]
    rows = value if isinstance(value, list) else [value]
    write_csv(stream, rows, columns(rows))


def export_csv(service, workflow_id, step, port, *, expected_revision=None):
    output = temporary()
    try:
        with service._indexed(workflow_id, step=step, expected_revision=expected_revision) as index:
            key = _json(["", port]); metadata, _, _ = index.metadata(key)
            writer = Writer(output, Budget(4 * service.settings.max_result_bytes))
            if metadata.get("presentation_only"):
                # Display rows flatten a native map. CSV keeps its native shape.
                saved = service._saved(workflow_id, step=step, expected_revision=expected_revision)
                table_csv(saved["result"]["ports"][port], writer)
            else:
                write_csv(writer, index.rows(key), columns(index.rows(key)))
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
    writer = Writer(output, Budget(4 * (service.settings.analytics_max_input_bytes + service.settings.max_result_bytes)))
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


def _html(stream, record, plan, manifest, facts):
    text = TextWriter(stream)
    text.write('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        '<title>GraphMine analysis report</title><style>body{font:16px system-ui;max-width:70rem;margin:2rem auto;padding:1rem;line-height:1.5}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1,h2{line-height:1.2}</style>'
        '<h1>GraphMine analysis report</h1><p>Workflow ')
    _escaped(stream, f"{record['id']} · revision {record['revision']} · {record['status']}")
    text.write('</p><h2>Recorded findings</h2><ul>')
    for fact in facts:
        text.write('<li>'); _escaped(stream, fact["statement"]); text.write('</li>')
    text.write('</ul><h2>Full tables</h2><ul>')
    for path, meta in manifest["outputs"].items():
        text.write(f'<li><a href="{html.escape(path, quote=True)}">')
        _escaped(stream, f"{meta['step']} / {meta['port']}")
        text.write(f'</a> · {"complete" if meta["complete"] else "incomplete"}</li>')
    text.write('</ul><p>Completeness belongs to each output. A complete output does not make a heuristic exact. Tables contain the full retained data, including rows outside browser previews.</p>')
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, indent=2)
    for heading, value in (("Plan", plan), ("Provenance", manifest)):
        text.write(f'<h2>{heading}</h2><pre>')
        for chunk in encoder.iterencode(value):
            _escaped(stream, chunk)
        text.write('</pre>')
    text.write('<h2>Reproduction</h2><p>The bundle includes exact inputs, plan, results and a worker request. Replaying requires a compatible GraphMine installation with matching verified native artifacts and environment. Review the plan and budgets before running request.json; randomized methods may produce different results.</p></html>')


def report_bundle(service, workflow_id, *, expected_revision=None):
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
    output, files = temporary(), {}
    budget = Budget(4 * (service.settings.analytics_max_input_bytes + service.settings.max_result_bytes))
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            def entry(name, write, *, include=True):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
                with archive.open(info, "w", force_zip64=True) as target:
                    writer = Writer(target, budget); write(writer)
                if include:
                    files[name] = {"sha256": writer.digest.hexdigest(), "size_bytes": writer.size}
            plan = record["validation"]["plan"]
            for name, value in (("plan.json", plan), ("inputs.json", inputs), ("result.json", saved),
                                ("request.json", {"command": "run", "plan": plan, "inputs": inputs, "expected_hash": record["validation"]["workflow_hash"]})):
                entry(name, lambda stream: write_json(stream, value))
            for step, artifact in saved.get("steps", {}).items():
                for port_name, port in (artifact.get("result") or {}).get("ports", {}).items():
                    safe = re.sub(r"[^A-Za-z0-9_-]", "_", step + "-" + port_name)
                    name = f"tables/{len(manifest['outputs']) + 1}-{safe}.csv"
                    manifest["outputs"][name] = {"step": step, "port": port_name, "type": port["type"], "complete": port.get("complete")}
                    entry(name, lambda stream: table_csv(port, stream))
            entry("report.html", lambda stream: _html(stream, record, plan, manifest, build_facts(saved, {}, {})))
            manifest["files"] = files
            entry("manifest.json", lambda stream: write_json(stream, manifest), include=False)
        service._result_path(workflow_id, expected_revision=record["revision"])
        if stamps != [file_stamp(path), file_stamp(input_path)]:
            raise AnalyticsError("The analysis changed while its report was prepared. Retry the download.", "revision_conflict", 409)
        return output
    except BaseException:
        output.close(); raise


def register_export_routes(router):
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
