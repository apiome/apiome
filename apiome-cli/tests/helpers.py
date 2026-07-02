"""Test utilities (importable from the tests package root on sys.path)."""

from __future__ import annotations

import re

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove terminal colour codes so help text assertions work in CI."""
    return ANSI_ESCAPE.sub("", text)
