"""Self-contained, offline answer reports using the same tested browser views."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ResultRecord


def render_report(result: ResultRecord) -> str:
    static = Path(__file__).parent / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    # Escape '<' even in JSON data blocks: an uploaded '</script>' must never
    # terminate its data element or become executable markup.
    data = (
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    html = html.replace(
        '<link rel="stylesheet" href="/styles.css">',
        "<style>" + (static / "styles.css").read_text(encoding="utf-8") + "</style>",
    )
    html = html.replace(
        '<script src="/vendor/cytoscape.min.js" defer></script>',
        '<script id="graphmine-report" type="application/json">'
        + data
        + "</script><script>"
        + (static / "vendor/cytoscape.min.js").read_text(encoding="utf-8")
        + "</script>",
    )
    return html.replace(
        '<script src="/app.js" defer></script>',
        "<script>" + (static / "app.js").read_text(encoding="utf-8") + "</script>",
    )
