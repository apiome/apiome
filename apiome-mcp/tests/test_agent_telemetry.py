"""ATQ-4.4 OpenTelemetry export of agent invocations (#5846).

Runs the real :class:`~apiome_mcp.agent_invocation_proxy.InvocationProxy` against the in-memory
Petstore upstream and the recording pool, with telemetry exporting either to in-memory readers or,
for the acceptance criteria, over real OTLP/HTTP to the in-process collector stub. Pins:

* one ``apiome.agent.invocation`` span with ``vault.resolve`` and ``upstream.request`` children,
  whose attributes are exactly the audit row the call wrote;
* the counter and histogram, labelled like the span minus the key id and the measured numbers;
* an inbound ``traceparent`` (HTTP header or ``_meta``) parents the span and decides sampling;
* the exporter or the SDK failing never fails the call, and the audit row is still written;
* the secret sweep (extending AGX-2.2's): no exported byte carries an argument, a body, a header,
  an upstream credential or a URL;
* settings: off by default, the endpoint validated, OTLP headers parsed.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.upstream_credential_binding import CredentialInjection
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import ValidationError

from agent_runtime_fakes import (
    KEY_ID,
    TENANT_ID,
    TOOLSET_ID,
    AgentDb,
    PetstoreUpstream,
    invocation_rows,
    manifest_row,
)
from apiome_mcp.agent_access import AgentKey
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_invocations import InvocationOutcome, InvocationRecord
from apiome_mcp.agent_telemetry import (
    AUDIT_COLUMNS,
    METRIC_INVOCATIONS,
    METRIC_LATENCY,
    NOOP_TELEMETRY,
    SPAN_INVOCATION,
    SPAN_UPSTREAM,
    SPAN_VAULT,
    AgentTelemetry,
    invocation_attributes,
    metric_attributes,
    parse_otlp_headers,
    telemetry_from_settings,
    trace_carrier,
)
from apiome_mcp.agent_toolset_source import ServedToolsetCache, load_served_toolset
from apiome_mcp.agent_upstream_auth import UpstreamCredentialUnavailableError
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy
from apiome_mcp.settings import Settings
from otlp_collector_stub import attributes, otlp_collector

KEY = AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=frozenset())
CONFIG = InvocationConfig(
    policy=UpstreamCallPolicy(timeout_seconds=0.5, budget_seconds=1.0, backoff_seconds=0.0),
    mock_base_url="http://mock.internal:8775",
)
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
PARENT_ID = "b7ad6b7169203331"
SAMPLED = f"00-{TRACE_ID}-{PARENT_ID}-01"

UPSTREAM_SECRET = "sk_live_upstream_value_123"
QUERY_SECRET = "q/secret+value-987"
ARGUMENT_MARKER = "argument-marker-5f1c"
BODY_MARKER = "body-marker-7a2e"


class _Vault:
    """A credential source: an injection, nothing, or 'cannot open'."""

    def __init__(self, injection: CredentialInjection | None = None, *, broken: bool = False) -> None:
        self.injection = injection
        self.broken = broken

    async def __call__(self, pool: Any, tenant_id: str, toolset_id: str, url: str) -> CredentialInjection | None:
        if self.broken:
            raise UpstreamCredentialUnavailableError("cred")
        return self.injection


def _memory_telemetry() -> tuple[AgentTelemetry, InMemorySpanExporter, InMemoryMetricReader]:
    """Telemetry that keeps every span and metric in memory (always sampled)."""
    spans = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    return AgentTelemetry(tracer_provider, MeterProvider(metric_readers=[reader])), spans, reader


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@localhost/db", internal_secret="x" * 16, **overrides)


def _call(
    telemetry: AgentTelemetry,
    tool: str = "showPetById",
    arguments: dict[str, Any] | None = None,
    *,
    target: str = "prod",
    vault: _Vault | None = None,
    upstream: PetstoreUpstream | None = None,
    trace_context: dict[str, str] | None = None,
) -> tuple[Any, Any]:
    """Run one proxied call with ``telemetry``; return ``(result, pool)``."""
    db = AgentDb(manifest=manifest_row(target=target))
    upstream = upstream or PetstoreUpstream()
    pool = db.pool()
    proxy = InvocationProxy(CONFIG, credentials=vault or _Vault(), telemetry=telemetry)

    async def run() -> Any:
        served = await load_served_toolset(pool, ServedToolsetCache(), TENANT_ID, TOOLSET_ID)  # type: ignore[arg-type]
        assert served is not None
        async with upstream.client() as client:
            return await proxy.invoke(
                pool=pool,  # type: ignore[arg-type]
                client=client,
                key=KEY,
                toolset=served,
                tool=served.tools[tool],
                arguments={"petId": "1"} if arguments is None else arguments,
                trace_context=trace_context,
            )

    return asyncio.run(run()), pool


def _by_name(spans: Any) -> dict[str, Any]:
    named = {span.name: span for span in spans}
    assert len(named) == len(spans), [span.name for span in spans]
    return named


def _metric_points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


# ============================================================================
# Spans: one parent, two children, the audit row as attributes
# ============================================================================


def test_a_prod_call_is_one_invocation_span_with_vault_and_upstream_children() -> None:
    telemetry, spans, _ = _memory_telemetry()
    injection = CredentialInjection(credential_id="c", headers=(("X-Api-Key", UPSTREAM_SECRET),))
    result, pool = _call(telemetry, vault=_Vault(injection))
    assert result.structured_content["httpStatus"] == 200

    named = _by_name(spans.get_finished_spans())
    assert set(named) == {SPAN_INVOCATION, SPAN_VAULT, SPAN_UPSTREAM}
    parent, vault, upstream = named[SPAN_INVOCATION], named[SPAN_VAULT], named[SPAN_UPSTREAM]
    assert parent.parent is None and parent.kind is SpanKind.SERVER
    for child in (vault, upstream):
        assert child.parent.span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id
    assert (vault.kind, upstream.kind) == (SpanKind.INTERNAL, SpanKind.CLIENT)
    assert dict(vault.attributes) == {"apiome.agent.credential_injected": True}
    assert dict(upstream.attributes) == {"http.request.method": "GET", "http.response.status_code": 200}

    (row,) = invocation_rows(pool)
    expected = {
        f"apiome.agent.{column}": row[column]
        for column in ("tenant_id", "key_id", "toolset_id", "tool_name", "target", "outcome", "http_status")
    }
    expected.update(
        {
            "apiome.agent.latency_ms": row["latency_ms"],
            "apiome.agent.request_bytes": row["request_bytes"],
            "apiome.agent.response_bytes": row["response_bytes"],
            "apiome.agent.sampled": row["sampled"],
        }
    )
    assert dict(parent.attributes) == expected
    assert parent.status.status_code is StatusCode.UNSET


def test_a_mock_call_has_no_vault_span() -> None:
    telemetry, spans, _ = _memory_telemetry()
    _call(telemetry, "listPets", {}, target="mock")
    assert set(_by_name(spans.get_finished_spans())) == {SPAN_INVOCATION, SPAN_UPSTREAM}


def test_a_failed_call_carries_its_error_code_and_the_failed_step() -> None:
    telemetry, spans, _ = _memory_telemetry()
    _, pool = _call(telemetry, "listPets", {}, vault=_Vault(broken=True))
    named = _by_name(spans.get_finished_spans())
    assert set(named) == {SPAN_INVOCATION, SPAN_VAULT}
    parent = named[SPAN_INVOCATION]
    assert parent.attributes["apiome.agent.outcome"] == "internal_error"
    assert parent.attributes["apiome.agent.error_code"] == "upstream_credential_unavailable"
    assert (parent.status.status_code, parent.status.description) == (
        StatusCode.ERROR,
        "upstream_credential_unavailable",
    )
    assert named[SPAN_VAULT].attributes["error.type"] == "credential_unavailable"
    assert invocation_rows(pool)[0]["error_code"] == "upstream_credential_unavailable"


def test_an_upstream_5xx_marks_the_upstream_span() -> None:
    upstream = PetstoreUpstream()
    upstream.override = lambda request: httpx.Response(503, json={"error": "down"})
    telemetry, spans, _ = _memory_telemetry()
    _call(telemetry, "listPets", {}, upstream=upstream)
    span = _by_name(spans.get_finished_spans())[SPAN_UPSTREAM]
    assert span.attributes["http.response.status_code"] == 503
    assert span.status.status_code is StatusCode.ERROR


def test_an_argument_failure_never_opens_a_child() -> None:
    telemetry, spans, _ = _memory_telemetry()
    _call(telemetry, "showPetById", {"petId": ".."})
    (parent,) = spans.get_finished_spans()
    assert parent.attributes["apiome.agent.outcome"] == "validation_failure"


# ============================================================================
# Parents: inbound traceparent
# ============================================================================


def test_an_inbound_traceparent_parents_the_invocation_span() -> None:
    telemetry, spans, _ = _memory_telemetry()
    _call(telemetry, "listPets", {}, target="mock", trace_context={"traceparent": SAMPLED})
    parent = _by_name(spans.get_finished_spans())[SPAN_INVOCATION]
    assert format(parent.context.trace_id, "032x") == TRACE_ID
    assert format(parent.parent.span_id, "016x") == PARENT_ID
    assert parent.parent.is_remote


def test_an_unsampled_caller_is_not_traced_but_still_counted() -> None:
    with otlp_collector() as (url, collected):
        telemetry = telemetry_from_settings(_settings(otel_exporter_otlp_endpoint=url, otel_traces_sampler_ratio=1.0))
        _call(telemetry, "listPets", {}, target="mock", trace_context={"traceparent": SAMPLED[:-2] + "00"})
        telemetry.shutdown()
    assert collected.spans() == []
    assert sum(point.as_int for point in collected.metric_points(METRIC_INVOCATIONS)) == 1


def test_a_malformed_traceparent_starts_a_new_trace() -> None:
    telemetry, spans, _ = _memory_telemetry()
    _call(telemetry, "listPets", {}, target="mock", trace_context={"traceparent": "not-a-trace"})
    parent = _by_name(spans.get_finished_spans())[SPAN_INVOCATION]
    assert parent.parent is None


@pytest.mark.parametrize(
    ("headers", "meta", "expected"),
    [
        ({"TraceParent": SAMPLED, "tracestate": "a=1"}, None, {"traceparent": SAMPLED, "tracestate": "a=1"}),
        ({"traceparent": SAMPLED}, {"traceparent": "00-other"}, {"traceparent": SAMPLED}),
        ({}, {"traceparent": SAMPLED, "tracestate": "b=2"}, {"traceparent": SAMPLED, "tracestate": "b=2"}),
        (None, SimpleNamespace(traceparent=SAMPLED), {"traceparent": SAMPLED}),
        (None, SimpleNamespace(model_extra={"traceparent": SAMPLED}), {"traceparent": SAMPLED}),
        ({"user-agent": "x"}, None, None),
        ({"traceparent": "x" * 600}, None, None),
        ({}, {"traceparent": 7}, None),
    ],
)
def test_the_trace_context_comes_from_headers_then_meta(headers: Any, meta: Any, expected: Any) -> None:
    assert trace_carrier(headers, meta) == expected


# ============================================================================
# Metrics
# ============================================================================


def test_metrics_count_every_call_without_the_key_id() -> None:
    telemetry, _, reader = _memory_telemetry()
    _call(telemetry, "listPets", {}, target="mock")
    _call(telemetry, "listPets", {}, target="mock")
    (counter,) = _metric_points(reader, METRIC_INVOCATIONS)
    (histogram,) = _metric_points(reader, METRIC_LATENCY)
    assert counter.value == 2 and histogram.count == 2
    labels = dict(counter.attributes)
    assert labels == dict(histogram.attributes)
    assert "apiome.agent.key_id" not in labels
    assert not {"apiome.agent.latency_ms", "apiome.agent.request_bytes", "apiome.agent.response_bytes"} & set(labels)
    assert labels["apiome.agent.tool_name"] == "listPets" and labels["apiome.agent.outcome"] == "success"


def _record(**overrides: Any) -> InvocationRecord:
    from datetime import UTC, datetime

    values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "key_id": KEY_ID,
        "toolset_id": TOOLSET_ID,
        "tool_name": "listPets",
        "target": "prod",
        "invoked_at": datetime.now(UTC),
        "latency_ms": 12,
        "outcome": InvocationOutcome.UPSTREAM_ERROR,
        "error_code": "upstream_500",
        "http_status": 500,
        "request_bytes": 2,
        "response_bytes": 40,
    }
    values.update(overrides)
    return InvocationRecord(**values)


def test_the_attributes_name_every_audit_column_and_skip_empty_ones() -> None:
    attrs = invocation_attributes(_record(error_code=None, http_status=None, outcome=InvocationOutcome.SUCCESS))
    assert "apiome.agent.error_code" not in attrs and "apiome.agent.http_status" not in attrs
    assert attrs["apiome.agent.outcome"] == "success"
    assert set(attrs) <= {f"apiome.agent.{column}" for column in AUDIT_COLUMNS}


def test_the_atq_4_1_and_4_2_columns_appear_once_the_record_carries_them() -> None:
    values = {column: getattr(_record(), column, None) for column in AUDIT_COLUMNS}
    values.update(via="mcp", version_id="v1", compile_fingerprint="sha256:abc", failure_class="upstream")
    later = SimpleNamespace(**values)
    attrs = invocation_attributes(later)  # type: ignore[arg-type]
    assert {attrs[f"apiome.agent.{c}"] for c in ("via", "version_id", "compile_fingerprint", "failure_class")} == {
        "mcp",
        "v1",
        "sha256:abc",
        "upstream",
    }
    assert metric_attributes(later)["apiome.agent.failure_class"] == "upstream"  # type: ignore[arg-type]


# ============================================================================
# Failure isolation: telemetry never fails a call
# ============================================================================


def test_a_collector_that_refuses_every_export_never_fails_a_call() -> None:
    with otlp_collector(fail=True) as (url, _):
        telemetry = telemetry_from_settings(
            _settings(otel_exporter_otlp_endpoint=url, otel_traces_sampler_ratio=1.0, otel_export_timeout_seconds=1)
        )
        result, pool = _call(telemetry, "listPets", {}, target="mock")
        telemetry.flush()
        telemetry.shutdown()
    assert result.structured_content["httpStatus"] == 200
    assert invocation_rows(pool)[0]["outcome"] == "success"


def test_an_unreachable_collector_never_fails_a_call() -> None:
    telemetry = telemetry_from_settings(
        _settings(otel_exporter_otlp_endpoint="http://127.0.0.1:9", otel_export_timeout_seconds=0.5)
    )
    result, pool = _call(telemetry, "listPets", {}, target="mock")
    telemetry.shutdown()
    assert result.structured_content["httpStatus"] == 200
    assert len(invocation_rows(pool)) == 1


def test_a_broken_sdk_never_fails_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry, _, _ = _memory_telemetry()

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("sdk broken")

    monkeypatch.setattr(telemetry._tracer, "start_span", boom)
    monkeypatch.setattr(telemetry._invocations, "add", boom)
    result, pool = _call(telemetry, "listPets", {}, target="mock")
    assert result.structured_content["httpStatus"] == 200
    assert invocation_rows(pool)[0]["outcome"] == "success"


# ============================================================================
# Acceptance: an in-process OTLP collector receives the documented spans and metrics
# ============================================================================


def test_the_otlp_collector_receives_one_parent_two_children_and_both_metrics() -> None:
    with otlp_collector() as (url, collected):
        telemetry = telemetry_from_settings(
            _settings(
                otel_exporter_otlp_endpoint=url + "/",
                otel_exporter_otlp_headers="x-honeycomb-team=team%20key,bad,=x",
                otel_traces_sampler_ratio=1.0,
                otel_service_name="agent-runtime",
            )
        )
        injection = CredentialInjection(credential_id="c", headers=(("X-Api-Key", UPSTREAM_SECRET),))
        _, pool = _call(telemetry, vault=_Vault(injection), trace_context={"traceparent": SAMPLED})
        telemetry.shutdown()

    spans = {span.name: span for span in collected.spans()}
    assert set(spans) == {SPAN_INVOCATION, SPAN_VAULT, SPAN_UPSTREAM}
    parent = spans[SPAN_INVOCATION]
    assert parent.trace_id.hex() == TRACE_ID and parent.parent_span_id.hex() == PARENT_ID
    for name in (SPAN_VAULT, SPAN_UPSTREAM):
        assert spans[name].parent_span_id == parent.span_id
    (row,) = invocation_rows(pool)
    assert attributes(parent)["apiome.agent.key_id"] == row["key_id"]
    assert attributes(parent)["apiome.agent.outcome"] == "success"
    resource = {kv.key: kv.value.string_value for kv in collected.traces[0].resource_spans[0].resource.attributes}
    assert resource["service.name"] == "agent-runtime"
    assert all(headers.get("x-honeycomb-team") == "team key" for headers in collected.headers)
    (point,) = collected.metric_points(METRIC_INVOCATIONS)
    assert point.as_int == 1 and "apiome.agent.key_id" not in attributes(point)
    (latency,) = collected.metric_points(METRIC_LATENCY)
    assert latency.count == 1


# ============================================================================
# Secret sweep (extends AGX-2.2's): nothing secret or caller-supplied is ever exported
# ============================================================================


@pytest.mark.parametrize(
    "injection",
    [
        CredentialInjection(credential_id="c", headers=(("Authorization", f"Bearer {UPSTREAM_SECRET}"),)),
        CredentialInjection(credential_id="c", query=(("api_key", QUERY_SECRET),)),
    ],
)
def test_no_exported_byte_carries_a_secret_an_argument_a_body_or_a_url(injection: CredentialInjection) -> None:
    upstream = PetstoreUpstream()
    upstream.override = lambda request: httpx.Response(
        500,
        json={"echo": str(request.url), "auth": request.headers.get("authorization"), "note": BODY_MARKER},
        headers={"X-Echo": request.headers.get("authorization") or str(request.url)},
    )
    with otlp_collector() as (url, collected):
        telemetry = telemetry_from_settings(_settings(otel_exporter_otlp_endpoint=url, otel_traces_sampler_ratio=1.0))
        _call(
            telemetry,
            "listPets",
            {"tags": [ARGUMENT_MARKER]},
            vault=_Vault(injection),
            upstream=upstream,
            trace_context={"traceparent": SAMPLED, "tracestate": "vendor=" + ARGUMENT_MARKER[:8]},
        )
        telemetry.shutdown()
    assert len(collected.spans()) == 3
    exported = b"".join(collected.raw)
    readable = json.dumps([str(span) for span in collected.spans()])
    forbidden = (
        UPSTREAM_SECRET,
        QUERY_SECRET,
        "q%2Fsecret%2Bvalue-987",
        ARGUMENT_MARKER,
        BODY_MARKER,
        "api.petstore.example",
        "Bearer",
    )
    for needle in forbidden:
        assert needle.encode() not in exported, needle
        assert needle not in readable, needle


def test_the_telemetry_module_never_reads_a_body_an_argument_or_a_header() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/apiome_mcp/agent_telemetry.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]  # skip the module docstring, which names what is excluded
    for name in ("request_body", "response_body", "arguments", "attach_bodies", "injection", ".headers", "url("):
        assert name not in code, name


# ============================================================================
# Settings
# ============================================================================


def test_telemetry_is_off_by_default() -> None:
    settings = _settings()
    assert settings.otel_exporter_otlp_endpoint is None
    assert telemetry_from_settings(settings) is NOOP_TELEMETRY
    assert NOOP_TELEMETRY.enabled is False
    assert settings.otel_traces_sampler_ratio == 0.25


def test_an_empty_endpoint_is_off_and_a_non_http_one_is_refused() -> None:
    assert _settings(otel_exporter_otlp_endpoint="  ").otel_exporter_otlp_endpoint is None
    assert _settings(otel_exporter_otlp_endpoint="https://otel.example:4318/").otel_exporter_otlp_endpoint == (
        "https://otel.example:4318"
    )
    with pytest.raises(ValidationError):
        _settings(otel_exporter_otlp_endpoint="grpc://otel.example:4317")
    with pytest.raises(ValidationError):
        _settings(otel_traces_sampler_ratio=1.5)


def test_the_noop_telemetry_runs_a_call_unchanged() -> None:
    result, pool = _call(NOOP_TELEMETRY, "listPets", {}, target="mock")
    assert result.structured_content["httpStatus"] == 200
    assert len(invocation_rows(pool)) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        ("", {}),
        ("api-key=abc", {"api-key": "abc"}),
        ("a=1, b = two%20words ,c=x=y", {"a": "1", "b": "two words", "c": "x=y"}),
        ("novalue,=empty", {}),
    ],
)
def test_otlp_headers_are_parsed_like_otel_exporter_otlp_headers(raw: str | None, expected: dict[str, str]) -> None:
    assert parse_otlp_headers(raw) == expected


# ============================================================================
# End to end over streamable HTTP: the header and `_meta` reach the span
# ============================================================================


def test_a_traceparent_sent_over_http_or_in_meta_parents_the_span() -> None:
    from fastmcp import Client, Context, FastMCP
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.server.lifespan import lifespan

    from agent_runtime_fakes import ALL_TOOLS
    from apiome_mcp.agent_access import AgentAccessMiddleware
    from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
    from apiome_mcp.agent_server import AGENT_HTTP_CLIENT_KEY, build_agent_server
    from apiome_mcp.database_pool import MCP_DB_POOL_KEY
    from apiome_mcp.http_app import build_http_app
    from http_server_harness import serve_http_app

    telemetry, spans, _ = _memory_telemetry()
    upstream = PetstoreUpstream()
    pool = AgentDb().pool()
    key = AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=ALL_TOOLS)

    async def resolve(ctx: Context, secret: str) -> AgentKey:
        return key

    async def enabled(ctx: Context, key: AgentKey) -> set[str]:
        return set(ALL_TOOLS)

    @lifespan
    async def agent_lifespan(server: Any) -> Any:
        async with upstream.client() as client:
            yield {MCP_DB_POOL_KEY: pool, AGENT_HTTP_CLIENT_KEY: client}

    agent = build_agent_server(
        proxy=InvocationProxy(CONFIG, telemetry=telemetry),
        access=AgentAccessMiddleware(key_resolver=resolve, enabled_tools=enabled),
        quota=AgentQuotaMiddleware(guard=AgentQuotaGuard(), pool_source=lambda ctx: pool),  # type: ignore[arg-type,return-value]
        server_lifespan=agent_lifespan,
    )
    meta_trace = "1" * 32
    with serve_http_app(build_http_app(FastMCP("Catalog stand-in"), agent)) as base_url:

        async def run() -> None:
            headers = {"Authorization": "Bearer ak_" + "d4" * 32, "traceparent": SAMPLED}
            async with Client(StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers=headers)) as client:
                assert (await client.call_tool_mcp("listPets", {})).isError is False
            bare = {"Authorization": "Bearer ak_" + "d4" * 32}
            async with Client(StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers=bare)) as client:
                meta = {"traceparent": f"00-{meta_trace}-{PARENT_ID}-01"}
                assert (await client.call_tool_mcp("listPets", {}, meta=meta)).isError is False

        asyncio.run(run())
    parents = [span for span in spans.get_finished_spans() if span.name == SPAN_INVOCATION]
    assert [format(span.context.trace_id, "032x") for span in parents] == [TRACE_ID, meta_trace]
