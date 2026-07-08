"""Catalog inventory export — tenant-scoped CSV / JSON of every cataloged endpoint (V2-MCP-33.2 / MCAT-19.2, #4651).

Analysts want the whole catalog as *data* — a spreadsheet or a notebook — not the browse UI. This
module turns each enriched ``apiome.mcp_endpoints`` row (endpoint + its current snapshot's
score/grade and per-kind capability tallies) into a flat inventory record and serializes a stream of
those records to **CSV** or **JSON**.

Design rules:

* **Pure and streaming.** Every function here is a pure transform over an *iterable* of DB rows and
  yields output incrementally, so the route can page the catalog and stream the body without ever
  materializing the whole tenant's catalog in memory. Rendering is deterministic — the same rows
  always produce byte-identical output — so it is trivially testable without a database.
* **Correct CSV.** Row serialization goes through the stdlib :mod:`csv` writer, so a value containing
  a comma, a quote, or a newline is quoted/escaped per RFC 4180 rather than corrupting the columns.
* **No secret ever emitted.** Only the endpoint's *host* is exported (via
  :func:`urllib.parse.urlparse().hostname`, which strips any ``user:pass@`` userinfo and the port);
  the stored ``endpoint_url`` — which may embed a credential — never reaches the output.

The public surface is :data:`INVENTORY_COLUMNS` (the ordered column contract), :func:`inventory_record`
(row → flat record), and the two streaming serializers :func:`stream_csv` / :func:`stream_json`.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple
from urllib.parse import urlparse

#: The ordered export column contract: ``(key, header)`` per column. The key indexes the record
#: :func:`inventory_record` produces; the header is the CSV column title (and documents the JSON
#: field). Kept as one list so CSV and JSON stay in lock-step and a column is added in exactly one
#: place. Covers every column the ticket names — name, host, transport, category, visibility,
#: current grade/score, capability counts, last discovery status/time, health — plus the endpoint
#: ``id`` (so an analyst can join the export back to other exports) and a ``capability_count`` total.
INVENTORY_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("id", "id"),
    ("name", "name"),
    ("host", "host"),
    ("transport", "transport"),
    ("category", "category"),
    ("visibility", "visibility"),
    ("published", "published"),
    ("grade", "grade"),
    ("score", "score"),
    ("tool_count", "tools"),
    ("resource_count", "resources"),
    ("resource_template_count", "resource_templates"),
    ("prompt_count", "prompts"),
    ("capability_count", "capabilities"),
    ("last_discovery_status", "last_discovery_status"),
    ("last_discovered_at", "last_discovered_at"),
    ("health", "health"),
    # Provenance (V2-MCP-34.5): how the endpoint entered the catalog, and what enqueued
    # the run that produced its current snapshot ("unrecorded" when the snapshot predates
    # provenance tracking; empty when never discovered).
    ("added_via", "added_via"),
    ("current_version_origin", "current_version_origin"),
)

#: The ordered record keys (derived once from the column contract).
_RECORD_KEYS: Tuple[str, ...] = tuple(key for key, _ in INVENTORY_COLUMNS)

#: The ordered CSV header row (derived once from the column contract).
_CSV_HEADER: Tuple[str, ...] = tuple(header for _, header in INVENTORY_COLUMNS)


def _host(endpoint_url: Any) -> Optional[str]:
    """Extract the bare host from a stored endpoint URL, never a credential.

    Uses :func:`urllib.parse.urlparse().hostname`, which returns the lower-cased host with any
    ``user:pass@`` userinfo and ``:port`` stripped — so a credential embedded in the URL (or the
    port) can never leak into the export. A malformed URL, or a hostless target (e.g. a stdio
    command), simply yields ``None`` rather than raising.

    Args:
        endpoint_url: The endpoint's stored URL (or command), possibly ``None``.

    Returns:
        The host, or ``None`` when there is none to extract.
    """
    if not endpoint_url:
        return None
    try:
        return urlparse(str(endpoint_url)).hostname or None
    except ValueError:
        # A URL that urlparse cannot decompose (e.g. an invalid IPv6 literal) has no host to export.
        return None


def _isoformat(value: Any) -> Optional[str]:
    """Normalize a timestamp column to an ISO-8601 string (or ``None``)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def derive_health(row: Mapping[str, Any]) -> str:
    """Fold an endpoint's live operational state into one compact health label.

    A single, human-readable signal for the inventory ``health`` column, derived from the columns
    the export query already selects. Precedence is by how actionable the state is — a quarantined
    endpoint reads ``"quarantined"`` even if it is also failing, because quarantine is the state an
    operator acts on first:

    * ``"quarantined"`` — discovery has been suspended after repeated failures (``quarantined_at``).
    * ``"disabled"`` — the tenant turned the endpoint off (``enabled`` is false).
    * ``"undiscovered"`` — never successfully discovered (no ``current_version_id`` / discovery time).
    * ``"failing"`` — discovered before, but the last attempts are failing (``consecutive_failures``).
    * ``"healthy"`` — enabled, discovered, and the last discovery succeeded.

    Args:
        row: The enriched endpoint row (quarantine, enabled, discovery, and failure columns).

    Returns:
        One of the five health labels above.
    """
    if row.get("quarantined_at") is not None:
        return "quarantined"
    if not bool(row.get("enabled", True)):
        return "disabled"
    if row.get("current_version_id") is None or row.get("last_discovered_at") is None:
        return "undiscovered"
    if int(row.get("consecutive_failures") or 0) > 0:
        return "failing"
    return "healthy"


