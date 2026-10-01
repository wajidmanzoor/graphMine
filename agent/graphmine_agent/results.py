from __future__ import annotations

from collections import Counter
from typing import Any

from .catalog import Catalog


class ResultValidationError(ValueError):
    pass


def _has_path(value: Any, path: str) -> bool:
    current = value
    for component in path.split("."):
        if component.endswith("[]"):
            name = component[:-2]
            if not isinstance(current, dict) or name not in current:
                return False
            array = current[name]
            if not isinstance(array, list):
                return False
            current = array[0] if array else {}
        else:
            if not isinstance(current, dict) or component not in current:
                return False
            current = current[component]
    return True


def validate_result(
    catalog: Catalog, operation_id: str, payload: dict[str, Any]
) -> None:
    if not isinstance(payload.get("ok"), bool):
        raise ResultValidationError("GraphMine result is missing boolean field 'ok'")
    if not payload["ok"]:
        error = payload.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("message"), str):
            raise ResultValidationError("failed result is missing a structured error")
        return
    for field in ("provenance", "warnings", "output"):
        if field not in payload:
            raise ResultValidationError(f"successful result is missing {field}")
    output = payload["output"]
    if not isinstance(output, dict):
        raise ResultValidationError("successful result output must be an object")
    contract = catalog.operation(operation_id)
    missing = [
        path
        for path in contract.manifest["required_outputs"]
        if not _has_path(output, path)
    ]
    if missing:
        raise ResultValidationError(
            f"result for {operation_id} is missing required outputs: {missing}"
        )


def summarize_result(payload: dict[str, Any], item_limit: int = 50) -> dict[str, Any]:
    """Create a bounded, faithful LLM context without losing aggregate counts."""

    def visit(value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return {"_summary": "maximum summary depth reached"}
        if isinstance(value, dict):
            return {str(key): visit(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            summary: dict[str, Any] = {
                "_type": "array",
                "count": len(value),
                "items": [visit(item, depth + 1) for item in value[:item_limit]],
                "truncated": len(value) > item_limit,
            }
            scalar_values = [
                item for item in value if isinstance(item, (str, int, float, bool))
            ]
            if scalar_values and len(scalar_values) == len(value):
                summary["frequent_values"] = [
                    {"value": item, "count": count}
                    for item, count in Counter(scalar_values).most_common(10)
                ]
            return summary
        if isinstance(value, str) and len(value) > 2_000:
            return value[:2_000] + "…"
        return value

    return visit(payload)


def query_path(payload: Any, path: str, *, offset: int = 0, limit: int = 100) -> Any:
    """Read an allowlisted dot/index path used by analyst result tools."""

    if offset < 0 or limit < 1 or limit > 10_000:
        raise ValueError("offset/limit are outside the allowed range")
    current = payload
    if path:
        for component in path.split("."):
            if component.startswith("_") or not component:
                raise ValueError("invalid result path")
            if isinstance(current, dict):
                if component not in current:
                    raise KeyError(path)
                current = current[component]
            elif isinstance(current, list) and component.isdigit():
                current = current[int(component)]
            else:
                raise KeyError(path)
    if isinstance(current, list):
        return {
            "path": path,
            "total": len(current),
            "offset": offset,
            "items": current[offset : offset + limit],
        }
    return {"path": path, "value": current}
