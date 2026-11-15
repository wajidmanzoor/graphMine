"""Self-contained, offline answer reports using the same tested browser views."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic_core import to_jsonable_python

from .export_streams import CHUNK
from .models import ResultRecord


def iter_report(result: ResultRecord):
    static = Path(__file__).parent / "static"
    template = (static / "index.html").read_text(encoding="utf-8")
    template = template.replace('<script src="/account.js" defer></script>', "")
    assets = {
        '<link rel="stylesheet" href="/styles.css">': "styles.css",
        **{f'<script src="/vendor/{name}" defer></script>': f"vendor/{name}"
           for name in ("cytoscape.min.js", "vega.min.js", "vega-lite.min.js", "vega-embed.min.js")},
        '<script src="/app.js" defer></script>': "app.js",
    }
    # These three fields are stored JSON. Reuse their objects instead of making
    # a second deep copy of every result row through model_dump().
    data = result.model_dump(mode="json", exclude={"payload", "summary", "answer"})
    data.update(payload=result.payload, summary=result.summary, answer=result.answer)
    encoder = json.JSONEncoder(ensure_ascii=False, default=to_jsonable_python)
    start = 0
    for match in re.finditer("|".join(map(re.escape, assets)), template):
        yield template[start:match.start()]
        asset = assets[match.group()]
        if asset == "vendor/cytoscape.min.js":
            yield '<script id="graphmine-report" type="application/json">'
            # Escaping '<' prevents uploaded script-closing text from ending
            # its JSON element. Splitting before escaping also bounds output.
            for text in encoder.iterencode(data):
                for offset in range(0, len(text), CHUNK):
                    yield (text[offset:offset + CHUNK].replace("<", "\\u003c")
                           .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
            yield "</script>"
        style = asset.endswith(".css")
        yield "<style>" if style else "<script>"
        # Static assets have fixed size independent of result size. Read one
        # asset at a time so no complete inline HTML document is assembled.
        content = (static / asset).read_text(encoding="utf-8")
        if not style:
            content = content.replace("</script", "<\\/script")
        for offset in range(0, len(content), CHUNK):
            yield content[offset:offset + CHUNK]
        yield "</style>" if style else "</script>"
        start = match.end()
    yield template[start:]


def render_report(result: ResultRecord) -> str:
    """Compatibility helper; downloads and evidence snapshots use iter_report."""
    return "".join(iter_report(result))
