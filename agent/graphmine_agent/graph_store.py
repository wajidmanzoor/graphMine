from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .config import Settings
from .database import Database
from .models import FileRole, GraphMetadata, StoredFile, new_id


class UploadError(ValueError):
    pass


def _safe_name(name: str) -> str:
    base = Path(name).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    return safe[:180] or "upload"


def _external_id(value: str) -> str | int:
    value = value.strip()
    if not value:
        raise UploadError("vertex IDs must not be empty")
    try:
        parsed = int(value)
    except ValueError:
        return value
    return parsed if str(parsed) == value or value == f"+{parsed}" else value


class GraphStore:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        schema = json.loads(settings.graph_schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def ingest(
        self,
        *,
        session_id: str,
        role: FileRole,
        filename: str,
        content: bytes,
        media_type: str | None = None,
        directed: bool = False,
    ) -> StoredFile:
        self.database.get_session(session_id)
        if not content:
            raise UploadError("uploaded file is empty")
        if len(content) > self.settings.max_upload_bytes:
            raise UploadError(
                f"upload exceeds {self.settings.max_upload_bytes} byte limit"
            )

        file_id = new_id("file")
        safe_name = _safe_name(filename)
        digest = hashlib.sha256(content).hexdigest()

        canonical_graph: dict[str, Any] | None = None
        metadata: GraphMetadata | dict[str, Any] | None = None
        if role in {FileRole.graph, FileRole.query_graph, FileRole.motif}:
            canonical_graph = self._read_graph(safe_name, content, directed=directed)
            self._validate_graph(canonical_graph)
            metadata = self._metadata(file_id, canonical_graph)
        elif role == FileRole.left_partition:
            value = self._read_json(content)
            if not isinstance(value, dict) or not isinstance(
                value.get("left_partition"), list
            ):
                raise UploadError(
                    'left-partition input must be {"left_partition": [...]}'
                )
            metadata = {"item_count": len(value["left_partition"])}
        elif role == FileRole.updates:
            value = self._read_json(content)
            if not isinstance(value, dict) or not isinstance(
                value.get("updates"), list
            ):
                raise UploadError('updates input must be {"updates": [...]}')
            metadata = {"update_count": len(value["updates"])}

        directory = (
            self.settings.data_root / "sessions" / session_id / "files" / file_id
        )
        canonical_path: Path | None = None
        try:
            directory.mkdir(parents=True, exist_ok=False)
            source_path = directory / safe_name
            source_path.write_bytes(content)
            if canonical_graph is not None:
                canonical_path = directory / "graph.json"
                canonical_path.write_text(
                    json.dumps(canonical_graph, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            record = StoredFile(
                id=file_id,
                session_id=session_id,
                role=role,
                original_name=filename,
                media_type=media_type,
                source_path=str(source_path),
                canonical_path=str(canonical_path) if canonical_path else None,
                sha256=digest,
                size_bytes=len(content),
                metadata=metadata,
            )
            return self.database.add_file(record)
        except Exception:
            if directory.is_dir():
                shutil.rmtree(directory)
            raise

    @staticmethod
    def _read_json(content: bytes) -> Any:
        try:
            return json.loads(content.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise UploadError("JSON input must be UTF-8") from error
        except json.JSONDecodeError as error:
            raise UploadError(f"invalid JSON: {error}") from error

    def _read_graph(
        self, filename: str, content: bytes, *, directed: bool
    ) -> dict[str, Any]:
        if filename.lower().endswith(".json"):
            value = self._read_json(content)
            if not isinstance(value, dict):
                raise UploadError("canonical graph JSON must be an object")
            return value
        return self._edge_list_graph(filename, content, directed=directed)

    @staticmethod
    def _edge_list_graph(
        filename: str, content: bytes, *, directed: bool
    ) -> dict[str, Any]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UploadError("edge-list input must be UTF-8") from error
        rows: list[list[str]] = []
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith(("#", "%")):
                continue
            try:
                row = next(csv.reader([line])) if "," in line else line.split()
            except csv.Error as error:
                raise UploadError(
                    f"invalid edge-list row {line_number}: {error}"
                ) from error
            row = [item.strip() for item in row if item.strip()]
            if len(row) < 2 or len(row) > 4:
                raise UploadError(
                    f"edge-list row {line_number} needs source target [weight] [timestamp]"
                )
            if not rows and row[0].lower() in {"source", "src", "from"}:
                continue
            rows.append(row)
        if not rows:
            raise UploadError("edge-list input contains no edges")

        vertex_ids: dict[str | int, None] = {}
        edges: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            source = _external_id(row[0])
            target = _external_id(row[1])
            vertex_ids[source] = None
            vertex_ids[target] = None
            edge: dict[str, Any] = {"id": index, "source": source, "target": target}
            if len(row) >= 3:
                try:
                    edge["weight"] = float(row[2])
                except ValueError as error:
                    raise UploadError(
                        f"edge row {index + 1} has invalid weight"
                    ) from error
            if len(row) == 4:
                try:
                    edge["timestamp"] = int(row[3])
                except ValueError as error:
                    raise UploadError(
                        f"edge row {index + 1} has non-integer timestamp"
                    ) from error
            edges.append(edge)
        graph_name = Path(filename).stem or "uploaded-graph"
        return {
            "graph": {
                "id": graph_name,
                "directed": directed,
                "allows_self_loops": any(
                    edge["source"] == edge["target"] for edge in edges
                ),
                "allows_parallel_edges": GraphStore._has_parallel_edges(
                    edges, directed
                ),
            },
            "vertices": [{"id": vertex_id} for vertex_id in vertex_ids],
            "edges": edges,
        }

    @staticmethod
    def _has_parallel_edges(edges: list[dict[str, Any]], directed: bool) -> bool:
        seen: set[tuple[str, str]] = set()
        for edge in edges:
            source, target = repr(edge["source"]), repr(edge["target"])
            key = (source, target) if directed or source <= target else (target, source)
            if key in seen:
                return True
            seen.add(key)
        return False

    def _validate_graph(self, graph: dict[str, Any]) -> None:
        errors = sorted(
            self.validator.iter_errors(graph), key=lambda item: list(item.path)
        )
        if errors:
            details = []
            for error in errors[:20]:
                location = ".".join(str(item) for item in error.absolute_path) or "$"
                details.append(f"{location}: {error.message}")
            raise UploadError("graph schema validation failed: " + "; ".join(details))

        vertices = [item["id"] for item in graph["vertices"]]
        serialized = [json.dumps(item, sort_keys=True) for item in vertices]
        if len(serialized) != len(set(serialized)):
            raise UploadError("vertex IDs must be unique")
        vertex_set = set(serialized)
        edge_ids: set[str] = set()
        endpoint_pairs: set[tuple[str, str]] = set()
        descriptor = graph["graph"]
        timestamp_kinds: set[type[Any]] = set()
        for edge in graph["edges"]:
            edge_id = json.dumps(edge["id"], sort_keys=True)
            if edge_id in edge_ids:
                raise UploadError("edge IDs must be unique")
            edge_ids.add(edge_id)
            source = json.dumps(edge["source"], sort_keys=True)
            target = json.dumps(edge["target"], sort_keys=True)
            if source not in vertex_set or target not in vertex_set:
                raise UploadError("every edge endpoint must name a declared vertex")
            if source == target and not descriptor["allows_self_loops"]:
                raise UploadError("self-loop present while allows_self_loops is false")
            pair = (
                (source, target)
                if descriptor["directed"] or source <= target
                else (target, source)
            )
            if pair in endpoint_pairs and not descriptor["allows_parallel_edges"]:
                raise UploadError(
                    "parallel edge present while allows_parallel_edges is false"
                )
            endpoint_pairs.add(pair)
            if "weight" in edge and not math.isfinite(float(edge["weight"])):
                raise UploadError("edge weights must be finite")
            if "timestamp" in edge:
                timestamp_kinds.add(type(edge["timestamp"]))
        if len(timestamp_kinds) > 1:
            raise UploadError("all timestamps must use one representation")

    @staticmethod
    def _metadata(file_id: str, graph: dict[str, Any]) -> GraphMetadata:
        vertices = graph["vertices"]
        edges = graph["edges"]
        index = {
            json.dumps(vertex["id"], sort_keys=True): position
            for position, vertex in enumerate(vertices)
        }
        degrees = [0] * len(vertices)
        for edge in edges:
            source = index[json.dumps(edge["source"], sort_keys=True)]
            target = index[json.dumps(edge["target"], sort_keys=True)]
            degrees[source] += 1
            if source != target:
                degrees[target] += 1
        vertex_count = len(vertices)
        edge_count = len(edges)
        directed = graph["graph"]["directed"]
        possible = (
            vertex_count * (vertex_count - 1)
            if directed
            else vertex_count * (vertex_count - 1) / 2
        )
        return GraphMetadata(
            graph_id=file_id,
            name=graph["graph"]["id"],
            directed=directed,
            allows_self_loops=graph["graph"]["allows_self_loops"],
            allows_parallel_edges=graph["graph"]["allows_parallel_edges"],
            vertex_count=vertex_count,
            edge_count=edge_count,
            density=0.0 if possible == 0 else edge_count / possible,
            minimum_degree=min(degrees, default=0),
            maximum_degree=max(degrees, default=0),
            average_degree=0.0 if not degrees else sum(degrees) / len(degrees),
            isolated_vertex_count=sum(degree == 0 for degree in degrees),
            has_weights=any("weight" in edge for edge in edges),
            has_timestamps=any("timestamp" in edge for edge in edges),
        )

    def execution_path(self, file_id: str, session_id: str) -> Path:
        record = self.database.get_file(file_id)
        if record.session_id != session_id:
            raise UploadError("file does not belong to this session")
        value = record.canonical_path or record.source_path
        path = Path(value).resolve()
        allowed_root = (self.settings.data_root / "sessions" / session_id).resolve()
        if path != allowed_root and allowed_root not in path.parents:
            raise UploadError("stored file escapes its session workspace")
        if not path.is_file():
            raise UploadError(f"stored file is missing: {file_id}")
        return path

    def graph_preview(
        self,
        file_id: str,
        *,
        vertex_limit: int = 500,
        edge_limit: int = 2_000,
    ) -> dict[str, Any]:
        if not 1 <= vertex_limit <= 2_000 or not 1 <= edge_limit <= 10_000:
            raise UploadError("graph preview limits are outside the allowed range")
        record = self.database.get_file(file_id)
        if record.role not in {FileRole.graph, FileRole.query_graph, FileRole.motif}:
            raise UploadError("this file role does not contain a graph")
        path = self.execution_path(file_id, record.session_id)
        graph = self._read_json(path.read_bytes())
        self._validate_graph(graph)
        vertices = graph["vertices"][:vertex_limit]
        vertex_ids = {json.dumps(vertex["id"], sort_keys=True) for vertex in vertices}
        edges = [
            edge
            for edge in graph["edges"]
            if json.dumps(edge["source"], sort_keys=True) in vertex_ids
            and json.dumps(edge["target"], sort_keys=True) in vertex_ids
        ][:edge_limit]
        return {
            "graph": graph["graph"],
            "vertex_count": len(graph["vertices"]),
            "edge_count": len(graph["edges"]),
            "vertices": vertices,
            "edges": edges,
            "vertices_truncated": len(vertices) < len(graph["vertices"]),
            "edges_truncated": len(edges) < len(graph["edges"]),
        }
