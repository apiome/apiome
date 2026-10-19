"""The usage ingest pipeline — RDG-1.2 (#5760).

``POST /v1/tenants/{tenant}/usage/ingest`` is the **one door** raw traffic takes into Apiome, so it
is the one place that has to make every privacy promise of the usage index (migration V290) true.
This module is the pipeline itself, as pure functions over a parsed batch — no I/O. The store
(:mod:`app.usage_ingest_store`) feeds it the source, the tier cap and the published revisions, and
writes what it returns; the route (:mod:`app.usage_ingest_routes`) parses the request.

The pipeline runs in this order and stops an event at its first refusal:

1. **Tier cap** — ``licenses.seats.usage_events_per_day``. Checked by the store before anything
   else (it needs the day's ledger); a batch over the cap is answered ``429 usage-quota-exceeded``
   and ledgered as wholly rejected.
2. **Head sampling** — :func:`head_sample_keep` hashes ``(source, observed_at, path, status)`` and
   keeps the event when the hash falls under the source's ``sampling_rate``. The decision is
   deterministic, so a retried batch samples the same events. Kept counts are scaled by the inverse
   rate (:func:`scale`), and the result says ``basis: sampled``.
3. **Scrubbing** of every string the index keeps (:func:`scrub_event`):

   * a path segment that a named :mod:`app.intake_secret_scrub` pattern (or its entropy heuristic)
     flags, or that looks like an email or a UUID, is generalized to ``{param}`` by
     :func:`app.inferred_spec.template_path`;
   * the query string is split off **before the event is built**: parameter names are kept (and
     scrubbed the same way), values are discarded;
   * the user agent is scrubbed (named patterns, entropy, emails) and truncated to 256 characters;
   * a field pointer with a flagged segment is dropped.

   Scrubbing always enforces, with entropy detection on, whatever the tenant's intake scrub policy
   says: ``warn_only`` is a statement about source documents a person uploads, not permission to
   keep a token that rode along in someone's traffic.
4. **Template matching** against the project's **published** revisions through
   :class:`app.consumer_surface.SpecIndex` — the resolver the Pact importer uses — so ``/pets/42``
   lands on ``GET /pets/{petId}`` the same way in both places (:class:`RevisionMatcher`). A matched
   event counts into ``usage_hourly``; an unmatched one into ``usage_unmatched_daily`` under the
   template the inferred-spec tokenizer gives it (numeric / UUID / hash segments become
   ``{param}``); with the source's ``field_capture`` on, its query names and ``fields`` count into
   ``usage_field_daily``. A draft revision is never matched against.
5. **Ledger** — one ``usage_ingest_batch`` row per batch: every event is exactly one of accepted,
   sampled out, unmatched or rejected (:class:`BatchPlan`), and the response echoes the counts.

**Bodies** reach the door only as an opt-in ``sample`` on an event. A batch carrying one is refused
``422 usage-body-not-accepted`` unless the source's body window is open
(:func:`refuse_closed_body_window`). When it is, a kept event's sample is chosen at the source's
``body_sample_rate``, reduced by the PMR-2.4 capture reducer (:func:`app.mock_capture.redact_exchange`)
and stored only if the final credential re-scan is clean and it fits in 16 KiB
(:func:`reduce_sample`) — "anything still flagged is not stored at all".
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, unquote

from pydantic import ValidationError

from .consumer_binding import ConsumerMatcher
from .consumer_surface import SpecIndex
from .inferred_spec import template_path
from .intake_secret_scrub import REDACTION_MARKER, scrub_document_text
from .mock_capture import REDACTION_PATTERNS, redact_exchange, residual_credential_pointers
from .usage_events import (
    LATENCY_BOUNDS_MS,
    MAX_USER_AGENT_LENGTH,
    MOCK_ENVIRONMENT,
    USAGE_EVENT_SCHEMA,
    EventFields,
    UsageEvent,
    latency_bucket,
)

__all__ = [
    "BASIS_COMPLETE",
    "BASIS_SAMPLED",
    "CODE_BATCH_INVALID",
    "CODE_BATCH_TOO_LARGE",
    "CODE_BODY_NOT_ACCEPTED",
    "CODE_KEY_REQUIRED",
    "CODE_QUOTA_EXCEEDED",
    "CODE_SOURCE_DISABLED",
    "CODE_SOURCE_NOT_FOUND",
    "CODE_SOURCE_REQUIRED",
    "MAX_BATCH_BYTES",
    "MAX_EVENTS_PER_BATCH",
    "MAX_REJECTION_DETAILS",
    "MAX_SAMPLE_BYTES",
    "QUERY_POINTER_PREFIX",
    "REJECTION_REASONS",
    "BatchPlan",
    "FieldGroup",
    "HourlyCounter",
    "RevisionMatcher",
    "ScrubbedEvent",
    "SourceConfig",
    "UnmatchedCounter",
    "UsageIngestError",
    "batch_digest",
    "decode_body",
    "head_sample_keep",
    "next_utc_midnight",
    "parse_batch",
    "plan_batch",
    "reduce_sample",
    "refuse_closed_body_window",
    "rejected_plan",
    "scale",
    "scrub_event",
]

#: The most events one batch may carry.
MAX_EVENTS_PER_BATCH = 5000

#: The largest batch, in bytes, compressed **and** decompressed (so a gzip bomb is refused too).
MAX_BATCH_BYTES = 2 * 1024 * 1024

#: The most per-event rejections the response lists (the counts always cover every event).
MAX_REJECTION_DETAILS = 100

#: The largest stored sample, the V290 ``usage_sample.exchange`` CHECK.
MAX_SAMPLE_BYTES = 16384

#: The longest path template the index stores (V290 ``path_template`` / ``operation_key``).
_MAX_TEMPLATE_LENGTH = 1024

#: The longest field pointer the index stores (V290 ``usage_field_daily.pointer``).
_MAX_POINTER_LENGTH = 512

#: ``usage_field_daily`` pointer prefix for a query parameter name. It is the classifier's own
#: parameter identity (``<in>:<name>``, :meth:`app.consumer_surface.SpecIndex.resolve_field`), so a
#: query-parameter count joins a consumer contract's parameter pointer without translation.
QUERY_POINTER_PREFIX = "/parameters/query:"

#: Counts are complete (``sampling_rate`` 1) or scaled from a head sample.
BASIS_COMPLETE = "complete"
BASIS_SAMPLED = "sampled"

# Error codes the route answers with (``{"code", "message"}``).
CODE_QUOTA_EXCEEDED = "usage-quota-exceeded"
CODE_BODY_NOT_ACCEPTED = "usage-body-not-accepted"
CODE_BATCH_TOO_LARGE = "usage-batch-too-large"
CODE_BATCH_INVALID = "usage-batch-invalid"
CODE_SOURCE_REQUIRED = "usage-source-required"
CODE_SOURCE_NOT_FOUND = "usage-source-not-found"
CODE_SOURCE_DISABLED = "usage-source-disabled"
CODE_KEY_REQUIRED = "usage-ingest-key-required"

# Why one event was rejected. A rejection names the reason and the event's index, never a value.
REASON_INVALID_EVENT = "invalid-event"
REASON_SOURCE_MISMATCH = "source-mismatch"
REASON_ENVIRONMENT_RESERVED = "environment-reserved"
REASON_TEMPLATE_UNSTORABLE = "template-unstorable"
REASON_DAY_FINALIZED = "day-finalized"
REASON_QUOTA_EXCEEDED = "quota-exceeded"

#: Every rejection reason, for the response schema and the docs.
REJECTION_REASONS: Tuple[str, ...] = (
    REASON_INVALID_EVENT,
    REASON_SOURCE_MISMATCH,
    REASON_ENVIRONMENT_RESERVED,
    REASON_TEMPLATE_UNSTORABLE,
    REASON_DAY_FINALIZED,
    REASON_QUOTA_EXCEEDED,
)

_BUCKETS = len(LATENCY_BOUNDS_MS) + 1
_EMAIL = re.compile(r"[^@\s/]+@[^@\s/]+\.[A-Za-z]{2,}")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_QUERY_NAME = re.compile(r"^[^\s~/]{1,128}$")
_TWO_TO_64 = 2 ** 64

#: What the V290 CHECKs accept for an operation key and an unmatched template.
_OPERATION_KEY = re.compile(r"^/paths/[^?#\s]+/[a-z]+$")
_TEMPLATE = re.compile(r"^/[^?#\s]*$")

#: The largest latency ``usage_hourly.latency_max_ms`` (INTEGER) can hold.
_MAX_LATENCY_MS = 2**31 - 1

#: The capture policy samples are reduced under: the always-on credential rules plus every
#: personal-data detector, since an ingest source never declared which of its fields are personal.
_SAMPLE_POLICY: Dict[str, Any] = {"redaction": {"patterns": sorted(REDACTION_PATTERNS)}}


class UsageIngestError(Exception):
    """A refusal of the whole batch.

    Attributes:
        status: The HTTP status the route answers with.
        code: The stable error code (``usage-…``).
        message: A sentence for the caller. Never quotes a value from the batch.
        retry_at: For a quota refusal, when the cap resets.
        batch_id: For a refusal that was ledgered, the ledger row.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retry_at: Optional[datetime] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_at = retry_at
        self.batch_id = batch_id

    def detail(self) -> Dict[str, Any]:
        """The JSON ``detail`` the route answers with."""
        body: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_at is not None:
            body["retryAt"] = self.retry_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if self.batch_id is not None:
            body["batchId"] = self.batch_id
        return body


