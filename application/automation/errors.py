"""Stable public CLI error categories and exit codes."""

SUCCESS = 0
VALIDATION_ERROR = 2
EXECUTION_ERROR = 3
CANCELLED = 130
TIMED_OUT = 124


class ValidationError(ValueError):
    """An invalid automation request, before successful execution."""
