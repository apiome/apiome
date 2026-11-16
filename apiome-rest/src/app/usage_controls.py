"""Usage export, retention and erasure controls — the rules — RDG-5.4 (#5789).

Counters about a named consumer are personal data when the consumer is a person's client. A
workspace must be able to show what it keeps, for how long, and delete it on request. This module
holds the rules and the shapes; :mod:`app.usage_controls_store` reads and writes them (apiome-db
V384), and :mod:`app.usage_controls_routes` serves them.

* **Retention** can only be lowered. The tier caps are ``licenses.seats.usage_hourly_retention_days``
  and ``usage_rollup_retention_days``. :func:`check_retention` refuses a value above a cap and names
  the cap.
* **Body samples** are one vocabulary for two opt-ins: a usage source's ``body_sample_rate`` /
  ``body_sample_until`` (RDG-1.1, at most 5 %) and an agent toolset's ``body_capture_rate`` /
  ``body_capture_until`` (AGX-3.3, at most 100 %). Both windows close at most 7 days ahead, and
  opening one takes the exact :data:`BODY_SAMPLE_ACKNOWLEDGEMENT` sentence
  (:func:`check_body_window`).
* **Export** streams ``usage_daily`` rows as CSV or JSON (:func:`csv_header`, :func:`csv_row`,
  :func:`export_row`). The consumer is shown by its slug, or ``anonymous``. It is never shown by a
  binding or a hash.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AGENT_BODY_CAPTURE_MAX_RATE",
    "AUDIT_CONSUMER_ERASED",
    "AUDIT_EXPORT",
    "AUDIT_RETENTION_UPDATE",
    "AUDIT_SOURCE_UPDATE",
    "AUDIT_TOOLSET_BODY_SAMPLES",
    "BODY_SAMPLE_ACKNOWLEDGEMENT",
    "BODY_SAMPLE_MAX_DAYS",
    "BODY_SAMPLE_MAX_RATE",
    "BodySampleWindow",
    "BodySamples",
    "CODE_ACK_REQUIRED",
    "CODE_BODY_WINDOW_INVALID",
    "CODE_NOTHING_TO_CHANGE",
    "CODE_RETENTION_ABOVE_CAP",
    "CODE_SOURCE_NOT_FOUND",
    "CODE_TOOLSET_NOT_FOUND",
    "DEFAULT_EXPORT_DAYS",
    "EXPORT_COLUMNS",
    "EXPORT_FORMAT",
    "FREE_HOURLY_RETENTION_DAYS",
    "FREE_ROLLUP_RETENTION_DAYS",
    "MAX_EXPORT_DAYS",
    "RetentionDays",
    "UsageRetentionResponse",
    "RetentionUpdate",
    "SAMPLE_RETENTION_DAYS",
    "ToolsetBodySamplesOut",
    "UsageControlsError",
    "UsageSourceList",
    "UsageSourceOut",
    "UsageSourceUpdate",
    "body_samples",
    "check_body_window",
    "check_retention",
    "csv_header",
    "csv_row",
    "effective_days",
    "export_row",
]

# ---------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------

#: The Free-tier values V290 falls back to when a license is missing or has no such key.
FREE_HOURLY_RETENTION_DAYS = 7
FREE_ROLLUP_RETENTION_DAYS = 90

#: The hard caps on a usage source's body samples (V290 rule 4).
BODY_SAMPLE_MAX_RATE = 0.05
BODY_SAMPLE_MAX_DAYS = 7
#: The hard cap on an agent toolset's body capture rate (V271).
AGENT_BODY_CAPTURE_MAX_RATE = 1.0
#: Body samples are purged after this many days, whatever the tier (V290 ``purge_usage``).
SAMPLE_RETENTION_DAYS = 7

#: The sentence a person must send (the UI shows it as a checkbox) to open a body-sample window.
BODY_SAMPLE_ACKNOWLEDGEMENT = (
    "I understand that sampled request and response bodies are stored, after redaction, for up to 7 days."
)

#: The export's default window and its longest one (a Sponsor tier's rollup retention).
DEFAULT_EXPORT_DAYS = 30
MAX_EXPORT_DAYS = 730
#: The JSON export's ``format`` marker.
EXPORT_FORMAT = "apiome.usage.export/v1"
#: Export columns, in CSV order (the JSON rows carry the same keys).
EXPORT_COLUMNS = (
    "day",
    "environment",
    "source_id",
    "source_kind",
    "version_id",
    "version_label",
    "operation_key",
    "status_code",
    "consumer",
    "calls",
    "errors",
    "latency_sum_ms",
    "latency_max_ms",
    "request_bytes",
    "response_bytes",
)

CODE_RETENTION_ABOVE_CAP = "usage-retention-above-cap"
CODE_ACK_REQUIRED = "usage-body-samples-acknowledgement-required"
CODE_BODY_WINDOW_INVALID = "usage-body-samples-invalid"
CODE_SOURCE_NOT_FOUND = "usage-source-not-found"
CODE_TOOLSET_NOT_FOUND = "agent-toolset-not-found"
CODE_NOTHING_TO_CHANGE = "usage-settings-unchanged"

AUDIT_EXPORT = "usage.export"
AUDIT_RETENTION_UPDATE = "usage.retention.update"
AUDIT_SOURCE_UPDATE = "usage.source.update"
AUDIT_TOOLSET_BODY_SAMPLES = "agent.toolset.body_samples.update"
AUDIT_CONSUMER_ERASED = "usage.consumer.erased"


class UsageControlsError(Exception):
    """A refused usage-controls request.

    Attributes:
        code: One of the ``CODE_*`` constants.
        message: What to fix, in one sentence.
        status: The HTTP status to answer with.
    """

    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def detail(self) -> Dict[str, str]:
        """The ``{code, message}`` body of the error response."""
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


class RetentionDays(BaseModel):
    """A pair of retention values in days. ``-1`` means "kept forever" (a tier cap only)."""

    model_config = ConfigDict(populate_by_name=True)

    hourly_days: Optional[int] = Field(
        default=None, alias="hourlyDays", description="How long hourly counters are kept, in days."
    )
    rollup_days: Optional[int] = Field(
        default=None, alias="rollupDays", description="How long daily rollups are kept, in days."
    )


class UsageRetentionResponse(BaseModel):
    """What the workspace keeps, for how long, and the caps it may lower."""

    model_config = ConfigDict(populate_by_name=True)

    caps: RetentionDays = Field(description="The tier's caps. `-1` keeps rows forever.")
    setting: RetentionDays = Field(description="The workspace's own values. `null` uses the cap.")
    effective: RetentionDays = Field(description="What the nightly purge applies: the smaller of the two.")
    sample_retention_days: int = Field(
        default=SAMPLE_RETENTION_DAYS,
        alias="sampleRetentionDays",
        description="Body samples are purged after this many days, whatever the tier.",
    )
    updated_at: Optional[datetime] = Field(
        default=None, alias="updatedAt", description="When the setting last changed."
    )


class RetentionUpdate(BaseModel):
    """Body of ``PUT …/usage/retention``. `null` (or an omitted field) goes back to the tier cap."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    hourly_days: Optional[int] = Field(
        default=None, ge=1, alias="hourlyDays", description="Days of hourly counters to keep (at most the cap)."
    )
    rollup_days: Optional[int] = Field(
        default=None, ge=1, alias="rollupDays", description="Days of daily rollups to keep (at most the cap)."
    )


