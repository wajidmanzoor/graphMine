"""Conservative allocation admission; no auxiliary learned memory model."""
from ..analytics_scheduler import estimate_memory


def effective_rows(rows):
    records = {r["run_id"]: r for r in rows}
    superseded = {r["supersedes"] for r in records.values() if r.get("supersedes")}
    return [r for key, r in records.items() if key not in superseded]


def estimate_candidate_memory(problem, backend, features, parameters, hardware, *, output_estimate,
                              implementation, data_dir):
    value = estimate_memory({"steps": [{"budget": {"max_output_items": output_estimate}}]},
                            features["input_bytes"])
    return value, "conservative_allocation"
