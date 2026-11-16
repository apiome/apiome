"""SIEM export of the agent invocation audit — ATQ-4.5 (#5847).

One finalized UTC day of a tenant's AGX-3.3 ``agent_invocations`` rows, as JSON Lines or CSV, for
a SIEM to ingest. This module holds the rules and the reads; :mod:`app.agent_invocation_export_routes`
serves them.

**Rows exactly as stored.** Every column of ``agent_invocations`` is exported, in table order, read
from the catalog at request time, so columns later migrations add (ATQ-4.1 correlation, ATQ-4.2
failure class) appear without a code change. Two columns are appended:

* ``key_name`` — the agent key's name (``null`` once the key row is gone; history outlives keys);
* ``key_fingerprint`` — :func:`key_fingerprint`, a SHA-256 of the key **id**, stable across
  exports so a SIEM can correlate one key's calls. It is never derived from the AGX-3.1 secret or
  its stored hash; neither is ever selected.

**Finalized days only** (the AGX-3.3 rule that rollups and raw rows agree). A day the usage sweep
has not finalized is refused with ``409 agent-invocations-day-not-final`` and the earliest time
it can be final (:data:`FINALIZE_GRACE` after the day ends).

**Capped by tier retention.** A day whose first instant is older than the tenant's raw-row
retention (``agent_usage_retention``, V271) may already be partly pruned, so an export of it could
not equal the stored day; it is refused with ``410 agent-invocations-day-past-retention`` and the
retention stated.

**CSV is spreadsheet-safe.** A text cell that would start a formula is prefixed with ``'``; the
JSON Lines document is never altered.

**Bounded memory.** Rows are read in keyset pages of :data:`PAGE_SIZE` on ``(invoked_at, id)``,
so a large day streams without being held whole.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Literal, Optional, Sequence
from uuid import UUID

__all__ = [
    "AUDIT_EXPORT",
    "CODE_DAY_NOT_FINAL",
    "CODE_DAY_PAST_RETENTION",
    "EXTRA_COLUMNS",
    "FINALIZE_GRACE",
    "PAGE_SIZE",
    "ExportFormat",
    "InvocationExportError",
    "check_day",
    "csv_line",
    "day_bounds",
    "export_columns",
    "export_lines",
    "export_record",
    "jsonl_line",
    "key_fingerprint",
    "read_day_page",
    "read_day_status",
    "read_stored_columns",
]

#: The access-audit action every export writes.
AUDIT_EXPORT = "agent.invocations.export"

#: Refusal codes (``detail.code``).
CODE_DAY_NOT_FINAL = "agent-invocations-day-not-final"
CODE_DAY_PAST_RETENTION = "agent-invocations-day-past-retention"

#: How long after a UTC day ends the usage sweep may finalize it: V271's
#: ``rollup_agent_invocation_days`` default ``p_grace``. The day is final on the first sweep tick
#: after this.
FINALIZE_GRACE = timedelta(hours=6)

#: Rows read per keyset page.
PAGE_SIZE = 1000

#: Columns appended after the stored ones, in this order.
EXTRA_COLUMNS = ("key_name", "key_fingerprint")

#: Domain separator of :func:`key_fingerprint`, so the digest is not a bare hash of a UUID.
_FINGERPRINT_DOMAIN = "apiome.agent-key.v1"

#: A CSV cell starting with one of these would run as a spreadsheet formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

#: Column names accepted from the catalog (they are interpolated into the SELECT).
_COLUMN_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

#: Export formats.
ExportFormat = Literal["jsonl", "csv"]


class InvocationExportError(Exception):
    """A refused export: an HTTP status plus a ``{code, message, …}`` detail.

    Attributes:
        status: The HTTP status (``409`` or ``410``).
        code: The machine refusal code.
        message: The human sentence.
        extra: Further detail fields (camelCase), e.g. ``finalizesAfter`` or ``retentionDays``.
    """

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def detail(self) -> Dict[str, Any]:
        """The HTTP error detail: ``{code, message}`` plus the extra fields."""
        return {"code": self.code, "message": self.message, **self.extra}


# ---------------------------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------------------------


def key_fingerprint(key_id: Any) -> Optional[str]:
    """A stable, non-reversible identifier for an agent key, for SIEM correlation.

    Args:
        key_id: The key's id (``agent_invocations.key_id``), a UUID or its string.

    Returns:
        ``sha256:`` plus the first 32 hex digits of SHA-256 over a domain separator and the
        canonical (lower-case) key id; ``None`` when ``key_id`` is ``None``. Never derived from
        the key secret or its stored hash.
    """
    if key_id is None:
        return None
    canonical = str(key_id).strip().lower()
    digest = hashlib.sha256(f"{_FINGERPRINT_DOMAIN}:{canonical}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:32]}"


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The UTC instants a day covers.

    Args:
        day: A UTC calendar day.

    Returns:
        ``(start, end)``: the day's first instant and the next day's first instant (exclusive).
    """
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def check_day(
    day: date,
    *,
    finalized_at: Optional[datetime],
    raw_cutoff: Optional[datetime],
    now: datetime,
) -> None:
    """Refuse a day that is past retention or not yet final.

    Retention is checked first: a day past retention was necessarily finalized before its rows
    were pruned, so "past retention" is the more useful answer.

    Args:
        day: The requested UTC day.
        finalized_at: When the usage sweep finalized the day (``None`` while it is open, or when
            it was never rolled up).
        raw_cutoff: The tenant's raw-row retention cutoff (rows older than this may be pruned);
            ``None`` keeps rows forever.
        now: The reference instant (the cutoff was computed at it).

    Raises:
        InvocationExportError: ``410`` past retention (with ``retentionDays`` and
            ``oldestExportableDay``); ``409`` when the day is not final (with ``finalizesAfter``).
    """
    start, end = day_bounds(day)
    if raw_cutoff is not None and start < raw_cutoff:
        retention_days = max(1, round((now - raw_cutoff) / timedelta(days=1)))
        oldest = raw_cutoff.astimezone(timezone.utc).date()
        if day_bounds(oldest)[0] < raw_cutoff:
            oldest += timedelta(days=1)
        raise InvocationExportError(
            410,
            CODE_DAY_PAST_RETENTION,
            (
                f"Agent invocations are kept for {retention_days} days on this workspace's plan, so "
                f"{day.isoformat()} may already be pruned. The oldest day you can export is "
                f"{oldest.isoformat()}."
            ),
            day=day.isoformat(),
            retentionDays=retention_days,
            oldestExportableDay=oldest.isoformat(),
        )
    if finalized_at is None:
        finalizes_after = end + FINALIZE_GRACE
        raise InvocationExportError(
            409,
            CODE_DAY_NOT_FINAL,
            (
                f"{day.isoformat()} is not final yet: only finalized days can be exported, so the "
                f"export matches the usage rollups. It can be finalized after "
                f"{_iso(finalizes_after)}, on the next usage sweep."
            ),
            day=day.isoformat(),
            finalizesAfter=_iso(finalizes_after),
        )


