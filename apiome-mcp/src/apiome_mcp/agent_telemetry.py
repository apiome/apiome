"""ATQ-4.4 OpenTelemetry export of agent invocations (#5846).

When ``APIOME_MCP_OTEL_EXPORTER_OTLP_ENDPOINT`` is set, every agent ``tools/call`` becomes one OTLP
trace and two metric points, sent over OTLP/HTTP to that collector. Unset (the default), nothing is
created and every hook is a no-op (:data:`NOOP_TELEMETRY`).

**Spans.** One ``apiome.agent.invocation`` span (kind ``SERVER``) per call, with two children:

* ``vault.resolve`` (``INTERNAL``): opening the AGX-2.2 upstream credential, ``prod`` only;
* ``upstream.request`` (``CLIENT``): the upstream HTTP request, retries included.

The parent's attributes are **exactly the AGX-3.3 audit row** (:class:`InvocationRecord`), one
``apiome.agent.<column>`` attribute per column (:data:`AUDIT_COLUMNS`), set from the very record
the audit writes. A column the record does not carry yet (``via``, ``version_id``,
``compile_fingerprint``, ``failure_class``, added by ATQ-4.1/4.2) is simply absent.

**Metrics.** A counter ``apiome.agent.invocations`` and a histogram ``apiome.agent.latency_ms``.
Their labels are the span's categorical attributes **minus the key id** (one series per key would
explode a backend's cardinality) and minus the measured numbers (latency and bytes).

**Parents.** An inbound W3C ``traceparent`` / ``tracestate`` (HTTP headers first, then the
request's ``_meta``, where the 2026-07-28 transport carries them) parents the invocation span, and
the caller's sampling decision is honoured (:func:`trace_carrier`).

**What never becomes telemetry.** Arguments, bodies, headers, URLs, credentials and exception
messages. Only the audit row's metadata and the fixed attributes below are ever set; a failed call
gets status ``ERROR`` with its machine ``error_code`` as the description, never an exception event.

**Failure isolation.** Telemetry never fails a call (the AGX-3.3 audit rule): every hook catches
and logs its own errors, and the exporters run in background threads with a bounded timeout.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

import structlog
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer, TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from apiome_mcp import __version__

if TYPE_CHECKING:
    from apiome_mcp.agent_invocations import InvocationRecord
    from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

__all__ = [
    "AUDIT_COLUMNS",
    "METRIC_INVOCATIONS",
    "METRIC_LATENCY",
    "NOOP_TELEMETRY",
    "SPAN_INVOCATION",
    "SPAN_UPSTREAM",
    "SPAN_VAULT",
    "AgentTelemetry",
    "ChildSpan",
    "InvocationSpan",
    "invocation_attributes",
    "metric_attributes",
    "parse_otlp_headers",
    "telemetry_from_settings",
    "trace_carrier",
]

SPAN_INVOCATION = "apiome.agent.invocation"
SPAN_UPSTREAM = "upstream.request"
SPAN_VAULT = "vault.resolve"
METRIC_INVOCATIONS = "apiome.agent.invocations"
METRIC_LATENCY = "apiome.agent.latency_ms"

#: The audit row's columns, in table order. Each becomes ``apiome.agent.<column>``. The last four
#: arrive with ATQ-4.1 / ATQ-4.2 and are read from the record only once it has them.
AUDIT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "key_id",
    "toolset_id",
    "tool_name",
    "target",
    "outcome",
    "error_code",
    "http_status",
    "latency_ms",
    "request_bytes",
    "response_bytes",
    "sampled",
    "via",
    "version_id",
    "compile_fingerprint",
    "failure_class",
)

#: Columns never used as metric labels: the key (cardinality) and the measured numbers.
_NOT_LABELS = frozenset(
    f"apiome.agent.{column}" for column in ("key_id", "latency_ms", "request_bytes", "response_bytes")
)

#: The two W3C trace-context fields, and the longest value accepted for either.
_TRACE_FIELDS = ("traceparent", "tracestate")
_MAX_TRACE_FIELD = 512

_PROPAGATOR = TraceContextTextMapPropagator()


def _attribute_value(value: Any) -> str | int | float | bool | None:
    """An OTel-safe scalar for one audit value (enums by value, anything else as text)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str | int):
        return enum_value
    return str(value)