@dataclass(frozen=True)
class SourceConfig:
    """The ``usage_source`` row a batch is for.

    Attributes:
        id: The source id.
        tenant_id: Its tenant.
        project_id: The project whose revisions its traffic is matched against.
        kind: ``otlp``, ``har``, ``access_log``, ``mock``, ``agent`` or ``sdk_beacon``.
        environment: The environment an event that names none is filed under.
        sampling_rate: Head-sampling rate in ``(0, 1]``.
        field_capture: Whether query names and ``fields`` count into ``usage_field_daily``.
        body_sample_rate: Opt-in sample rate in ``[0, 0.05]``.
        body_sample_until: When the body window closes.
        enabled: A disabled source is refused.
    """

    id: str
    tenant_id: str
    project_id: str
    kind: str
    environment: str = "prod"
    sampling_rate: float = 1.0
    field_capture: bool = False
    body_sample_rate: float = 0.0
    body_sample_until: Optional[datetime] = None
    enabled: bool = True

    def body_window_open(self, now: datetime) -> bool:
        """Whether the source may send bodies at ``now``.

        Args:
            now: The current instant.

        Returns:
            True while ``body_sample_rate > 0`` and ``body_sample_until`` is in the future.
        """
        return (
            self.body_sample_rate > 0
            and self.body_sample_until is not None
            and self.body_sample_until > now
        )


