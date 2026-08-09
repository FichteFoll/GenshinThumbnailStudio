"""The single exception type raised by the `enka` package."""

from __future__ import annotations


class EnkaError(RuntimeError):
    """Anything that went wrong talking to Enka, with a message fit for a dialog."""
