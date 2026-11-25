"""Present saved runnable contracts without rewriting their immutable artifacts."""

from .errors import AnalyticsError


def _rename(value, old, new):
    if not isinstance(value, dict) or old not in value:
        return value
    if new in value and value[new] != value[old]:
        raise AnalyticsError("Saved workflow has conflicting problem identifiers.", "data_integrity", 409)
    result = dict(value)
    result[new] = result.pop(old)
    return result


def _replace(value, key, transform):
    if not isinstance(value, dict) or key not in value:
        return value
    changed = transform(value[key])
    return value if changed is value[key] else {**value, key: changed}


def saved_plan(plan):
    def steps(values):
        if not isinstance(values, list):
            return values
        changed = [_rename(step, "operation", "problem") for step in values]
        return values if all(a is b for a, b in zip(values, changed)) else changed
    return _replace(plan, "steps", steps)


def saved_workflow(record):
    record = _replace(record, "plan", saved_plan)
    return _replace(record, "validation", lambda value: _replace(value, "plan", saved_plan))


def saved_result(saved):
    """Rename envelope fields only; user attributes and port values are opaque.

    Approval hashes, result hashes and cache keys describe the original saved
    artifacts and remain unchanged. Re-execution still requires validation
    against the current native implementation.
    """
    def native(value):
        value = _rename(value, "operation", "problem")
        return _rename(value, "problem_id", "topic_id")

    def step(value):
        return _replace(value, "result", native)

    def steps(values):
        if not isinstance(values, dict):
            return values
        changed = {name: step(value) for name, value in values.items()}
        return values if all(changed[name] is value for name, value in values.items()) else changed

    saved = saved_workflow(saved)
    return _replace(saved, "steps", steps) if isinstance(saved, dict) and "steps" in saved else step(saved)
