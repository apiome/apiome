"""stderr progress feedback for long-running CLI operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.status import Status


@contextmanager
def import_progress(
    *,
    enabled: bool = True,
    initial_message: str = "Importing…",
) -> Iterator[Status | None]:
    """Show a Rich spinner on stderr while an import job is polled.

    Args:
        enabled: When False, yield None and do not write to stderr.
        initial_message: First status line shown when progress is enabled.

    Yields:
        A Rich ``Status`` instance to update, or None when progress is disabled.
    """
    if not enabled:
        yield None
        return

    console = Console(stderr=True)
    with console.status(initial_message, spinner="dots") as status:
        yield status