def export_columns(stored: Sequence[str]) -> List[str]:
    """The export's column order: the stored columns, then :data:`EXTRA_COLUMNS`.

    Args:
        stored: ``agent_invocations`` column names in table order.

    Returns:
        The header, without duplicates.
    """
    return [name for name in stored if name not in EXTRA_COLUMNS] + list(EXTRA_COLUMNS)


def _iso(value: datetime) -> str:
    """An aware instant as ISO 8601 in UTC (``…Z`` is not used; ``+00:00`` is what Postgres writes)."""
    return value.astimezone(timezone.utc).isoformat()


def _plain(value: Any) -> Any:
    """A stored value as a JSON-ready scalar (UUID and dates as strings, numerics as numbers).

    Args:
        value: A value psycopg2 returned.

    Returns:
        ``None``, ``bool``, ``int``, ``float``, ``str``, or a list / dict of those.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return _iso(value) if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


def export_record(row: Dict[str, Any], columns: Sequence[str]) -> Dict[str, Any]:
    """One stored row as an export record: every column, plus the fingerprint.

    Args:
        row: The stored row plus ``key_name`` (as :func:`read_day_page` returns it).
        columns: The export header (:func:`export_columns`).

    Returns:
        An ordered mapping of every header column to its JSON-ready value.
    """
    record: Dict[str, Any] = {}
    for name in columns:
        if name == "key_fingerprint":
            record[name] = key_fingerprint(row.get("key_id"))
        else:
            record[name] = _plain(row.get(name))
    return record


def jsonl_line(record: Dict[str, Any]) -> str:
    """One JSON Lines record (compact, UTF-8 kept, newline-terminated)."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


def _csv_cell(value: Any) -> str:
    """A CSV cell: empty for null, ``true``/``false`` for booleans, JSON for structures.

    Text a spreadsheet would run as a formula (a free-text ``key_name`` such as ``=HYPERLINK(…)``,
    or a ``tool_name`` starting with ``-``) is prefixed with ``'``, the rule the RDG-5.4 usage
    export applies. Numbers, negative ones included, are left as they are. JSON Lines are never
    altered.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    if text and text[0] in _FORMULA_PREFIXES and not isinstance(value, (int, float)):
        return "'" + text
    return text


def csv_line(values: Sequence[Any]) -> str:
    """One CSV line (RFC 4180 quoting, ``\\r\\n`` terminated)."""
    buffer = io.StringIO()
    csv.writer(buffer).writerow([_csv_cell(value) for value in values])
    return buffer.getvalue()


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def read_stored_columns(db: Any) -> List[str]:
    """``agent_invocations`` column names, in table order, from the catalog.

    Args:
        db: The database.

    Returns:
        The names (only plain lower-case identifiers; anything else is skipped).
    """
    rows = db.execute_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'apiome' AND table_name = 'agent_invocations'
        ORDER BY ordinal_position
        """
    )
    return [row["column_name"] for row in rows or [] if _COLUMN_NAME.match(row["column_name"] or "")]


