#!/usr/bin/env python3
"""Replay saved canonical/manifest/adjacency validation graphs through byte goldens.

Discovery retains source aliases and hashes; identical graph documents run once.
Malformed canonical inputs remain in the corpus for matching rejection checks.
"""
import argparse
import gzip
import hashlib
import json
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(name, n, edges, directed=False):
    return {"graph": {"id": name, "directed": directed, "allows_self_loops": True,
                      "allows_parallel_edges": True},
            "vertices": [{"id": v} for v in range(n)],
            "edges": [{"id": i, "source": e[0], "target": e[1],
                       **({"weight": e[2]} if len(e) > 2 else {})}
                      for i, e in enumerate(edges)]}


def discover():
    for base in (ROOT / "validation", ROOT / "library/examples/data"):
        for path in sorted(base.rglob("*.json")):
            if "graph_views" in path.parts:
                continue
            raw = path.read_bytes()
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            source = str(path.relative_to(ROOT))
            source_sha = hashlib.sha256(raw).hexdigest()

            def walk(value, pointer):
                if isinstance(value, dict):
                    if isinstance(value.get("graph"), dict) and isinstance(value.get("vertices"), list) and isinstance(value.get("edges"), list):
                        yield pointer, value
                        return
                    edges = value.get("edges")
                    if isinstance(value.get("n"), int) and isinstance(edges, list) and all(isinstance(e, list) and len(e) in (2, 3) for e in edges):
                        yield pointer, canonical(str(value.get("id", value.get("name", pointer))), value["n"], edges, value.get("directed", False))
                        return
                    for key, item in value.items():
                        yield from walk(item, pointer + "/" + str(key))
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        yield from walk(item, pointer + "/" + str(i))

            for pointer, graph in walk(data, ""):
                yield source + "#" + pointer, source_sha, graph
    for path in sorted((ROOT / "validation/algorithm_repairs/cds/fixtures").glob("*.adj")):
        raw = path.read_bytes()
        rows = raw.decode().splitlines()
        n, m = map(int, rows[0].split())
        edges = [(int(row.split()[0]), int(v)) for row in rows[1:] if row.strip()
                 for v in row.split()[1:] if int(row.split()[0]) < int(v)]
        assert len(edges) == m, path
        yield str(path.relative_to(ROOT)), hashlib.sha256(raw).hexdigest(), canonical(path.stem, n, edges)


def supplementary(scale):
    for path in sorted((ROOT / "validation/algorithm_repairs/mbe_gpu/fixtures").glob("*.adj")):
        raw = path.read_bytes()
        rows = [list(map(int, line.split())) for line in raw.decode().splitlines()]
        left = max((u for row in rows for u in row), default=-1) + 1
        edges = [(u, left + v) for v, row in enumerate(rows) for u in row]
        yield str(path.relative_to(ROOT)), hashlib.sha256(raw).hexdigest(), canonical(path.stem, left + len(rows), edges)
    for path in sorted((ROOT / "validation/gpu_correctness_expansion/datasets").rglob("*.egr")):
        raw = path.read_bytes()
        data = struct.unpack("<" + "i" * (len(raw)//4), raw)
        n, m = data[:2]
        offsets, dst = data[2:n+3], data[n+3:n+3+m]
        weights = data[n+3+m:]
        assert len(weights) in (0, m) and offsets[-1] == m, path
        edges = [(u, dst[i], *([weights[i]] if weights else [])) for u in range(n)
                 for i in range(offsets[u], offsets[u+1])]
        yield str(path.relative_to(ROOT)), hashlib.sha256(raw).hexdigest(), canonical(path.stem, n, edges, True)
    if scale is None:
        return
    yield from published(scale)
    snap = scale / "ca-CondMat.txt.gz"
    edges = set()
    with gzip.open(snap, "rt") as stream:
        for line in stream:
            if not line.startswith("#"):
                edges.add(tuple(sorted(map(int, line.split()))))
    vertices = sorted({v for edge in edges for v in edge})
    assert len(vertices) == 23133 and len(edges) == 93497
    document = canonical("snap-ca-CondMat", 0, sorted(edges))
    document["vertices"] = [{"id": v} for v in vertices]
    yield "scale/snap-ca-CondMat", hashlib.sha256(snap.read_bytes()).hexdigest(), document
    # Exact generator/seed from tools/validate_native_scale.py.
    rng, n = random.Random(30171011), 100000
    pairs = {tuple(sorted((u, (u + 1) % n))) for u in range(n)}
    while len(pairs) < 5*n:
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            pairs.add(tuple(sorted((u, v))))
    document = canonical(f"synthetic-{n}", n, [(u, v, 1 + (u*13 + v*7) % 31) for u, v in sorted(pairs)])
    yield "scale/synthetic-100000", hashlib.sha256((ROOT / "tools/validate_native_scale.py").read_bytes()).hexdigest(), document


def published(scale):
    for properties_path in sorted(scale.rglob("*.properties")):
        directory, name = properties_path.parent, properties_path.stem
        files = [directory / (name + suffix) for suffix in (".properties", ".v", ".e")]
        properties = dict(line.split("=", 1) for line in files[0].read_text().splitlines()
                          if "=" in line and not line.lstrip().startswith("#"))
        properties = {key.strip(): value.strip() for key, value in properties.items()}
        vertices = [int(row.split()[0]) for row in files[1].read_text().splitlines() if row.strip()]
        edges = []
        for row in files[2].read_text().splitlines():
            values = row.split()
            if values:
                edges.append((int(values[0]), int(values[1]), *([float(values[2])] if len(values) > 2 else [])))
        document = canonical(name, 0, edges, properties["graph." + name + ".directed"] == "true")
        document["vertices"] = [{"id": v} for v in vertices]
        yield "scale/" + name, hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest(), document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supplementary", action="store_true")
    parser.add_argument("--published-only", action="store_true")
    parser.add_argument("--scale", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    seen = {}
    inputs = published(args.scale) if args.published_only else supplementary(args.scale) if args.supplementary else discover()
    with gzip.open(args.output / "corpus.jsonl.gz", "wt") as output:
        for source, source_sha, graph in inputs:
            raw = json.dumps(graph, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(raw.encode()).hexdigest()
            alias = {"source": source, "source_sha256": source_sha}
            if digest in seen:
                seen[digest]["sources"].append(alias)
                continue
            seen[digest] = {"dataset": source, "graph_sha256": digest, "sources": [alias]}
            output.write(json.dumps({"dataset": source, "graph": graph}, separators=(",", ":")) + "\n")
    (args.output / "corpus-index.json").write_text(json.dumps(list(seen.values()), indent=2) + "\n")
    print(f"{len(seen)} unique documents, {sum(len(row['sources']) for row in seen.values())} source cases")


if __name__ == "__main__":
    main()