def effective_days(cap: int, setting: Optional[int]) -> int:
    """The retention the purge applies (V384 ``usage_retention``).

    Args:
        cap: The tier cap; negative keeps rows forever.
        setting: The workspace's own value, or ``None``.

    Returns:
        The smaller of the two, ``setting`` under a forever cap, ``cap`` without a setting.
    """
    if setting is None:
        return cap
    if cap < 0:
        return setting
    return min(cap, setting)


def check_retention(update: RetentionUpdate, caps: RetentionDays) -> None:
    """Refuse a retention value above its tier cap.

    Args:
        update: The requested values.
        caps: The tier caps (``-1`` = forever, which accepts any positive value).

    Raises:
        UsageControlsError: 422 ``usage-retention-above-cap`` naming the key and the cap.
    """
    for key, value, cap in (
        ("usage_hourly_retention_days", update.hourly_days, caps.hourly_days),
        ("usage_rollup_retention_days", update.rollup_days, caps.rollup_days),
    ):
        if value is not None and cap is not None and cap >= 0 and value > cap:
            raise UsageControlsError(
                CODE_RETENTION_ABOVE_CAP,
                f"{key} may be at most {cap} days on this workspace's tier (asked for {value}); "
                "retention can only be lowered",
            )


# ---------------------------------------------------------------------------------------------
# Body samples (one vocabulary for usage sources and agent toolsets)
# ---------------------------------------------------------------------------------------------