def read_day_status(db: Any, tenant_id: str, day: date, now: datetime) -> Dict[str, Optional[datetime]]:
    """When a day was finalized, and the tenant's raw retention cutoff at ``now``.

    Args:
        db: The database.
        tenant_id: The tenant.
        day: The UTC day.
        now: The reference instant.

    Returns:
        ``{"finalized_at": …, "raw_cutoff": …}``; either may be ``None`` (not final / kept
        forever).
    """
    rows = db.execute_query(
        """
        SELECT (SELECT d.finalized_at FROM apiome.agent_invocation_rollup_days d WHERE d.day = %s)
                   AS finalized_at,
               (SELECT r.raw_cutoff FROM apiome.agent_usage_retention(%s) r
                 WHERE r.tenant_id = %s::uuid) AS raw_cutoff
        """,
        (day, now, tenant_id),
    )
    row = dict(rows[0]) if rows else {}
    return {"finalized_at": row.get("finalized_at"), "raw_cutoff": row.get("raw_cutoff")}


def read_day_page(
    db: Any,
    tenant_id: str,
    day: date,
    stored: Sequence[str],
    *,
    after: Optional[tuple[Any, Any]] = None,
    limit: int = PAGE_SIZE,
) -> List[Dict[str, Any]]:
    """One keyset page of a tenant's stored rows for a UTC day, oldest first, with ``key_name``.

    Only ``api_keys.name`` is read from the key row: never its secret hash or prefix.

    Args:
        db: The database.
        tenant_id: The tenant.
        day: The UTC day.
        stored: Stored column names (:func:`read_stored_columns`).
        after: ``(invoked_at, id)`` of the last row of the previous page, or ``None``.
        limit: Page size.

    Returns:
        Up to ``limit`` rows ordered by ``(invoked_at, id)``.
    """
    names = [name for name in stored if _COLUMN_NAME.match(name)]
    select = ", ".join(f'i."{name}"' for name in names)
    start, end = day_bounds(day)
    params: List[Any] = [tenant_id, start, end]
    keyset = ""
    if after is not None:
        keyset = "AND (i.invoked_at, i.id) > (%s::timestamptz, %s::uuid)"
        params.extend([after[0], str(after[1])])
    params.append(max(1, int(limit)))
    rows = db.execute_query(
        f"""
        SELECT {select}, ak.name AS key_name
        FROM apiome.agent_invocations i
        LEFT JOIN apiome.api_keys ak ON ak.id = i.key_id AND ak.tenant_id = i.tenant_id
        WHERE i.tenant_id = %s::uuid AND i.invoked_at >= %s AND i.invoked_at < %s
        {keyset}
        ORDER BY i.invoked_at, i.id
        LIMIT %s
        """,
        tuple(params),
    )
    return [dict(row) for row in rows or []]


def export_lines(
    db: Any,
    tenant_id: str,
    day: date,
    fmt: ExportFormat,
    *,
    stored: Optional[Sequence[str]] = None,
    page_size: int = PAGE_SIZE,
) -> Iterator[str]:
    """Yield the export document line by line, one keyset page at a time.

    Args:
        db: The database.
        tenant_id: The tenant.
        day: A finalized UTC day within retention (the caller checked it).
        fmt: ``jsonl`` (one object per line, no header) or ``csv`` (a header line first).
        stored: Stored column names; read from the catalog when omitted.
        page_size: Rows per page.

    Yields:
        Lines of the document, each newline-terminated.
    """
    stored_names = list(stored) if stored is not None else read_stored_columns(db)
    columns = export_columns(stored_names)
    if fmt == "csv":
        yield csv_line(columns)
    after: Optional[tuple[Any, Any]] = None
    while True:
        page = read_day_page(db, tenant_id, day, stored_names, after=after, limit=page_size)
        for row in page:
            record = export_record(row, columns)
            yield jsonl_line(record) if fmt == "jsonl" else csv_line([record[name] for name in columns])
        if len(page) < page_size:
            return
        after = (page[-1]["invoked_at"], page[-1]["id"])
