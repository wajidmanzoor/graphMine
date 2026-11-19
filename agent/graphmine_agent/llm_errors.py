"""Shared errors at the model transport and power boundaries."""


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """The model can be retried after its service becomes available."""


class LLMPowerBusy(LLMUnavailable):
    """Sleeping would interrupt another request or evaluation."""
