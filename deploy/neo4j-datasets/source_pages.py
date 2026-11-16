#!/usr/bin/env python3
"""Copy and audit the publisher's Neo4j examples without changing their mapping.

Only the Cypher examples are selected; the pages also contain GQL alternatives.
OnTime's published shell loop is expanded by substituting its file names only.
LDBC's bulk importer is retained as a reference, never executed by this tool.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request


ROOT = Path(__file__).resolve().parent
DATASETS = {
    "yelp": ("Yelp", "yelp"),
    "movielens-32m": ("MovieLens 32M", "ml32m"),
    "movielens-genome": ("MovieLens Tag Genome", "mlgenome"),
    "stackoverflow": ("Stack Overflow", "stackof"),
    "ontime": ("OnTime", "ontime"),
    "ldbc-snb": ("LDBC SNB SF100 BI", "snb"),
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def text(self):
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        child = Node(tag, attrs, self.current)
        self.current.children.append(child)
        if tag not in VOID:
            self.current = child

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, value):
        self.current.children.append(value)


def compact(value):
    return " ".join(value.split())


def language(node):
    parent = node.parent
    while parent and "code-wrapper" not in parent.attrs.get("class", "").split():
        parent = parent.parent
    if parent:
        for item in parent.walk():
            if "code-header" in item.attrs.get("class", "").split():
                spans = [x for x in item.walk() if x.tag == "span"]
                if spans:
                    return compact(spans[0].text()).lower()
    return "unknown"


def extract(html):
    page = Page(html)
    mode, heading, query, block = None, "", None, 0
    loads, queries, titles, tables = [], defaultdict(list), {}, []
    for node in page.root.walk():
        if node.tag == "h3":
            text = compact(node.text())
            if text == "Data Loading":
                mode = "load"
            elif text == "Queries":
                mode = "queries"
        elif node.tag == "h4":
            heading = compact(node.text())
            if mode == "queries" and (match := re.match(r"Q(\d+)\.", heading)):
                query = int(match[1])
                titles[query] = heading
                queries[query]  # Also record queries for which no code is published.
        elif node.tag == "table" and mode is None:
            rows = []
            for tr in (n for n in node.walk() if n.tag == "tr"):
                cells = [compact(n.text()) for n in tr.children if isinstance(n, Node) and n.tag == "td"]
                if len(cells) == 2:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        elif node.tag == "pre":
            block += 1
            item = {"block": block, "language": language(node), "heading": heading, "body": node.text()}
            if mode == "load":
                loads.append(item)
            elif mode == "queries" and query is not None and item["language"] == "cypher":
                queries[query].append(item)
    if len(tables) != 2 or not loads or not titles:
        raise ValueError("Publisher layout changed: expected two statistics tables, loading, and queries")
    return loads, queries, titles, tables


def header(url, copied_at, block, *, shell=False, change=None):
    mark = "#" if shell else "//"
    lines = [f"{mark} Source: {url}", f"{mark} Copied: {copied_at}", f"{mark} Published code block: {block}"]
    if change:
        lines.append(f"{mark} Path change: {change}")
    return "\n".join(lines) + "\n"


def counts(tables):
    nodes, relationships, edge_rows, totals = {}, defaultdict(int), [], {}
    for kind, rows in zip(("nodes", "relationships"), tables):
        for label, text in rows:
            if not re.fullmatch(r"[\d,\s]+", text):
                raise ValueError(f"Non-exact published count: {label}: {text}")
            count = int(re.sub(r"[,\s]", "", text))
            if label.lower().startswith("total"):
                totals[kind] = count
            elif kind == "nodes":
                nodes[label] = count
            else:
                match = re.search(r"\[:([^\]]+)\]", label)
                rel_type = match[1] if match else label
                relationships[rel_type] += count
                edge_rows.append({"pattern": label, "type": rel_type, "count": count})
    return {"nodes": nodes, "relationships": dict(relationships), "relationship_rows": edge_rows,
            "published_totals": totals, "published_tables": tables}


def artifacts(slug, html, url, copied_at):
    loads, queries, titles, tables = extract(html)
    files, order, references, required, query_manifest = {}, [], [], set(), []
    for item in loads:
        block, body = item["block"], item["body"]
        if item["language"] == "cypher":
            path = f"load/{len(order) + 1:03d}.cypher"
            files[path] = header(url, copied_at, block) + body
            order.append({"file": path, "source_block": block, "heading": item["heading"]})
            required.update(re.findall(r"file:///([^\s\"'\)]+)", body))
        else:
            path = f"reference/load-{block:03d}.sh"
            files[path] = header(url, copied_at, block, shell=True) + body
            references.append({"file": path, "source_block": block, "language": item["language"], "heading": item["heading"]})
            if slug == "ontime" and "<< CYPHER" in body:
                cypher = body.split("<< CYPHER\n", 1)[1].split("\nCYPHER", 1)[0]
                years = re.search(r"YEARS=\(([^)]+)\)", body)[1].split()
                months = re.search(r"MONTHS=\(([^)]+)\)", body)[1].split()
                for year in years:
                    for month in months:
                        filename = f"{year}_{month}.csv"
                        expanded = cypher.replace("${FILE}", filename)
                        change = f"${{FILE}} -> {filename}; expands the publisher's year/month loop."
                        path = f"load/{len(order) + 1:03d}.cypher"
                        files[path] = header(url, copied_at, block, change=change) + expanded
                        order.append({"file": path, "source_block": block, "heading": item["heading"], "file_substitution": filename})
                        required.update(re.findall(r"file:///([^\s\"'\)]+)", expanded))
    for number, items in sorted(queries.items()):
        path = f"queries/Q{number:02d}.cypher"
        bodies = [item["body"] for item in items]
        files[path] = "\n\n".join(header(url, copied_at, item["block"]) + item["body"] for item in items)
        if not items:
            files[path] = header(url, copied_at, "none") + "// This section publishes no Neo4j Cypher example.\n"
        query_manifest.append({"id": f"Q{number:02d}", "file": path, "title": titles[number],
                               "source_blocks": [item["block"] for item in items],
                               "gds": any(re.search(r"\bgds\.", b, re.I) for b in bodies),
                               "has_cypher": bool(items)})
    expected = counts(tables)
    files["expected_counts.json"] = json.dumps(expected, indent=2) + "\n"
    manifest = {"version": 1, "id": slug, "name": DATASETS[slug][0], "url": url, "copied_at": copied_at,
                "page_sha256": hashlib.sha256(html.encode()).hexdigest(), "load_order": order,
                "reference_scripts": references, "required_files": sorted(required), "queries": query_manifest,
                "import_mode": "published_bulk" if slug == "ldbc-snb" else "cypher"}
    manifest["artifact_sha256"] = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in files.items()}
    files["source-manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return files, manifest


def copy(slug, html):
    directory = ROOT / slug
    if directory.exists():
        raise ValueError(f"Refusing to overwrite copied source: {directory}")
    url = f"https://pgraphbenchweb.vercel.app/workloads/{DATASETS[slug][1]}-neo4j.html"
    copied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    files, manifest = artifacts(slug, html, url, copied_at)
    for name, body in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    (directory / "page.html").write_text(html)
    source = [f"# {DATASETS[slug][0]} — PropGBench Neo4j source", "", f"Source: {url}",
              f"Copied: {copied_at}", f"Page SHA-256: `{manifest['page_sha256']}`", "",
              "`page.html` is the archived publisher page. `source-manifest.json` records",
              "the exact code blocks, order, and hashes. GQL alternatives are excluded.",
              "GDS examples are retained for source completeness and must not be executed.", "", "## Input files", ""]
    source += [f"- `{name}`" for name in manifest["required_files"]]
    if slug == "ontime":
        source += ["", "The published shell loop is retained under `reference/`. Its Cypher",
                   "here-document is copied once per month; only `${FILE}` is substituted,",
                   "with every substitution recorded in that script's header."]
    if slug == "ldbc-snb":
        source += ["", "The page publishes an administrative bulk-import shell script, not a",
                   "Cypher node/edge loader. It is archived under `reference/` and is never",
                   "executed directly: it contains system-wide and destructive commands.",
                   "The user authorized adapting this published bulk importer for a separate",
                   "Neo4j 5.26 Community instance. Record every compatibility change here.",
                   "The copied schema alone does not load this dataset."]
    source += ["", "## Verification and count differences", "",
               "No database has been loaded or verified yet. Published counts are unchanged.", ""]
    (directory / "SOURCE.md").write_text("\n".join(source))
    return manifest


def audit(slug):
    directory = ROOT / slug
    manifest = json.loads((directory / "source-manifest.json").read_text())
    html = (directory / "page.html").read_text()
    files, regenerated = artifacts(slug, html, manifest["url"], manifest["copied_at"])
    for name, expected in files.items():
        if (directory / name).read_text() != expected:
            raise ValueError(f"Published-source mismatch: {slug}/{name}")
    if regenerated != manifest:
        raise ValueError(f"Published-source manifest mismatch: {slug}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("copy", "audit"))
    parser.add_argument("dataset", choices=(*DATASETS, "all"))
    parser.add_argument("--html", type=Path, help="Use a previously downloaded page for one dataset")
    args = parser.parse_args()
    for slug in DATASETS if args.dataset == "all" else (args.dataset,):
        if args.command == "audit":
            m = audit(slug)
        else:
            if args.html:
                if args.dataset == "all":
                    parser.error("--html requires one dataset")
                html = args.html.read_text()
            else:
                url = f"https://pgraphbenchweb.vercel.app/workloads/{DATASETS[slug][1]}-neo4j.html"
                with urllib.request.urlopen(url, timeout=60) as response:
                    html = response.read().decode("utf-8")
            m = copy(slug, html)
        print(slug, len(m["load_order"]), "load scripts;", len(m["queries"]), "query sections; source audit passed" if args.command == "audit" else "query sections copied")


if __name__ == "__main__":
    main()
