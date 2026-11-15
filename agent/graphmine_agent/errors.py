"""Service errors shared by routes, jobs and transports."""

class AnalyticsError(ValueError):
    def __init__(self, message, code="invalid_workflow", status=422, *, details=None):
        super().__init__(message)
        self.code, self.status = code, status
        self.details = details


