"""Stand-ins for :func:`app.compatibility_engine.read_revision_openapi` in route tests (COA-5.6, #7082).

Route tests patch the cached read with plain OpenAPI dicts. The reads these helpers return carry no
digest, so a route never takes the equal-digest short cut with them and classifies as it always did.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator

from app.compatibility_engine import CACHE_MISS, RevisionOpenApi


def as_read(spec: Dict[str, Any], *, sha256: str | None = None, cache: str = CACHE_MISS) -> RevisionOpenApi:
    """Wrap one OpenAPI document as a read.

    Args:
        spec: The document.
        sha256: Its rendered digest, or ``None`` for "not from the cache".
        cache: ``hit`` or ``miss``.

    Returns:
        The read.
    """
    return RevisionOpenApi(spec=spec, sha256=sha256, cache=cache)


def reads(*specs: Dict[str, Any]) -> Callable[..., RevisionOpenApi]:
    """A ``side_effect`` that returns the documents in order, one per call (like a list side effect)."""
    queue: Iterator[Dict[str, Any]] = iter(specs)
    return lambda *_args, **_kwargs: as_read(next(queue))


def always(spec: Dict[str, Any]) -> Callable[..., RevisionOpenApi]:
    """A ``side_effect`` that returns the same document on every call."""
    return lambda *_args, **_kwargs: as_read(spec)