def invocation_attributes(record: InvocationRecord) -> dict[str, str | int | float | bool]:
    """The ``apiome.agent.invocation`` span's attributes: one per audit column that has a value.

    Args:
        record: The audit row the call wrote.

    Returns:
        ``{"apiome.agent.<column>": value}`` for every column in :data:`AUDIT_COLUMNS` the record
        carries and that is not ``None``.
    """
    attributes: dict[str, str | int | float | bool] = {}
    for column in AUDIT_COLUMNS:
        value = _attribute_value(getattr(record, column, None))
        if value is not None:
            attributes[f"apiome.agent.{column}"] = value
    return attributes


def metric_attributes(record: InvocationRecord) -> dict[str, str | int | float | bool]:
    """The metric labels: the span attributes minus the key id and the measured numbers.

    Args:
        record: The audit row the call wrote.

    Returns:
        The labels for ``apiome.agent.invocations`` and ``apiome.agent.latency_ms``.
    """
    return _labels(invocation_attributes(record))


def _labels(attributes: Mapping[str, str | int | float | bool]) -> dict[str, str | int | float | bool]:
    """The metric labels of an already-built attribute set (see :func:`metric_attributes`)."""
    return {name: value for name, value in attributes.items() if name not in _NOT_LABELS}


def _field(source: Any, name: str) -> str | None:
    """Read one trace field from a mapping or a pydantic ``_meta`` model; strings only, bounded."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        value = source.get(name)
    else:
        value = getattr(source, name, None)
        if value is None:
            extra = getattr(source, "model_extra", None)
            value = extra.get(name) if isinstance(extra, Mapping) else None
    if not isinstance(value, str) or not value or len(value) > _MAX_TRACE_FIELD:
        return None
    return value


def trace_carrier(headers: Mapping[str, str] | None, meta: Any = None) -> dict[str, str] | None:
    """The W3C trace context a call arrived with: HTTP headers first, then ``params._meta``.

    Args:
        headers: The request's HTTP headers (any case), or ``None`` on a transport without them.
        meta: The request's ``_meta`` (a mapping or the MCP SDK's model), or ``None``.

    Returns:
        ``{"traceparent": …, "tracestate": …}`` (``tracestate`` only when sent), or ``None`` when
        neither source carries a ``traceparent``. The values are not validated here; the W3C
        propagator ignores a malformed one.
    """
    lowered = {key.lower(): value for key, value in (headers or {}).items()}
    for source in (lowered, meta):
        parent = _field(source, "traceparent")
        if parent is not None:
            carrier = {"traceparent": parent}
            state = _field(source, "tracestate")
            if state is not None:
                carrier["tracestate"] = state
            return carrier
    return None


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    """Parse ``key=value,key2=value2`` (the ``OTEL_EXPORTER_OTLP_HEADERS`` format, URL-decoded).

    A pair without ``=`` or with an empty key is skipped; values are never logged.

    Args:
        raw: The configured headers, or ``None``.

    Returns:
        The headers.
    """
    headers: dict[str, str] = {}
    for pair in (raw or "").split(","):
        key, sep, value = pair.partition("=")
        key = unquote(key.strip())
        if not sep or not key:
            continue
        headers[key] = unquote(value.strip())
    return headers


class ChildSpan:
    """One child span (``vault.resolve`` or ``upstream.request``) of the call in flight."""

    def __init__(self, span: Span | None) -> None:
        """Wrap ``span`` (``None`` when telemetry is off or the span could not start)."""
        self._span = span

    def set(self, name: str, value: str | int | float | bool | None) -> None:
        """Set one attribute (ignored when ``value`` is ``None`` or telemetry is off).

        Callers only ever pass the fixed, non-secret attributes this module documents.
        """
        if self._span is None or value is None:
            return
        try:
            self._span.set_attribute(name, value)
        except Exception:
            _log.warning("agent_telemetry_attribute_failed", exc_info=True)

    def fail(self, error_type: str) -> None:
        """Mark the step failed with a machine ``error.type`` (e.g. ``timeout``)."""
        if self._span is None:
            return
        try:
            self._span.set_attribute("error.type", error_type)
            self._span.set_status(Status(StatusCode.ERROR, error_type))
        except Exception:
            _log.warning("agent_telemetry_status_failed", exc_info=True)


class InvocationSpan:
    """The ``apiome.agent.invocation`` span of one call; :meth:`record` closes the loop with the audit."""

    def __init__(self, telemetry: AgentTelemetry, span: Span | None) -> None:
        """Wrap ``span`` (``None`` when telemetry is off or the span could not start)."""
        self._telemetry = telemetry
        self._span = span

    def record(self, record: InvocationRecord) -> None:
        """Copy the audit row onto the span and count it. Never raises.

        Args:
            record: The row :class:`~apiome_mcp.agent_invocations.InvocationAudit` is writing.
        """
        self._telemetry.observe(record, self._span)


class AgentTelemetry:
    """Spans and metrics for agent invocations, on providers this instance owns.

    The providers are kept local rather than installed globally, so another library's OTel setup
    is never replaced. Build it with :func:`telemetry_from_settings`; tests pass in-memory providers.
    """

    enabled = True

    def __init__(self, tracer_provider: TracerProvider, meter_provider: MeterProvider) -> None:
        """Create the tracer, the counter and the histogram.

        Args:
            tracer_provider: Where spans go.
            meter_provider: Where metric points go.
        """
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._tracer: Tracer = tracer_provider.get_tracer("apiome_mcp.agent_telemetry", __version__)
        meter: Meter = meter_provider.get_meter("apiome_mcp.agent_telemetry", __version__)
        self._invocations = meter.create_counter(
            METRIC_INVOCATIONS, unit="{invocation}", description="Agent tools/call invocations."
        )
        self._latency = meter.create_histogram(
            METRIC_LATENCY, unit="ms", description="Wall-clock duration of agent tools/call invocations."
        )

    @contextmanager
    def invocation(self, carrier: Mapping[str, str] | None = None) -> Iterator[InvocationSpan]:
        """Open the call's span (current for the block, so children nest under it).

        The block's own exceptions pass through untouched; only telemetry errors are swallowed.

        Args:
            carrier: The inbound W3C trace context (:func:`trace_carrier`), or ``None``.

        Yields:
            The span handle; report the audit row to it with :meth:`InvocationSpan.record`.
        """
        span: Span | None = None
        token: object | None = None
        try:
            parent = _PROPAGATOR.extract(carrier) if carrier else None
            span = self._tracer.start_span(SPAN_INVOCATION, context=parent, kind=SpanKind.SERVER)
            token = otel_context.attach(trace.set_span_in_context(span))
        except Exception:
            _log.warning("agent_telemetry_span_failed", exc_info=True)
        try:
            yield InvocationSpan(self, span)
        finally:
            _close(span, token)

    @contextmanager
    def child(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Mapping[str, str | int | float | bool] | None = None,
    ) -> Iterator[ChildSpan]:
        """Open a child of the current invocation span.

        Args:
            name: :data:`SPAN_VAULT` or :data:`SPAN_UPSTREAM`.
            kind: The span kind.
            attributes: Fixed, non-secret attributes known when the step starts.

        Yields:
            The child handle.
        """
        span: Span | None = None
        try:
            span = self._tracer.start_span(name, kind=kind, attributes=attributes)
        except Exception:
            _log.warning("agent_telemetry_span_failed", exc_info=True)
        try:
            yield ChildSpan(span)
        finally:
            _close(span, None)

    def observe(self, record: InvocationRecord, span: Span | None) -> None:
        """Set the audit row on ``span`` and record both metrics. Never raises.

        Args:
            record: The audit row.
            span: The invocation span, or ``None``.
        """
        try:
            attributes = invocation_attributes(record)
            if span is not None:
                span.set_attributes(attributes)
                if record.error_code is not None:
                    span.set_status(Status(StatusCode.ERROR, record.error_code))
            labels = _labels(attributes)
            self._invocations.add(1, labels)
            self._latency.record(record.latency_ms, labels)
        except Exception:
            _log.warning("agent_telemetry_record_failed", exc_info=True)

    def flush(self) -> None:
        """Export everything recorded so far (bounded by the export timeout). Never raises."""
        for provider in (self._tracer_provider, self._meter_provider):
            force = getattr(provider, "force_flush", None)
            if force is None:
                continue
            try:
                force()
            except Exception:
                _log.warning("agent_telemetry_flush_failed", exc_info=True)

    def shutdown(self) -> None:
        """Flush and stop both providers (bounded by the export timeout). Never raises."""
        for provider in (self._tracer_provider, self._meter_provider):
            stop = getattr(provider, "shutdown", None)
            if stop is None:
                continue
            try:
                stop()
            except Exception:
                _log.warning("agent_telemetry_shutdown_failed", exc_info=True)


def _close(span: Span | None, token: object | None) -> None:
    """Detach the context and end the span, swallowing telemetry errors."""
    try:
        if token is not None:
            otel_context.detach(token)  # type: ignore[arg-type]
        if span is not None:
            span.end()
    except Exception:
        _log.warning("agent_telemetry_span_end_failed", exc_info=True)


class _NoopTelemetry(AgentTelemetry):
    """Telemetry switched off: no providers, no spans, no metrics, no cost."""

    enabled = False

    def __init__(self) -> None:  # noqa: D107 - nothing to create
        pass

    @contextmanager
    def invocation(self, carrier: Mapping[str, str] | None = None) -> Iterator[InvocationSpan]:
        """Yield a handle that records nothing."""
        yield InvocationSpan(self, None)

    @contextmanager
    def child(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Mapping[str, str | int | float | bool] | None = None,
    ) -> Iterator[ChildSpan]:
        """Yield a handle that records nothing."""
        yield _NOOP_CHILD

    def observe(self, record: InvocationRecord, span: Span | None) -> None:
        """Record nothing."""

    def flush(self) -> None:
        """Nothing to flush."""

    def shutdown(self) -> None:
        """Nothing to flush."""


_NOOP_CHILD = ChildSpan(None)

#: The telemetry used when no endpoint is configured.
NOOP_TELEMETRY: AgentTelemetry = _NoopTelemetry()


def telemetry_from_settings(settings: Settings) -> AgentTelemetry:
    """Build the process's telemetry from ``APIOME_MCP_OTEL_*``.

    Without an endpoint this is :data:`NOOP_TELEMETRY` and the OTel SDK is not even imported.
    With one: a parent-based trace-ID-ratio sampler, batched OTLP/HTTP span export to
    ``{endpoint}/v1/traces`` and periodic metric export to ``{endpoint}/v1/metrics``, both with the
    configured headers and timeout.

    Args:
        settings: Process settings.

    Returns:
        The telemetry. A configuration that cannot be built falls back to :data:`NOOP_TELEMETRY`
        with a warning, so the runtime still starts.
    """
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return NOOP_TELEMETRY
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        secret = settings.otel_exporter_otlp_headers
        headers = parse_otlp_headers(secret.get_secret_value() if secret else None)
        timeout = settings.otel_export_timeout_seconds
        resource = Resource.create({"service.name": settings.otel_service_name, "service.version": __version__})
        tracer_provider = SdkTracerProvider(
            resource=resource, sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_ratio))
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers, timeout=timeout),
                export_timeout_millis=timeout * 1000,
            )
        )
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", headers=headers, timeout=timeout),
            export_interval_millis=settings.otel_metric_export_interval_seconds * 1000,
            export_timeout_millis=timeout * 1000,
        )
        meter_provider = SdkMeterProvider(resource=resource, metric_readers=[reader])
    except Exception:
        _log.warning("agent_telemetry_disabled", reason="configuration_failed", exc_info=True)
        return NOOP_TELEMETRY
    # Only the host: an endpoint may carry credentials in its userinfo.
    _log.info(
        "agent_telemetry_enabled", host=urlsplit(endpoint).hostname, sampler_ratio=settings.otel_traces_sampler_ratio
    )
    return AgentTelemetry(tracer_provider, meter_provider)
