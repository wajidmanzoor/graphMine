class GraphMineError(ValueError):
    """An input, capability, or computation failure with a stable error code."""

    code = "invalid_input"


class UnsupportedProblem(GraphMineError):
    code = "unsupported_problem"


class BackendUnavailable(GraphMineError):
    code = "backend_unavailable"


class ResourceLimit(GraphMineError):
    code = "resource_limit"


class ConvergenceError(GraphMineError):
    code = "not_converged"
