"""Read-only catalog of local benchmark downloads and their published schemas."""

import json
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse

from .database import RecordNotFound

DATASETS = {
    "yelp": ("Yelp", "yelp"),
    "movielens-32m": ("MovieLens 32M", "ml32m"),
    "movielens-genome": ("MovieLens Tag Genome", "mlgenome"),
    "amazon": ("Amazon", "amazon"),
    "stackoverflow": ("Stack Overflow", "stackoverflow"),
    "ontime": ("OnTime", "ontime"),
    "fars": ("FARS", "fars"),
    "ldbc-snb": ("LDBC SNB", "snb"),
}


def directory(settings, identifier):
    root = settings.benchmark_datasets_root
    if not root or identifier not in DATASETS:
        raise RecordNotFound("Benchmark dataset not found")
    path = root / identifier
    if not path.is_dir():
        raise RecordNotFound("Benchmark dataset not found")
    return path


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def describe(settings, identifier):
    path = directory(settings, identifier)
    name, page = DATASETS[identifier]
    manifest = read_json(path / "schemas" / "manifest.json", {})
    schemas = []
    for schema in manifest.get("schemas", []):
        filename = schema.get("file", "")
        if Path(filename).name != filename or not (path / "schemas" / filename).is_file():
            continue
        schemas.append({
            **schema,
            "image_url": f"/api/benchmark-datasets/{identifier}/schemas/{filename}",
            "definition_url": f"/api/benchmark-datasets/{identifier}/schemas/{schema['platform']}-loading-and-queries.txt"
            if (path / "schemas" / f"{schema['platform']}-loading-and-queries.txt").is_file() else None,
        })
    files = []
    for folder in [path, path / "raw"]:
        for receipt in sorted(folder.glob("*.verified.json")):
            data = read_json(receipt, {})
            filename = receipt.name.removesuffix(".verified.json")
            target = folder / filename
            if target.is_file() and target.stat().st_size == data.get("size_bytes"):
                files.append({"name": filename, "size_bytes": data["size_bytes"], "sha256": data.get("sha256")})
    metadata = read_json(path / "dataverse-metadata.json", {})
    expected = len(metadata.get("data", {}).get("latestVersion", {}).get("files", []))
    if identifier == "ldbc-snb":
        expected = 2
    complete = bool(expected and len(files) >= expected)
    return {
        "id": identifier, "name": name, "source_url": f"https://pgraphbenchweb.vercel.app/datasets/{page}.html",
        "schemas": schemas, "files": files, "downloaded_files": len(files),
        "expected_files": expected, "size_bytes": sum(item["size_bytes"] for item in files),
        "status": "downloaded" if complete else "downloading" if expected else "schema_only",
        "storage_path": str(path),
    }


def register_benchmark_routes(router):
    @router.get("/benchmark-datasets")
    def catalog(request: Request):
        settings = request.app.state.runtime.settings
        if not settings.benchmark_datasets_root:
            return []
        return [
            describe(settings, identifier) for identifier in DATASETS
            if (settings.benchmark_datasets_root / identifier).is_dir()
        ]

    @router.get("/benchmark-datasets/{identifier}/schemas/{filename}")
    def schema(identifier: str, filename: str, request: Request):
        path = directory(request.app.state.runtime.settings, identifier) / "schemas"
        manifest = read_json(path / "manifest.json", {})
        permitted = {item["file"] for item in manifest.get("schemas", [])}
        permitted.update(f"{item['platform']}-loading-and-queries.txt" for item in manifest.get("schemas", []))
        if filename not in permitted or Path(filename).name != filename:
            raise RecordNotFound("Dataset schema not found")
        asset = path / filename
        if not asset.is_file() or asset.resolve().parent != path.resolve():
            raise RecordNotFound("Dataset schema not found")
        if asset.suffix == ".txt":
            return FileResponse(asset, media_type="text/plain", filename=filename)
        types = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif"}
        if asset.suffix not in types:
            raise RecordNotFound("Dataset schema not found")
        return FileResponse(asset, media_type=types[asset.suffix])
