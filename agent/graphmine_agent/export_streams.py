"""Private prepared downloads with bounded buffers and deterministic cleanup."""

import asyncio
import json
import tempfile

from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

CHUNK = 64 * 1024
ENCODER = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def temporary():
    # Unlinked/0600 on supported platforms; normal completion and process exit
    # both remove these files. Export data never enters a shared named cache.
    return tempfile.TemporaryFile(mode="w+b", prefix="graphmine-export-")


def write_json(stream, value):
    for text in ENCODER.iterencode(value):
        for offset in range(0, len(text), CHUNK):
            stream.write(text[offset:offset + CHUNK].encode("utf-8"))


def copy_chunks(source, destination, limit):
    from .analytics import AnalyticsError

    total = 0
    while raw := source.read(CHUNK):
        total += len(raw)
        if total > limit:
            raise AnalyticsError("Export exceeds the byte budget", "resource_limit")
        destination.write(raw)
    return total


class Download(StreamingResponse):
    def __init__(self, handle, *, filename, media_type, release=lambda: None):
        self.handle, self.release, self.closed = handle, release, False
        size = handle.seek(0, 2); handle.seek(0)
        async def chunks():
            while raw := await run_in_threadpool(handle.read, CHUNK):
                yield raw
        super().__init__(chunks(), media_type=media_type, headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size), "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        })

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.handle.close()
            finally:
                self.release()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.close()  # Also runs on disconnect, send failure and cancellation.


async def prepare_download(service, builder, *args, filename, media_type, **kwargs):
    from .analytics import AnalyticsError

    slots = service.export_slots
    if slots.locked():
        raise AnalyticsError("Downloads are busy. Retry shortly.", "busy", 429)
    await slots.acquire()
    task = asyncio.create_task(run_in_threadpool(builder, *args, **kwargs))
    try:
        handle = await asyncio.shield(task)
    except asyncio.CancelledError:
        # A thread may still be building after its request is cancelled. Keep
        # its slot until it finishes and close any orphaned result then.
        def abandoned(done):
            try:
                done.result().close()
            except BaseException:
                pass
            finally:
                slots.release()
        task.add_done_callback(abandoned)
        raise
    except BaseException:
        slots.release(); raise
    try:
        return Download(handle, filename=filename, media_type=media_type, release=slots.release)
    except BaseException:
        handle.close(); slots.release(); raise
