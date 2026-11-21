"""Optional calculation limits: None means no automatic cutoff."""

import time

from .errors import AnalyticsError


def minimum_limit(*limits):
    return min((value for value in limits if value is not None), default=None)


def remaining_seconds(deadline, now=None):
    return None if deadline is None else deadline - (time.monotonic() if now is None else now)


async def response_lines(reader, maximum=None):
    """Read complete protocol messages without StreamReader's fixed line cap."""
    pending = bytearray()
    while chunk := await reader.read(65536):
        pending.extend(chunk)
        while (end := pending.find(b"\n")) >= 0:
            if maximum is not None and end + 1 > maximum:
                raise AnalyticsError("Worker output exceeded the byte budget", "resource_limit")
            yield bytes(pending[:end + 1])
            del pending[:end + 1]
        if maximum is not None and len(pending) > maximum:
            raise AnalyticsError("Worker output exceeded the byte budget", "resource_limit")
    if pending:
        yield bytes(pending)
