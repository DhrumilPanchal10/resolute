class ResoluteError(Exception):
    """Base error for all resolute errors."""


class OfflineFixtureError(ResoluteError):
    """Raised when OFFLINE=1 and no fixture exists for the requested LLM call."""

    def __init__(self, key: str, path: str) -> None:
        super().__init__(
            f"OFFLINE=1 but no fixture found for key {key!r}. "
            f"Expected file: {path}. "
            "Record a fixture by running with OFFLINE=0 first."
        )
        self.key = key
        self.path = path


class BudgetExceeded(ResoluteError):
    """Raised when a run exceeds its configured USD budget."""

    def __init__(self, spent: float, limit: float) -> None:
        super().__init__(f"Budget exceeded: spent ${spent:.4f}, limit ${limit:.4f}")
        self.spent = spent
        self.limit = limit
