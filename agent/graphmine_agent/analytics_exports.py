"""Exports read immutable saved artifacts; they never launch another calculation."""

import csv
import hashlib
import html
import io
import json
import re
import zipfile

from fastapi import Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json
from .analytics_answers import build_facts
from .database import RecordNotFound


def _cell(value):
    if isinstance(value, (dict, list)) or value is None:
        return _json(value)
    if isinstance(value, str) and value.lstrip().startswith(
        ("=", "+", "-", "@", "\t", "\r")
    ):
        return "'" + value  # Keep imported text from becoming a spreadsheet formula.
    return value


def table_csv(port):
    value = port["value"]
    rows = value if isinstance(value, list) else [value]
    rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["value"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writerow({field: _cell(field) for field in fields})
    for row in rows:
        writer.writerow({key: _cell(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def export_csv(service, workflow_id, step, port):
    output = (
        service._saved(workflow_id, step=step)
        .get("result", {})
        .get("ports", {})
        .get(port)
    )
    if output is None:
        raise RecordNotFound("Result port not found")
    return table_csv(output)


def report_bundle(service, workflow_id):
    record = service.get(workflow_id)
    saved = service._saved(workflow_id)
    inputs = json.loads((service._directory(record) / "inputs.json").read_bytes())
    manifest = {
        "format": "graphmine-report-v1",
        "workflow_id": workflow_id,
        "revision": record["revision"],
        "status": record["status"],
        "created_at": record.get("created_at"),
        "finished_at": record.get("finished_at"),
        "workflow_hash": record["validation"]["workflow_hash"],
        "environment": record["validation"].get("environment"),
        "implementation_sha256": record["validation"].get("implementation_sha256"),
        "input_provenance": record.get("input_provenance", {}),
        "input_fingerprints": record["validation"].get("inputs", {}),
        "csv_text_formula_escaped": True,
        "csv_note": "JSON artifacts preserve exact identifier types, nested data and precision. CSV is a spreadsheet-safe view.",
        "outputs": {},
    }
    plan = record["validation"]["plan"]
    entries = {
        "plan.json": _json(plan).encode(),
        "inputs.json": _json(inputs).encode(),
        "result.json": _json(saved).encode(),
        "request.json": _json(
            {
                "command": "run",
                "plan": plan,
                "inputs": inputs,
                "expected_hash": record["validation"]["workflow_hash"],
            }
        ).encode(),
    }
    for step, artifact in saved.get("steps", {}).items():
        for name, port in (artifact.get("result") or {}).get("ports", {}).items():
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", step + "-" + name)
            # Include an index to avoid filename collisions after sanitization.
            path = f"tables/{len(manifest['outputs']) + 1}-{safe}.csv"
            entries[path] = table_csv(port)
            manifest["outputs"][path] = {
                "step": step,
                "port": name,
                "type": port["type"],
                "complete": port.get("complete"),
            }
    facts = build_facts(saved, {}, {})
    esc = lambda value: html.escape(str(value), quote=True)
    items = "".join(f"<li>{esc(fact['statement'])}</li>" for fact in facts)
    outputs = "".join(
        f'<li><a href="{esc(path)}">{esc(meta["step"])} / {esc(meta["port"])}</a> · {"complete" if meta["complete"] else "incomplete"}</li>'
        for path, meta in manifest["outputs"].items()
    )
    entries["report.html"] = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>GraphMine analysis report</title><style>body{font:16px system-ui;max-width:70rem;margin:2rem auto;padding:1rem;line-height:1.5}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1,h2{line-height:1.2}</style>"
        f"<h1>GraphMine analysis report</h1><p>Workflow {esc(workflow_id)} · revision {record['revision']} · {esc(record['status'])}</p>"
        f"<h2>Recorded findings</h2><ul>{items}</ul><h2>Full tables</h2><ul>{outputs}</ul>"
        "<p>Completeness belongs to each output. A complete output does not make a heuristic exact. Tables contain the full retained data, including rows outside browser previews.</p>"
        f"<h2>Plan</h2><pre>{esc(json.dumps(plan, ensure_ascii=False, indent=2))}</pre>"
        f"<h2>Provenance</h2><pre>{esc(json.dumps(manifest, ensure_ascii=False, indent=2))}</pre>"
        "<h2>Reproduction</h2><p>The bundle includes exact inputs, plan, results and a worker request. Replaying requires a compatible GraphMine installation with matching verified native artifacts and environment. Review the plan and budgets before running request.json; randomized methods may produce different results.</p></html>"
    ).encode()
    manifest["files"] = {
        path: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        for path, raw in entries.items()
    }
    entries["manifest.json"] = _json(manifest).encode()
    if sum(map(len, entries.values())) > 4 * (
        service.settings.analytics_max_input_bytes + service.settings.max_result_bytes
    ):
        raise AnalyticsError("Report exceeds the export byte budget", "resource_limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, raw in entries.items():
            # Fixed timestamps make repeated downloads of a revision identical.
            archive.writestr(
                zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0)),
                raw,
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return output.getvalue()


def register_export_routes(router):
    @router.get("/workflows/{workflow_id}/report")
    async def report(workflow_id: str, request: Request):
        service = request.app.state.runtime.analytics
        async with service.edit_lock:
            raw = await run_in_threadpool(report_bundle, service, workflow_id)
        return Response(
            raw,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="graphmine-report.zip"'
            },
        )

    @router.get("/workflows/{workflow_id}/steps/{step}/ports/{port}/csv")
    async def port_csv(workflow_id: str, step: str, port: str, request: Request):
        service = request.app.state.runtime.analytics
        async with service.edit_lock:
            raw = await run_in_threadpool(export_csv, service, workflow_id, step, port)
        return Response(
            raw,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="graphmine-table.csv"'
            },
        )
