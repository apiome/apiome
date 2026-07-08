"""Cataloger notes validation (V2-MCP-36.3 / MCAT-22.3, #4666).

Human notes on MCP endpoints are tenant-scoped commentary kept separate from server-reported
discovery data. This module normalizes and bounds note bodies before persistence.
"""

from __future__ import annotations

MAX_ENDPOINT_NOTE_CHARS = 10_000


class EndpointNoteValidationError(ValueError):
    """Raised when a note body fails validation."""


def normalize_endpoint_note_body(body: str | None) -> str:
    """Strip and validate a cataloger note body.

    Args:
        body: Raw note text from the API.

    Returns:
        The trimmed note body.

    Raises:
        EndpointNoteValidationError: When empty or over the character limit.
    """
    text = (body or "").strip()
    if not text:
        raise EndpointNoteValidationError("Note body is required")
    if len(text) > MAX_ENDPOINT_NOTE_CHARS:
        raise EndpointNoteValidationError(
            f"Note body exceeds maximum length ({MAX_ENDPOINT_NOTE_CHARS} characters)"
        )
    return text


__all__ = ["EndpointNoteValidationError", "MAX_ENDPOINT_NOTE_CHARS", "normalize_endpoint_note_body"]
