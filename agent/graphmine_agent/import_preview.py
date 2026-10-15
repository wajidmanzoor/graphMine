"""Preview a bounded CSV import without persisting a file or charging a job."""

import hashlib
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from .csv_ingestion import graph_from_table, read_table
from .graph_store import UploadError
from .identity import current_principal


def preview(runtime, stream, filename, *, directed, source_column, target_column):
    limit = runtime.settings.max_upload_bytes
    if current_principal.get():
        limit = min(limit, runtime.settings.account_upload_bytes)
    with tempfile.TemporaryDirectory(prefix="graphmine-import-") as directory:
        path = Path(directory) / (
            "input.csv" if filename.lower().endswith(".csv") else "input.txt"
        )
        digest, size = hashlib.sha256(), 0
        with path.open("wb") as output:
            while chunk := stream.read(min(1024 * 1024, limit - size + 1)):
                size += len(chunk)
                if size > limit:
                    raise UploadError("Import preview exceeds the upload byte limit")
                digest.update(chunk)
                output.write(chunk)
        table = read_table(path)
        graph = graph_from_table(
            table,
            directed=directed,
            source_column=source_column,
            target_column=target_column,
            digest=digest.hexdigest(),
            edge_list=path.suffix.lower() != ".csv",
        )
        runtime.graph_store._validate_graph(graph)
        metadata = runtime.graph_store._metadata("preview", graph).model_dump(
            mode="json"
        )
        return {
            "columns": table["columns"],
            "sample": table["rows"][:8],
            "row_count": len(table["rows"]),
            "sample_is_excerpt": len(table["rows"]) > 8,
            "metadata": metadata,
            "provenance": graph["graph"]["attributes"]["ingestion"],
            "vertices": graph["vertices"][:20],
            "edges": graph["edges"][:20],
        }


def register_import_routes(router):
    @router.post("/sessions/{session_id}/files/preview")
    async def import_preview(
        session_id: str,
        request: Request,
        file: Annotated[UploadFile, File()],
        directed: Annotated[bool, Form()] = False,
        source_column: Annotated[str | None, Form()] = None,
        target_column: Annotated[str | None, Form()] = None,
    ):
        runtime = request.app.state.runtime
        runtime.database.get_session(session_id)
        if runtime.upload_slots.locked():
            raise HTTPException(429, "Uploads are busy. Please retry shortly.")
        async with runtime.upload_slots:
            return await run_in_threadpool(
                preview,
                runtime,
                file.file,
                file.filename or "input.csv",
                directed=directed,
                source_column=source_column,
                target_column=target_column,
            )