# ---------------------------------------------------------------------------------------------
# Parsing the request
# ---------------------------------------------------------------------------------------------


def decode_body(raw: bytes, content_encoding: Optional[str]) -> bytes:
    """Undo the request's content encoding, refusing anything over :data:`MAX_BATCH_BYTES`.

    Args:
        raw: The request body as received.
        content_encoding: The ``Content-Encoding`` header (``gzip`` or nothing).

    Returns:
        The batch's JSON bytes.

    Raises:
        UsageIngestError: 413 ``usage-batch-too-large`` over the limit (before or after
            decompression), 400 ``usage-batch-invalid`` for an unknown encoding or broken gzip.
    """
    if len(raw) > MAX_BATCH_BYTES:
        raise UsageIngestError(413, CODE_BATCH_TOO_LARGE, f"a usage batch is at most {MAX_BATCH_BYTES} bytes")
    encoding = (content_encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return raw
    if encoding not in ("gzip", "x-gzip"):
        raise UsageIngestError(400, CODE_BATCH_INVALID, "Content-Encoding must be gzip or absent")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = inflater.decompress(raw, MAX_BATCH_BYTES + 1)
    except zlib.error as exc:
        raise UsageIngestError(400, CODE_BATCH_INVALID, "the gzip body could not be decompressed") from exc
    if len(data) > MAX_BATCH_BYTES or inflater.unconsumed_tail:
        raise UsageIngestError(
            413, CODE_BATCH_TOO_LARGE, f"a usage batch is at most {MAX_BATCH_BYTES} bytes decompressed"
        )
    return data


def batch_digest(data: bytes) -> str:
    """SHA-256 (hex) of the batch as received, after decompression — the ledger's replay key.

    Args:
        data: The decoded batch bytes.

    Returns:
        64 lower-case hex characters.
    """
    return hashlib.sha256(data).hexdigest()


def parse_batch(data: bytes) -> Tuple[Optional[str], List[Any]]:
    """Read the batch envelope ``{"source_id"?, "events": [...]}``.

    Each event is left as parsed JSON here: a malformed event is *rejected* (and ledgered) by
    :func:`plan_batch` rather than failing the whole batch.

    Args:
        data: The decoded batch bytes.

    Returns:
        ``(source_id from the body or None, the raw events)``.

    Raises:
        UsageIngestError: 400 ``usage-batch-invalid`` when the body is not the envelope, 413
            ``usage-batch-too-large`` over :data:`MAX_EVENTS_PER_BATCH` events.
    """
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UsageIngestError(400, CODE_BATCH_INVALID, "the batch is not UTF-8 JSON") from exc
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        raise UsageIngestError(400, CODE_BATCH_INVALID, 'the batch must be an object with an "events" array')
    unknown = set(document) - {"source_id", "events"}
    if unknown:
        raise UsageIngestError(400, CODE_BATCH_INVALID, 'a batch carries only "source_id" and "events"')
    events = document["events"]
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise UsageIngestError(
            413, CODE_BATCH_TOO_LARGE, f"a usage batch carries at most {MAX_EVENTS_PER_BATCH} events"
        )
    source_id = document.get("source_id")
    if source_id is not None and not isinstance(source_id, str):
        raise UsageIngestError(400, CODE_BATCH_INVALID, "source_id must be a string")
    return source_id, events


def refuse_closed_body_window(raw_events: Sequence[Any], source: SourceConfig, now: datetime) -> None:
    """Refuse a batch that carries a body the source may not send.

    Args:
        raw_events: The batch's events as parsed.
        source: The source.
        now: The current instant.

    Raises:
        UsageIngestError: 422 ``usage-body-not-accepted`` when any event carries ``sample`` and
            the source's body window is closed (``body_sample_rate`` 0, or past
            ``body_sample_until``).
    """
    if source.body_window_open(now):
        return
    if any(isinstance(event, dict) and event.get("sample") is not None for event in raw_events):
        raise UsageIngestError(
            422,
            CODE_BODY_NOT_ACCEPTED,
            "this source does not accept bodies: set a body_sample_rate and an open body_sample_until "
            "window first, or send events without a sample",
        )


def next_utc_midnight(now: datetime) -> datetime:
    """When the daily cap resets: the next 00:00 UTC.

    Args:
        now: The current instant.

    Returns:
        The start of the next UTC day.
    """
    today = now.astimezone(timezone.utc).date()
    return datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)


# ---------------------------------------------------------------------------------------------
# Step 2 — head sampling
# ---------------------------------------------------------------------------------------------


def _unit_hash(*parts: str) -> float:
    """A deterministic number in ``[0, 1)`` from the SHA-256 of ``parts``."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / _TWO_TO_64


def head_sample_keep(source_id: str, observed_at: datetime, path: str, status: int, rate: float) -> bool:
    """Whether head sampling keeps one event.

    Args:
        source_id: The source.
        observed_at: The event's instant.
        path: The path as the source sent it (without query).
        status: The response status.
        rate: The source's ``sampling_rate``.

    Returns:
        True when the hash of ``(source, observed_at, path, status)`` falls under ``rate``; always
        True at rate 1. The same event always gets the same answer.
    """
    if rate >= 1:
        return True
    stamp = observed_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return _unit_hash(source_id, stamp, path, str(status)) < rate


def _body_sample_keep(source_id: str, observed_at: datetime, path: str, status: int, rate: float) -> bool:
    """Whether a kept event's opt-in sample is chosen — the same hash under another salt."""
    stamp = observed_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return _unit_hash("body", source_id, stamp, path, str(status)) < rate


