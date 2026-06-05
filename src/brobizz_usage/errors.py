"""Shared exceptions for Brobizz usage operations."""


class BrobizzError(RuntimeError):
    """Raised when the Brobizz API returns an unrecoverable error."""


class BrobizzAuthError(BrobizzError):
    """Raised when OAuth login or refresh cannot produce usable tokens."""