class BodySamples(BaseModel):
    """A body-sample opt-in as it stands, with its hard caps."""

    model_config = ConfigDict(populate_by_name=True)

    rate: float = Field(description="Fraction of exchanges whose bodies are kept. `0` keeps none.")
    until: Optional[datetime] = Field(default=None, description="When sampling stops.")
    open: bool = Field(description="Whether sampling is happening right now (`rate > 0` and `until` ahead).")
    max_rate: float = Field(alias="maxRate", description="The hard cap on `rate`.")
    max_window_days: int = Field(
        default=BODY_SAMPLE_MAX_DAYS, alias="maxWindowDays", description="`until` may be at most this many days ahead."
    )
    retention_days: int = Field(
        default=SAMPLE_RETENTION_DAYS, alias="retentionDays", description="How long a kept body is stored."
    )


class BodySampleWindow(BaseModel):
    """Open, change or close a body-sample window.

    Set ``rate`` to ``0`` to close it. Opening it takes ``until`` and the exact acknowledgement sentence.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rate: float = Field(ge=0, le=1, description="Fraction of exchanges to keep; `0` closes the window.")
    until: Optional[datetime] = Field(default=None, description="When sampling stops; at most 7 days ahead.")
    acknowledgement: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Required to open a window: the exact sentence `BODY_SAMPLE_ACKNOWLEDGEMENT` (shown in the UI).",
    )


def body_samples(
    rate: Any, until: Optional[datetime], *, max_rate: float, now: Optional[datetime] = None
) -> BodySamples:
    """Describe a stored body-sample opt-in.

    Args:
        rate: The stored rate (NUMERIC).
        until: The stored end of the window.
        max_rate: The hard cap for this kind of opt-in.
        now: The current time (for tests).

    Returns:
        The opt-in, with ``open`` computed.
    """
    current = now or datetime.now(timezone.utc)
    value = float(rate or 0)
    return BodySamples(
        rate=value,
        until=until,
        open=value > 0 and until is not None and until > current,
        max_rate=max_rate,
    )


def check_body_window(
    window: BodySampleWindow, *, max_rate: float, now: Optional[datetime] = None
) -> Optional[datetime]:
    """Check a requested window against the hard caps and the acknowledgement rule.

    Args:
        window: The request.
        max_rate: ``BODY_SAMPLE_MAX_RATE`` for a usage source, ``AGENT_BODY_CAPTURE_MAX_RATE`` for a
            toolset.
        now: The current time (for tests).

    Returns:
        The ``until`` to store: the request's, or ``None`` when the window is being closed.

    Raises:
        UsageControlsError: 422 ``usage-body-samples-invalid`` for a rate over the cap or a
            missing, past or too-distant ``until``. 422
            ``usage-body-samples-acknowledgement-required`` when an opening window does not carry
            the exact sentence.
    """
    if window.rate == 0:
        return None
    if window.rate > max_rate:
        raise UsageControlsError(
            CODE_BODY_WINDOW_INVALID, f"the body-sample rate may be at most {max_rate:g} (asked for {window.rate:g})"
        )
    current = now or datetime.now(timezone.utc)
    until = window.until
    if until is None:
        raise UsageControlsError(CODE_BODY_WINDOW_INVALID, "a body-sample window needs `until`")
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if until <= current:
        raise UsageControlsError(CODE_BODY_WINDOW_INVALID, "`until` must be in the future")
    if until > current + timedelta(days=BODY_SAMPLE_MAX_DAYS):
        raise UsageControlsError(CODE_BODY_WINDOW_INVALID, f"`until` may be at most {BODY_SAMPLE_MAX_DAYS} days ahead")
    if (window.acknowledgement or "").strip() != BODY_SAMPLE_ACKNOWLEDGEMENT:
        raise UsageControlsError(
            CODE_ACK_REQUIRED,
            f'opening a body-sample window needs the acknowledgement: "{BODY_SAMPLE_ACKNOWLEDGEMENT}"',
        )
    return until


# ---------------------------------------------------------------------------------------------
# Sources and toolsets
# ---------------------------------------------------------------------------------------------


class UsageSourceOut(BaseModel):
    """One traffic source of a project, with what it captures."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str = Field(description="`otlp`, `har`, `access_log`, `mock`, `agent` or `sdk_beacon`.")
    environment: str
    enabled: bool
    sampling_rate: float = Field(alias="samplingRate", description="Head sampling: fraction (0..1] of events kept.")
    field_capture: bool = Field(
        alias="fieldCapture", description="Whether field presence (names, never values) is counted."
    )
    body_samples: BodySamples = Field(alias="bodySamples")
    last_received_at: Optional[datetime] = Field(default=None, alias="lastReceivedAt")


