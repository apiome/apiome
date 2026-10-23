"""Shared pieces of the ``mainframe-misc`` import family — FMT-11.3 (#5484).

FMT-11.3 adds two mainframe sub-formats that describe data without being a programming language:

* **VSAM cluster definitions** (:mod:`app.vsam_idcams_parser`) — IDCAMS ``DEFINE CLUSTER`` / ``AIX``
  / ``PATH`` commands, or the ``LISTCAT`` listing of an existing cluster;
* **CICS BMS maps** (:mod:`app.cics_bms_parser`) — ``DFHMSD`` / ``DFHMDI`` / ``DFHMDF`` assembler
  macros, and the symbolic-map copybook BMS generates from them.

Each sub-format is registered as its own adapter (``vsam-idcams``, ``cics-bms``) so that each one
refuses the other's text as ``FORMAT_MISMATCH``; both are built from the modules of this family and
both normalize onto the ``data_schema`` paradigm. This module holds what the two readers share: the
error type that carries an intake taxonomy code, the encoding check, and identifier helpers.
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "FAMILY_KEY",
    "MainframeParseError",
    "check_encoding",
    "sanitize_identifier",
    "where",
]

#: The family name both sub-formats record as their ``family`` in the projection record.
FAMILY_KEY = "mainframe-misc"

#: Characters a text decode leaves behind when the upload was not UTF-8 (NUL from UTF-16, U+FFFD
#: from an invalid byte).
_ENCODING_FAULT_MARKERS = ("\x00", "�")


class MainframeParseError(Exception):
    """A VSAM or BMS source could not be read.

    Attributes:
        code: The intake taxonomy code (:mod:`app.intake_error_taxonomy`) the failure belongs to —
            ``INPUT_MALFORMED``, ``INPUT_TRUNCATED``, ``INPUT_SEMANTIC_INVALID``,
            ``INPUT_REFERENCE_UNRESOLVED``, ``INPUT_ENCODING_INVALID``, ``INPUT_EMPTY`` or
            ``FORMAT_MISMATCH``.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def where(path: Optional[str]) -> str:
    """Render `` in <path>`` for an error message, or nothing when the path is unknown."""
    return f" in {path}" if path else ""


def check_encoding(text: str, path: Optional[str], *, what: str) -> None:
    """Refuse text that was decoded from a non-UTF-8 upload.

    Mainframe sources are EBCDIC on the host; an upload is expected to have been transferred as
    text (ASCII / UTF-8). A UTF-16 file decoded as UTF-8 shows NULs, an invalid byte shows U+FFFD,
    and either may start with a byte-order mark.

    Args:
        text: The decoded file text.
        path: The file's path, for the message.
        what: What the file is (``"IDCAMS input"``, ``"BMS source"``), for the message.

    Raises:
        MainframeParseError: ``INPUT_ENCODING_INVALID`` when a fault marker is present.
    """
    if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
        raise MainframeParseError(
            f"The {what}{where(path)} is not UTF-8 text (NULs, replacement characters or a "
            "byte-order mark); transfer the member as text (EBCDIC → ASCII), not as a UTF-16 or "
            "binary file",
            code="INPUT_ENCODING_INVALID",
        )


def sanitize_identifier(name: str) -> str:
    """Turn a dataset or member name into a type-name-safe identifier.

    ``EXAMPLE.CUSTOMER.KSDS`` → ``EXAMPLE_CUSTOMER_KSDS``. Letters, digits and underscores are
    kept; every other run of characters becomes one underscore.

    Args:
        name: The source name.

    Returns:
        The identifier (``UNNAMED`` when nothing usable remains).
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    return cleaned or "UNNAMED"
