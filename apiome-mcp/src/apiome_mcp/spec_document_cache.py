"""Process-wide LRU of built OpenAPI documents for the spec tools — DBP-1.22 (#7205).

Six tools (``spec.get_openapi``, ``spec.export_yaml``, ``spec.list_operations``,
``spec.list_components``, ``spec.describe_operation``, ``spec.describe_component``) build a
revision's OpenAPI document, and an agent typically calls several of them for the same spec. The
document of an unchanged revision is the same every time, so it is built once and kept.

* **Key.** ``(part, revision id, freshness)``. ``freshness`` is everything the document is
  generated from that the caller's resolve query returns: the revision's ``updated_at`` and
  ``content_stamp`` (bumped by any write to the revision's rows) and the tenant slug, project slug,
  version label and project description. A changed revision therefore has a new key; the old entry
  is never served again and ages out.
* **Who may read.** The cache is consulted only after the resolve query has authorized the caller
  for the revision on this call, so a cached document never widens access.
* **Bound.** ``openapi_document_cache_bytes`` (default 64 MiB; ``0`` turns the cache off), counted
  as the compact-JSON size of the cached values. Least recently used entries go first; a value
  larger than the whole budget is not kept.
* **Sharing.** Callers get the cached object itself, not a copy: they must not mutate it.

Used from the event loop only (no locking needed).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

from apiome_mcp.settings import setting_or_default

__all__ = ["DEFAULT_DOCUMENT_CACHE_BYTES", "DOCUMENT_CACHE", "SpecDocumentCache", "compact_json_size"]

#: Budget used when settings cannot be loaded (tests, tooling); the setting's default.
DEFAULT_DOCUMENT_CACHE_BYTES = 64 * 1024 * 1024


def compact_json_size(value: Any) -> int:
    """UTF-8 size of ``value`` as compact JSON — what ``spec.get_openapi`` caps and the cache counts.

    Args:
        value: A JSON-serializable value.

    Returns:
        The size in bytes.
    """
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class SpecDocumentCache:
    """Size-bounded LRU of ``key → (value, size)``."""

    def __init__(self, *, max_bytes: Callable[[], float] | None = None) -> None:
        """Create an empty cache.

        Args:
            max_bytes: Returns the current budget (default: the ``openapi_document_cache_bytes``
                setting, read on every call so an operator change applies at once).
        """
        self._max_bytes = max_bytes or (
            lambda: setting_or_default("openapi_document_cache_bytes", DEFAULT_DOCUMENT_CACHE_BYTES)
        )
        self._entries: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self._bytes = 0

    def get(self, key: Hashable) -> tuple[Any, int] | None:
        """The cached ``(value, size)`` for ``key``, or ``None`` (missing, or the cache is off)."""
        if float(self._max_bytes()) <= 0:
            return None
        hit = self._entries.get(key)
        if hit is not None:
            self._entries.move_to_end(key)
        return hit

    def put(self, key: Hashable, value: Any, size: int) -> None:
        """Keep ``value`` under ``key``, dropping least recently used entries to stay in budget.

        Args:
            key: The cache key.
            value: The built value; shared with every later reader.
            size: Its :func:`compact_json_size`.
        """
        budget = int(self._max_bytes())
        self._drop(key)
        if budget <= 0 or size > budget:
            return
        self._entries[key] = (value, size)
        self._bytes += size
        while self._bytes > budget:
            _, (_, dropped) = self._entries.popitem(last=False)
            self._bytes -= dropped

    def _drop(self, key: Hashable) -> None:
        """Remove ``key`` if present."""
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= old[1]

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()
        self._bytes = 0

    @property
    def size_bytes(self) -> int:
        """Total size of the cached values."""
        return self._bytes

    def __len__(self) -> int:
        """Entries held."""
        return len(self._entries)


#: The spec tools' shared cache.
DOCUMENT_CACHE = SpecDocumentCache()