def scale(value: int, rate: float) -> int:
    """Scale a sampled count by the inverse sampling rate (round half to even).

    Args:
        value: A count over the kept events.
        rate: The sampling rate in ``(0, 1]``.

    Returns:
        ``value / rate`` rounded to an integer; ``value`` itself at rate 1.
    """
    if rate >= 1 or value == 0:
        return int(value)
    return int((Decimal(value) / Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


# ---------------------------------------------------------------------------------------------
# Step 3 — scrubbing
# ---------------------------------------------------------------------------------------------


def _is_sensitive(text: str) -> bool:
    """Whether one path segment, query name or pointer segment must not persist as written.

    True when a named credential pattern or the entropy heuristic of
    :func:`app.intake_secret_scrub.scrub_document_text` flags it, or it looks like an email or a
    UUID. The segment is percent-decoded first, so ``Bearer%20abc…`` is seen as ``Bearer abc…``.
    """
    decoded = unquote(text)
    if _EMAIL.search(decoded) or _UUID.match(decoded):
        return True
    return scrub_document_text(decoded).scrubbed


def _scrub_free_text(text: str) -> Tuple[str, int]:
    """Scrub a user agent: credentials and emails become the redaction marker, then truncate.

    Returns:
        ``(scrubbed text, how many values were redacted)``.
    """
    outcome = scrub_document_text(text)
    scrubbed, emails = _EMAIL.subn(REDACTION_MARKER, outcome.text)
    return _CONTROL.sub(" ", scrubbed)[:MAX_USER_AGENT_LENGTH], outcome.redaction_count + emails


def _split_query(path: str) -> Tuple[str, List[str]]:
    """Split a raw path into the path and its query parameter **names** (values discarded).

    Returns:
        ``(path without query or fragment, the distinct names in order of appearance)``.
    """
    without_fragment = path.split("#", 1)[0]
    bare, _, query = without_fragment.partition("?")
    names: List[str] = []
    for name, _value in parse_qsl(query, keep_blank_values=True):
        if name not in names:
            names.append(name)
    return bare or "/", names


def _escape_pointer(segment: str) -> str:
    """RFC 6901-escape one pointer segment."""
    return segment.replace("~", "~0").replace("/", "~1")


def _pointer_sensitive(pointer: str) -> bool:
    """Whether any segment of a JSON Pointer is sensitive."""
    return any(
        _is_sensitive(segment.replace("~1", "/").replace("~0", "~"))
        for segment in pointer.split("/")[1:]
        if segment
    )


@dataclass(frozen=True)
class ScrubbedEvent:
    """One event after scrubbing — the only form the rest of the pipeline sees.

    Attributes:
        index: Its position in the batch.
        event: The event, with its path generalized, user agent scrubbed and field pointers
            filtered.
        query_names: Its query parameter names, scrubbed (values were never kept).
        sample: The opt-in sample as the source sent it, or ``None``.
        findings: How many strings scrubbing rewrote or dropped.
    """

    index: int
    event: UsageEvent
    query_names: Tuple[str, ...]
    sample: Optional[Mapping[str, Any]]
    findings: int


def scrub_event(
    index: int,
    event: UsageEvent,
    query_names: Sequence[str],
    sample: Optional[Mapping[str, Any]],
    *,
    user_agent: Optional[str] = None,
) -> ScrubbedEvent:
    """Scrub every string of one event the index (or a sample) could keep.

    Args:
        index: The event's position in the batch.
        event: The validated event (path already without query).
        query_names: The query parameter names split off its path.
        sample: Its opt-in sample, if any.
        user_agent: The raw user agent held aside before validation; when given it replaces the
            event's own. Scrubbed first, then truncated to 256 characters.

    Returns:
        The :class:`ScrubbedEvent`.
    """
    findings = 0

    flagged: List[str] = []

    def _flag(segment: str) -> bool:
        if _is_sensitive(segment):
            flagged.append(segment)
            return True
        return False

    path = template_path(event.path, generalize_dynamic=False, is_sensitive=_flag)
    findings += len(flagged)

    kept_names: List[str] = []
    for name in query_names:
        if _QUERY_NAME.match(name) and not _is_sensitive(name):
            kept_names.append(name)
        else:
            findings += 1

    if user_agent is None:
        user_agent = event.user_agent
    if user_agent is not None:
        user_agent, redacted = _scrub_free_text(user_agent)
        findings += redacted

    fields = event.fields
    if fields is not None:
        request = [pointer for pointer in fields.request if not _pointer_sensitive(pointer)]
        response = [pointer for pointer in fields.response if not _pointer_sensitive(pointer)]
        findings += len(fields.request) - len(request) + len(fields.response) - len(response)
        fields = EventFields(request=request, response=response)

    scrubbed = event.model_copy(update={"path": path, "user_agent": user_agent, "fields": fields})
    return ScrubbedEvent(
        index=index, event=scrubbed, query_names=tuple(kept_names), sample=sample, findings=findings
    )


# ---------------------------------------------------------------------------------------------
# Step 4 — template matching
# ---------------------------------------------------------------------------------------------


class RevisionMatcher:
    """Resolve a method and a path onto an operation of the project's published revisions.

    Revisions are tried newest-published first and the first match wins, so traffic is attributed
    to the newest published revision that declares the operation. An event whose
    ``spec_revision_id`` names one of these revisions (an Apiome-controlled source) tries that
    revision first. Only published revisions are ever handed in, so an operation that only a draft
    declares stays unmatched.
    """

    def __init__(self, revisions: Sequence[Tuple[str, SpecIndex]]) -> None:
        """Hold the indexes.

        Args:
            revisions: ``(versions.id, SpecIndex)`` pairs, newest published first.
        """
        self._revisions = list(revisions)

    def match(self, method: str, path: str, spec_revision_id: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
        """Find the operation a call belongs to.

        Args:
            method: The HTTP method.
            path: The scrubbed path (concrete or templated).
            spec_revision_id: The revision the source says served the call, if any.

        Returns:
            ``(version_record_id, operation_key, path template)``, or ``None`` when no published
            revision declares the operation.
        """
        ordered = self._revisions
        if spec_revision_id:
            ordered = sorted(self._revisions, key=lambda pair: pair[0] != spec_revision_id)
        for version_id, index in ordered:
            entry = index.match_operation(method, path)
            if entry is not None:
                return version_id, entry.pointer, entry.path
        return None


# ---------------------------------------------------------------------------------------------
# Step 5 — the plan the store writes
# ---------------------------------------------------------------------------------------------


@dataclass
class HourlyCounter:
    """One ``usage_hourly`` grain's counts over the batch's kept events (unscaled).

    The grain is ``(environment, hour, version_record_id, operation_key, status,
    consumer_binding_id)``; the source, tenant and project are the batch's. The binding is the one
    the RDG-1.8 :class:`~app.consumer_binding.ConsumerMatcher` attributed the call to, or ``None``
    for an anonymous call.
    """

    events: int = 0
    buckets: List[int] = field(default_factory=lambda: [0] * _BUCKETS)
    latency_sum_ms: int = 0
    latency_max_ms: int = 0
    auth_present: int = 0
    auth_unknown: int = 0
    versioned: int = 0
    version_unknown: int = 0
    https: int = 0
    request_bytes: int = 0
    response_bytes: int = 0

    def add(self, event: UsageEvent) -> None:
        """Count one event."""
        self.events += 1
        self.buckets[latency_bucket(event.latency_ms)] += 1
        self.latency_sum_ms += event.latency_ms
        self.latency_max_ms = max(self.latency_max_ms, event.latency_ms)
        self.auth_present += event.auth_present == "true"
        self.auth_unknown += event.auth_present == "unknown"
        self.versioned += event.version_hint.present == "true"
        self.version_unknown += event.version_hint.present == "unknown"
        self.https += event.scheme == "https"
        self.request_bytes += event.request_bytes or 0
        self.response_bytes += event.response_bytes or 0

    def scaled(self, rate: float) -> Dict[str, Any]:
        """The row's counters scaled by the inverse rate, still satisfying the V290 CHECKs.

        ``calls`` is the sum of the scaled buckets (so the histogram always sums to it), and the
        posture pairs are clamped so that, after rounding, neither pair exceeds ``calls``.

        Args:
            rate: The source's sampling rate.

        Returns:
            Column → value for ``calls``, ``latency_buckets``, ``latency_sum_ms``,
            ``latency_max_ms``, the five posture counters and the two byte counters.
        """
        buckets = [scale(count, rate) for count in self.buckets]
        calls = sum(buckets)
        present = min(scale(self.auth_present, rate), calls)
        versioned = min(scale(self.versioned, rate), calls)
        return {
            "calls": calls,
            "latency_buckets": buckets,
            "latency_sum_ms": scale(self.latency_sum_ms, rate),
            "latency_max_ms": self.latency_max_ms,
            "auth_present_calls": present,
            "auth_unknown_calls": min(scale(self.auth_unknown, rate), calls - present),
            "versioned_calls": versioned,
            "version_unknown_calls": min(scale(self.version_unknown, rate), calls - versioned),
            "https_calls": min(scale(self.https, rate), calls),
            "request_bytes": scale(self.request_bytes, rate),
            "response_bytes": scale(self.response_bytes, rate),
        }


@dataclass
class UnmatchedCounter:
    """One ``usage_unmatched_daily`` grain ``(environment, day, method, path_template)``."""

    first_seen: datetime
    last_seen: datetime
    by_class: List[int] = field(default_factory=lambda: [0] * 5)

    def add(self, event: UsageEvent) -> None:
        """Count one event."""
        self.first_seen = min(self.first_seen, event.observed_at)
        self.last_seen = max(self.last_seen, event.observed_at)
        self.by_class[event.status // 100 - 1] += 1

    def scaled(self, rate: float) -> Dict[str, Any]:
        """Column → value for ``calls`` and ``calls_1xx`` … ``calls_5xx``, scaled."""
        classes = [scale(count, rate) for count in self.by_class]
        row: Dict[str, Any] = {"calls": sum(classes)}
        for position, count in enumerate(classes):
            row[f"calls_{position + 1}xx"] = count
        return row


@dataclass
class UnattributedCounter:
    """One ``usage_unattributed_client_daily`` grain ``(day, client_kind, client_key)`` (CDG-3.5)."""

    first_seen: datetime
    last_seen: datetime
    events: int = 0

    def add(self, event: UsageEvent) -> None:
        """Count one event."""
        self.events += 1
        self.first_seen = min(self.first_seen, event.observed_at)
        self.last_seen = max(self.last_seen, event.observed_at)


@dataclass
class FieldGroup:
    """One ``usage_field_daily`` group ``(environment, day, operation_key, direction, status)``.

    Attributes:
        inspected: Kept events of the group whose fields were counted.
        pointers: Pointer → how many of them carried it.
    """

    inspected: int = 0
    pointers: Dict[str, int] = field(default_factory=dict)


@dataclass
class BatchPlan:
    """What the pipeline decided about one batch — the store writes it and the ledger row.

    Attributes:
        received: Events in the batch.
        accepted: Kept and matched.
        sampled_out: Dropped by head sampling.
        unmatched: Kept, but no published revision declares the operation.
        rejected: Refused (see ``rejections``).
        scrub_findings: Strings scrubbing rewrote or dropped.
        rejections: ``(index, reason)`` per rejected event.
        hourly: ``usage_hourly`` grains.
        unmatched_rows: ``usage_unmatched_daily`` grains.
        field_groups: ``usage_field_daily`` groups.
        samples: ``(environment, captured_at, operation_key, status, exchange)`` to store.
        samples_dropped: Chosen samples the re-scan or the size cap refused.
        sampling_rate: The source's rate, which every count above was scaled by.
        attributed: Accepted events a consumer binding matched (the rest are anonymous).
        binding_matches: Binding id → the newest observed time attributed to it.
        binding_consumers: Binding id → its consumer id.
        unattributed_clients: ``(day, client_kind, client_key)`` → the accepted calls no binding
            matched, by the client key that could later identify them (CDG-3.5).
    """

    received: int = 0
    accepted: int = 0
    sampled_out: int = 0
    unmatched: int = 0
    rejected: int = 0
    scrub_findings: int = 0
    rejections: List[Tuple[int, str]] = field(default_factory=list)
    hourly: Dict[Tuple[str, datetime, Optional[str], str, int, Optional[str]], HourlyCounter] = field(
        default_factory=dict
    )
    unmatched_rows: Dict[Tuple[str, date, str, str], UnmatchedCounter] = field(default_factory=dict)
    field_groups: Dict[Tuple[str, date, str, str, int], FieldGroup] = field(default_factory=dict)
    samples: List[Tuple[str, datetime, Optional[str], int, Dict[str, Any]]] = field(default_factory=list)
    samples_dropped: int = 0
    sampling_rate: float = 1.0
    attributed: int = 0
    binding_matches: Dict[str, datetime] = field(default_factory=dict)
    binding_consumers: Dict[str, str] = field(default_factory=dict)
    unattributed_clients: Dict[Tuple[date, str, str], UnattributedCounter] = field(default_factory=dict)

    @property
    def basis(self) -> str:
        """``sampled`` when counts were scaled from a head sample, ``complete`` otherwise."""
        return BASIS_SAMPLED if self.sampling_rate < 1 else BASIS_COMPLETE

    def reject(self, index: int, reason: str) -> None:
        """Record one rejected event."""
        self.rejected += 1
        self.rejections.append((index, reason))

    def ledger_counts(self) -> Dict[str, int]:
        """The ledger's counters; they always add up to ``received``."""
        return {
            "received": self.received,
            "accepted": self.accepted,
            "sampled_out": self.sampled_out,
            "unmatched": self.unmatched,
            "rejected": self.rejected,
            "scrub_findings": self.scrub_findings,
        }


def _hour_of(moment: datetime) -> datetime:
    """The start of the UTC hour ``moment`` falls in."""
    utc = moment.astimezone(timezone.utc)
    return utc.replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class _BuiltEvent:
    """One raw event validated against the contract, with what was held aside for scrubbing."""

    event: UsageEvent
    query_names: List[str]
    user_agent: Optional[str]
    sample: Optional[Mapping[str, Any]]


def _build_event(raw: Any, source: SourceConfig) -> Tuple[Optional[_BuiltEvent], Optional[str]]:
    """Validate one raw event against the contract, filling the source's defaults.

    ``source_id``, ``environment`` and ``schema`` may be omitted (the batch names the source).
    The query string is split off the path here, **before** the event is built, so a query value
    never reaches a :class:`UsageEvent`. The user agent is held aside unvalidated, because the
    contract caps it at 256 characters and the edge must scrub it *before* it truncates it (a
    token cut in half can no longer be recognized).

    Returns:
        ``(built event, None)``, or ``(None, reason)`` when rejected.
    """
    if not isinstance(raw, dict):
        return None, REASON_INVALID_EVENT
    payload = dict(raw)
    sample = payload.pop("sample", None)
    user_agent = payload.pop("user_agent", None)
    if (sample is not None and not isinstance(sample, dict)) or (
        user_agent is not None and not isinstance(user_agent, str)
    ):
        return None, REASON_INVALID_EVENT
    path = payload.get("path")
    names: List[str] = []
    if isinstance(path, str):
        payload["path"], names = _split_query(path)
    payload.setdefault("schema", USAGE_EVENT_SCHEMA)
    payload.setdefault("source_id", source.id)
    payload.setdefault("environment", source.environment)
    try:
        event = UsageEvent.model_validate(payload)
    except ValidationError:
        # The validation message may quote the offending value; it is never kept.
        return None, REASON_INVALID_EVENT
    if event.latency_ms > _MAX_LATENCY_MS:
        return None, REASON_INVALID_EVENT
    if str(event.source_id) != source.id:
        return None, REASON_SOURCE_MISMATCH
    if event.environment == MOCK_ENVIRONMENT and source.kind != "mock":
        return None, REASON_ENVIRONMENT_RESERVED
    return _BuiltEvent(event=event, query_names=names, user_agent=user_agent, sample=sample), None


def plan_batch(
    raw_events: Sequence[Any],
    source: SourceConfig,
    matcher: RevisionMatcher,
    *,
    now: datetime,
    is_day_finalized: Callable[[date], bool] = lambda _day: False,
    consumers: Optional[ConsumerMatcher] = None,
) -> BatchPlan:
    """Run steps 2–4 over a batch the tier cap already admitted, and plan step 5.

    Args:
        raw_events: The batch's events as parsed.
        source: The source.
        matcher: The project's published revisions.
        now: The current instant (body windows).
        is_day_finalized: Whether a UTC day is finalized; an event on one is rejected
            (``day-finalized``), since V290 refuses new counts there.
        consumers: The project's live consumer bindings (RDG-1.8). A matched event's grain carries
            the binding; an unmatched one is counted with none (the ``anonymous`` consumer).

    Returns:
        The :class:`BatchPlan`.
    """
    plan = BatchPlan(received=len(raw_events), sampling_rate=source.sampling_rate)
    take_samples = source.body_window_open(now)

    for index, raw in enumerate(raw_events):
        built, reason = _build_event(raw, source)
        if built is None:
            plan.reject(index, reason or REASON_INVALID_EVENT)
            continue
        event = built.event

        # Step 2 — head sampling, on the path as sent.
        if not head_sample_keep(source.id, event.observed_at, event.path, event.status, source.sampling_rate):
            plan.sampled_out += 1
            continue

        # Step 3 — scrubbing.
        scrubbed = scrub_event(index, event, built.query_names, built.sample, user_agent=built.user_agent)
        plan.scrub_findings += scrubbed.findings
        event = scrubbed.event

        day = event.observed_at.date()
        if is_day_finalized(day):
            plan.reject(index, REASON_DAY_FINALIZED)
            continue

        # Step 4 — template matching.
        match = matcher.match(event.method, event.path, str(event.spec_revision_id) if event.spec_revision_id else None)
        if match is None:
            template = template_path(event.path)
            if len(template) > _MAX_TEMPLATE_LENGTH or not _TEMPLATE.match(template):
                plan.reject(index, REASON_TEMPLATE_UNSTORABLE)
                continue
            plan.unmatched += 1
            key_u = (event.environment, day, event.method, template)
            counter_u = plan.unmatched_rows.get(key_u)
            if counter_u is None:
                counter_u = plan.unmatched_rows[key_u] = UnmatchedCounter(event.observed_at, event.observed_at)
            counter_u.add(event)
            _maybe_sample(plan, scrubbed, source, template, None, take_samples)
            continue

        version_id, operation_key, template = match
        if len(operation_key) > _MAX_TEMPLATE_LENGTH or not _OPERATION_KEY.match(operation_key):
            plan.reject(index, REASON_TEMPLATE_UNSTORABLE)
            continue
        plan.accepted += 1
        binding_id = _attribute(plan, consumers, event)
        key_h = (event.environment, _hour_of(event.observed_at), version_id, operation_key, event.status, binding_id)
        counter_h = plan.hourly.get(key_h)
        if counter_h is None:
            counter_h = plan.hourly[key_h] = HourlyCounter()
        counter_h.add(event)
        if source.field_capture:
            _count_fields(plan, scrubbed, day, operation_key)
        _maybe_sample(plan, scrubbed, source, template, operation_key, take_samples)

    return plan


def _attribute(plan: BatchPlan, consumers: Optional[ConsumerMatcher], event: UsageEvent) -> Optional[str]:
    """Match an accepted event to a consumer binding and note the match (RDG-1.8).

    Args:
        plan: The plan, which records the match for the ``last_matched_at`` stamps.
        consumers: The project's bindings, if any.
        event: The scrubbed event (its user agent is the scrubbed one).

    Returns:
        The binding id, or ``None`` — the call is anonymous, and still counted.
    """
    hint = event.consumer_hint
    binding = (
        consumers.match(hint.kind if hint else None, hint.hmac if hint else None, event.user_agent)
        if consumers
        else None
    )
    if binding is None:
        _note_unattributed(plan, event)
        return None
    plan.attributed += 1
    seen = plan.binding_matches.get(binding.id)
    if seen is None or event.observed_at > seen:
        plan.binding_matches[binding.id] = event.observed_at
    plan.binding_consumers[binding.id] = binding.consumer_id
    return binding.id


#: A user-agent product token the index may keep as a client key (V293's CHECK, 64 at most).
_CLIENT_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def client_token(user_agent: Optional[str]) -> Optional[str]:
    """The product token of a scrubbed user agent, as a client key (CDG-3.5).

    ``checkout-web/4.2 (linux)`` gives ``checkout-web``. A token that is not a short plain name, or
    that looks like a credential or a random string, gives ``None``: it could identify a person or
    carry a secret, and is not a consumer name anyone would register anyway.

    Args:
        user_agent: The event's user agent, already scrubbed.

    Returns:
        The lower-cased token, or ``None``.
    """
    if not user_agent:
        return None
    first = user_agent.strip().split(None, 1)[0] if user_agent.strip() else ""
    token = first.split("/", 1)[0].lower()
    if not _CLIENT_TOKEN.match(token) or _is_sensitive(token):
        return None
    return token


def unattributed_client_key(event: UsageEvent) -> Optional[Tuple[str, str]]:
    """The client key an unattributed call is counted under (CDG-3.5).

    The edge's own hint wins (it is an exact identity): ``(kind, hmac)`` for a ``header``,
    ``api_key`` or ``jwt_claim`` hint. Otherwise the user agent's product token,
    ``("user_agent", token)``. A call with neither has no key and stays only in the anonymous counts.

    Args:
        event: The scrubbed event.

    Returns:
        ``(client_kind, client_key)``, or ``None``.
    """
    hint = event.consumer_hint
    if hint is not None and hint.kind != "user_agent":
        return hint.kind, hint.hmac
    token = client_token(event.user_agent)
    return ("user_agent", token) if token else None


def _note_unattributed(plan: BatchPlan, event: UsageEvent) -> None:
    """Count an accepted call no binding matched under its client key, if it has one."""
    key = unattributed_client_key(event)
    if key is None:
        return
    grain = (event.observed_at.date(), key[0], key[1])
    counter = plan.unattributed_clients.get(grain)
    if counter is None:
        counter = plan.unattributed_clients[grain] = UnattributedCounter(event.observed_at, event.observed_at)
    counter.add(event)


def _count_fields(plan: BatchPlan, scrubbed: ScrubbedEvent, day: date, operation_key: str) -> None:
    """Count a matched event's field presence (the source has ``field_capture`` on).

    Every such event is inspected on its request side — its query names (as
    ``/parameters/query:<name>``) and ``fields.request`` — and its response side —
    ``fields.response``. An event without ``fields`` counts as a call with no body fields.
    """
    event = scrubbed.event
    request = [f"{QUERY_POINTER_PREFIX}{_escape_pointer(name)}" for name in scrubbed.query_names]
    request += list(event.fields.request) if event.fields else []
    response = list(event.fields.response) if event.fields else []
    for direction, pointers in (("request", request), ("response", response)):
        group_key = (event.environment, day, operation_key, direction, event.status)
        group = plan.field_groups.get(group_key)
        if group is None:
            group = plan.field_groups[group_key] = FieldGroup()
        group.inspected += 1
        for pointer in dict.fromkeys(pointers):
            if len(pointer) <= _MAX_POINTER_LENGTH:
                group.pointers[pointer] = group.pointers.get(pointer, 0) + 1


def _maybe_sample(
    plan: BatchPlan,
    scrubbed: ScrubbedEvent,
    source: SourceConfig,
    template: str,
    operation_key: Optional[str],
    take_samples: bool,
) -> None:
    """Choose, reduce and plan a kept event's opt-in sample."""
    event = scrubbed.event
    if not take_samples or scrubbed.sample is None:
        return
    if not _body_sample_keep(source.id, event.observed_at, event.path, event.status, source.body_sample_rate):
        return
    exchange = reduce_sample(scrubbed.sample, method=event.method, path=template, status=event.status)
    if exchange is None:
        plan.samples_dropped += 1
        return
    plan.samples.append((event.environment, event.observed_at, operation_key, event.status, exchange))


def reduce_sample(sample: Mapping[str, Any], *, method: str, path: str, status: int) -> Optional[Dict[str, Any]]:
    """Reduce an opt-in sample to what ``usage_sample.exchange`` may hold, or refuse it.

    The PMR-2.4 capture reducer removes every credential header, credential-shaped field, JWT and
    personal-data value; then the finished exchange is re-scanned twice — by the capture
    re-scan (:func:`app.mock_capture.residual_credential_pointers`) and by the intake scrubber's
    named patterns — and refused if either still flags anything, or if it exceeds
    :data:`MAX_SAMPLE_BYTES`.

    Args:
        sample: ``{"request": {"headers", "body", "mediaType"}, "response": {...}}`` as sent.
        method: The event's method.
        path: The path template the event was filed under (never the raw path).
        status: The event's status.

    Returns:
        The exchange ``{"request", "response", "redaction": {"count"}}``, or ``None`` when it may
        not be stored.
    """
    request = sample.get("request") if isinstance(sample.get("request"), dict) else {}
    response = sample.get("response") if isinstance(sample.get("response"), dict) else {}

    def _headers(side: Mapping[str, Any]) -> Dict[str, str]:
        raw = side.get("headers")
        if not isinstance(raw, dict):
            return {}
        return {str(name): str(value) for name, value in raw.items()}

    def _media(side: Mapping[str, Any]) -> Optional[str]:
        value = side.get("mediaType")
        return value if isinstance(value, str) else None

    reduced = redact_exchange(
        policy=_SAMPLE_POLICY,
        method=method,
        path=path,
        # Query values were discarded before the event was built; a sample carries none either.
        query_params=(),
        request_headers=_headers(request),
        request_body=request.get("body"),
        request_media_type=_media(request),
        status=status,
        response_headers=_headers(response),
        response_body=response.get("body"),
        response_media_type=_media(response),
    )
    exchange: Dict[str, Any] = {
        "request": reduced.request,
        "response": reduced.response,
        "redaction": {"count": len(reduced.decisions)},
    }
    if residual_credential_pointers(exchange):
        return None
    # Measured the way the V290 CHECK measures it: ``jsonb::text`` writes ", " and ": ".
    text = json.dumps(exchange, separators=(", ", ": "), ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_SAMPLE_BYTES:
        return None
    if scrub_document_text(text).scrubbed or _EMAIL.search(text):
        return None
    return exchange


def rejected_plan(raw_events: Sequence[Any], reason: str) -> BatchPlan:
    """A plan that rejects every event of a batch for one reason (the tier cap).

    Args:
        raw_events: The batch's events.
        reason: The rejection reason.

    Returns:
        A :class:`BatchPlan` with ``rejected == received`` and nothing to write but the ledger.
    """
    plan = BatchPlan(received=len(raw_events))
    for index in range(len(raw_events)):
        plan.reject(index, reason)
    return plan