class ToolsetBodySamplesOut(BaseModel):
    """An agent toolset of the project, with its AGX-3.3 body-capture opt-in."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    version_id: str = Field(alias="versionId")
    version_label: Optional[str] = Field(default=None, alias="versionLabel")
    enabled: bool
    body_samples: BodySamples = Field(alias="bodySamples")


class UsageSourceList(BaseModel):
    """The project's sources and agent toolsets: everything that can keep traffic or bodies."""

    model_config = ConfigDict(populate_by_name=True)

    sources: List[UsageSourceOut] = Field(default_factory=list)
    agent_toolsets: List[ToolsetBodySamplesOut] = Field(default_factory=list, alias="agentToolsets")
    acknowledgement: str = Field(
        default=BODY_SAMPLE_ACKNOWLEDGEMENT, description="The sentence that opens a body-sample window."
    )


class UsageSourceUpdate(BaseModel):
    """Body of ``PATCH …/usage/sources/{id}``. At least one field is required."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sampling_rate: Optional[float] = Field(
        default=None, gt=0, le=1, alias="samplingRate", description="Head sampling, in (0, 1]."
    )
    field_capture: Optional[bool] = Field(default=None, alias="fieldCapture")
    body_samples: Optional[BodySampleWindow] = Field(default=None, alias="bodySamples")


# ---------------------------------------------------------------------------------------------
# Export rows
# ---------------------------------------------------------------------------------------------


def _iso(value: Any) -> Any:
    """Dates as ISO strings; everything else as is."""
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def export_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One ``usage_daily`` read as an export row (the :data:`EXPORT_COLUMNS` keys, JSON-ready).

    Args:
        row: A row from :func:`app.usage_controls_store.export_day_rows`.

    Returns:
        The row with exactly the export columns.
    """
    out: Dict[str, Any] = {}
    for column in EXPORT_COLUMNS:
        value = row.get(column)
        if column in ("calls", "errors", "latency_sum_ms", "latency_max_ms", "request_bytes", "response_bytes"):
            value = int(value or 0)
        elif column == "status_code":
            value = int(value)
        out[column] = _iso(value)
    return out


def _csv_cell(value: Any) -> str:
    """A CSV cell that a spreadsheet will not run as a formula."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r" and not text.lstrip("-").replace(".", "", 1).isdigit():
        return "'" + text
    return text


def _csv_line(cells: List[Any]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow([_csv_cell(cell) for cell in cells])
    return buffer.getvalue()


def csv_header() -> str:
    """The CSV header line."""
    return _csv_line(list(EXPORT_COLUMNS))


def csv_row(row: Mapping[str, Any]) -> str:
    """One export row as a CSV line.

    Args:
        row: An :func:`export_row`.

    Returns:
        The line, CRLF-terminated.
    """
    return _csv_line([row[column] for column in EXPORT_COLUMNS])


ExportFormat = Literal["csv", "json"]