def _int_or_none(value: Any) -> Optional[int]:
    """Coerce a numeric column to ``int``; ``None`` stays ``None`` (an explicit gap, not a zero)."""
    return int(value) if value is not None else None


def _current_version_origin(row: Mapping[str, Any]) -> Optional[str]:
    """Provenance of the endpoint's current snapshot for the export (V2-MCP-34.5).

    The current version's ``discovery_trigger`` (``manual`` / ``sweep`` / ``registry``);
    ``"unrecorded"`` when a snapshot exists but predates provenance tracking — deliberately
    never presented as any concrete origin — and ``None`` when never discovered.
    """
    if row.get("current_version_id") is None:
        return None
    trigger = row.get("discovery_trigger")
    return str(trigger) if trigger is not None else "unrecorded"


def inventory_record(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one enriched endpoint row onto the flat, typed inventory record (MCAT-19.2).

    The single row → record mapping both serializers share. Values stay natively typed (ints for
    counts/score, a bool for ``published``, ``None`` for genuine gaps) so the JSON output is
    faithful; the CSV serializer coerces them to text at the edge. Only the *host* is derived from
    the URL — the full ``endpoint_url`` (which may embed a credential) never appears in the record.

    Args:
        row: An enriched endpoint row from :meth:`Database.list_mcp_endpoints_export_page` — the
            endpoint plus its current snapshot's ``score`` / ``grade`` and per-kind capability
            counts.

    Returns:
        A dict keyed by :data:`INVENTORY_COLUMNS` keys, with the capability total and health label
        computed.
    """
    tool_count = int(row.get("tool_count") or 0)
    resource_count = int(row.get("resource_count") or 0)
    resource_template_count = int(row.get("resource_template_count") or 0)
    prompt_count = int(row.get("prompt_count") or 0)
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "host": _host(row.get("endpoint_url")),
        "transport": row.get("transport"),
        "category": row.get("category"),
        "visibility": row.get("visibility"),
        "published": bool(row.get("published", False)),
        "grade": row.get("grade"),
        "score": _int_or_none(row.get("score")),
        "tool_count": tool_count,
        "resource_count": resource_count,
        "resource_template_count": resource_template_count,
        "prompt_count": prompt_count,
        "capability_count": tool_count + resource_count + resource_template_count + prompt_count,
        "last_discovery_status": row.get("last_discovery_status"),
        "last_discovered_at": _isoformat(row.get("last_discovered_at")),
        "health": derive_health(row),
        "added_via": str(row.get("added_via") or "manual"),
        "current_version_origin": _current_version_origin(row),
    }


def _csv_cell(value: Any) -> str:
    """Coerce one record value to its CSV cell text (``None`` → empty, bool → ``true``/``false``)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _csv_line(values: Iterable[Any]) -> str:
    """Serialize one ordered row of values into a single RFC-4180 CSV line (with its terminator).

    Delegates quoting/escaping to the stdlib :mod:`csv` writer over a throwaway buffer, so a value
    containing a comma, a double-quote, or a newline is correctly quoted rather than breaking the
    column layout.
    """
    buffer = io.StringIO()
    # QUOTE_MINIMAL + \r\n terminator = RFC 4180. Newlines inside a quoted field are preserved.
    csv.writer(buffer, lineterminator="\r\n").writerow(list(values))
    return buffer.getvalue()


def stream_csv(records: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    """Stream an inventory record iterable as CSV — a header row then one row per record (MCAT-19.2).

    Yields the header line first, then one correctly-escaped line per record, pulling from
    ``records`` lazily so the caller can page the catalog and this never holds more than one row's
    worth of text in memory.

    Args:
        records: An iterable of records from :func:`inventory_record` (typically a generator that
            pages the DB).

    Yields:
        The CSV document, one line (header, then per row) at a time.
    """
    yield _csv_line(_CSV_HEADER)
    for record in records:
        yield _csv_line(_csv_cell(record.get(key)) for key in _RECORD_KEYS)


def stream_json(
    records: Iterable[Mapping[str, Any]],
    *,
    tenant_slug: str,
    scope: str,
    generated_at: str,
) -> Iterator[str]:
    """Stream an inventory record iterable as a single JSON document (MCAT-19.2).

    Emits a wrapper object — ``{success, tenant_slug, scope, generated_at, endpoints: [...], count}``
    — mirroring the app's response style, but written incrementally: the ``endpoints`` array is
    streamed one object at a time (pulling from ``records`` lazily) so a large catalog never has to
    be buffered. ``count`` is accumulated while streaming and emitted last, so the total is exact
    without a second pass.

    Args:
        records: An iterable of records from :func:`inventory_record`.
        tenant_slug: The catalog's tenant slug, echoed into the wrapper for provenance.
        scope: The export scope (``"all"`` or ``"public"``), echoed for provenance.
        generated_at: Caller-supplied ISO-8601 render time (keeps the serializer pure).

    Yields:
        The JSON document in fragments (prologue, each endpoint object, epilogue).
    """
    prologue = {
        "success": True,
        "tenant_slug": tenant_slug,
        "scope": scope,
        "generated_at": generated_at,
    }
    head = json.dumps(prologue)
    # Splice the streamed array onto the wrapper: drop the closing brace, append the endpoints key.
    yield head[:-1] + ', "endpoints": ['
    count = 0
    for record in records:
        # Project through the column contract so the JSON field order matches the CSV columns.
        obj = {key: record.get(key) for key in _RECORD_KEYS}
        yield ("," if count else "") + json.dumps(obj)
        count += 1
    yield "], " + json.dumps({"count": count})[1:]
