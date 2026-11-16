---
title: Agent telemetry
description: "Export agent tool calls as OpenTelemetry traces and metrics over OTLP."
sidebar_position: 10
tags: [admin, agents, observability, opentelemetry]
---

The agent runtime (`/agent/mcp` on apiome-mcp) can send every agent `tools/call` to your
observability stack as an **OpenTelemetry trace** and two **metrics**, over OTLP/HTTP. Datadog,
Honeycomb, Grafana, Splunk and most SIEM pipelines accept OTLP, either directly or through an
OpenTelemetry Collector. Apiome uses no vendor SDK.

It is **off** until you set an endpoint. Every call is still recorded in the invocation audit
whatever you choose here. See [Agent access](../bring-in/agent-access.mdx#usage).

## Turn it on

Set these on the `mcp` service (or in `apiome-mcp/.env`) and restart apiome-mcp:

| Variable | Default | What it is |
| --- | --- | --- |
| `APIOME_MCP_OTEL_EXPORTER_OTLP_ENDPOINT` | empty (off) | The OTLP/HTTP root of your collector, for example `http://otel-collector:4318`. Spans go to `<root>/v1/traces`, metrics to `<root>/v1/metrics`. Must start with `http://` or `https://` |
| `APIOME_MCP_OTEL_EXPORTER_OTLP_HEADERS` | empty | Headers sent with every export, as `key=value` pairs separated by commas (URL-encode spaces as `%20`), for example a vendor API key. Never logged |
| `APIOME_MCP_OTEL_TRACES_SAMPLER_RATIO` | `0.25` | Share of calls traced (`0` to `1`). Metrics count every call whatever the ratio |
| `APIOME_MCP_OTEL_SERVICE_NAME` | `apiome-mcp` | The `service.name` your backend groups the data under |
| `APIOME_MCP_OTEL_METRIC_EXPORT_INTERVAL_SECONDS` | `60` | Seconds between metric exports |
| `APIOME_MCP_OTEL_EXPORT_TIMEOUT_SECONDS` | `10` | The longest one export may take |

On start-up apiome-mcp logs `agent_telemetry_enabled` with the collector's host.

### Sampling and cost

Exporting runs in the background, but building spans costs some CPU. On the agent runtime's own
benchmark (a mock `listPets` call through the full HTTP stack, about 4 ms of CPU):

| Sampling ratio | CPU added per call |
| --- | --- |
| `0.25` (default) | about 1.5% |
| `1` (every call traced) | about 2.5% |

Metrics always cover every call, so dashboards and alerts on call counts, error rates and latency
are exact at any ratio. Traces are a sample.

**A caller's decision wins.** When a call arrives with a W3C `traceparent` (below), it is traced
exactly when the caller's trace is sampled, whatever the ratio. A caller that traces everything gets
every one of its calls.

## What is exported

### The trace

Each call is one span named `apiome.agent.invocation` (kind `SERVER`), with up to two children:

| Span | When | Attributes |
| --- | --- | --- |
| `vault.resolve` | `prod` toolsets, while the upstream credential is opened | `apiome.agent.credential_injected` (`true` when a credential was bound to the host); on failure `error.type = credential_unavailable` |
| `upstream.request` | When the request is sent to the API, retries included | `http.request.method`, `http.response.status_code`; on failure `error.type` (`timeout`, `unreachable`, `blocked`, or the `5xx` status) |

A call refused before it reaches the API (invalid arguments, a method or size rail) has no children.
A failed call's span has status `ERROR`, with its error code as the description.

The `apiome.agent.invocation` span carries the **same values as the call's audit row**, one attribute
per column:

| Attribute | What it is |
| --- | --- |
| `apiome.agent.tenant_id` | The workspace |
| `apiome.agent.key_id` | The agent key's id (never the key) |
| `apiome.agent.toolset_id` | The toolset |
| `apiome.agent.tool_name` | The MCP tool called |
| `apiome.agent.target` | `prod` or `mock` |
| `apiome.agent.outcome` | `success`, `validation_failure`, `upstream_error`, `quota_rejected` or `internal_error` |
| `apiome.agent.error_code` | The machine reason, such as `upstream_timeout` (failed calls only) |
| `apiome.agent.http_status` | The API's HTTP status, when it answered |
| `apiome.agent.latency_ms` | How long the call took |
| `apiome.agent.request_bytes`, `apiome.agent.response_bytes` | The size of the arguments and of the result |
| `apiome.agent.sampled` | Whether a [body sample](../bring-in/agent-access.mdx#body-samples) was kept for the call |

Four more columns are on the way: `apiome.agent.via`, `apiome.agent.version_id`,
`apiome.agent.compile_fingerprint` and `apiome.agent.failure_class`. They will appear on the span and
the metrics automatically once the audit row records them.

### The metrics

| Metric | Type | Unit |
| --- | --- | --- |
| `apiome.agent.invocations` | Counter | calls |
| `apiome.agent.latency_ms` | Histogram | ms |

Both are labelled with the span's attributes **except** `apiome.agent.key_id` and the three measured
numbers (`latency_ms`, `request_bytes`, `response_bytes`). One series per key, or per call size,
would overwhelm most backends. To break usage down by key, use the traces or the
[Usage tab](../bring-in/agent-access.mdx#usage).

### What is never exported

Arguments, request and response bodies, headers, URLs, upstream credentials and error messages
never become telemetry. Only the attributes listed on this page are set. A test runs real calls
whose arguments, bodies and credentials carry known markers, and fails if any of them appears in
an exported byte.

## Connect a trace to the agent's own trace

If the agent (or the gateway in front of it) sends a W3C `traceparent` header, the
`apiome.agent.invocation` span becomes a child of the caller's span, so the whole request shows as
one trace. A `tracestate` header is passed along too. On a transport without HTTP headers, put
`traceparent` and `tracestate` in the request's `params._meta`. A malformed value is ignored and
the call starts its own trace.

## Recipes

Send to an [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) and let it forward
to your vendor. That keeps vendor keys out of apiome-mcp and lets you batch, filter or fan out.
Every recipe uses the same apiome-mcp setting:

```bash
APIOME_MCP_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

### Datadog

Use the Collector's Datadog exporter (or the Datadog Agent with OTLP ingest on port `4318`):

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  datadog:
    api:
      key: ${env:DD_API_KEY}
      site: datadoghq.com
service:
  pipelines:
    traces: { receivers: [otlp], exporters: [datadog] }
    metrics: { receivers: [otlp], exporters: [datadog] }
```

### Grafana (Tempo and Mimir, or Grafana Cloud)

Forward OTLP to Grafana Cloud's OTLP gateway with basic auth (`<instance id>:<token>`, base64):

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  otlphttp/grafana:
    endpoint: https://otlp-gateway-prod-eu-west-0.grafana.net/otlp
    headers:
      Authorization: Basic ${env:GRAFANA_OTLP_AUTH}
service:
  pipelines:
    traces: { receivers: [otlp], exporters: [otlphttp/grafana] }
    metrics: { receivers: [otlp], exporters: [otlphttp/grafana] }
```

For a self-hosted Tempo and Mimir, point an `otlphttp` exporter at each one instead.

### Straight to a vendor

Backends that accept OTLP/HTTP directly need no Collector. For Honeycomb:

```bash
APIOME_MCP_OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
APIOME_MCP_OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=YOUR_API_KEY
```

## When the collector is down

Telemetry never fails or slows a call. Spans wait in a bounded in-memory queue and are sent in
the background. An export that fails or takes longer than the timeout is dropped and logged by the
OpenTelemetry SDK, and the call has already returned. The invocation audit is written either way.
Pending data is flushed when apiome-mcp shuts down.

## Where next

- [Agent access](../bring-in/agent-access.mdx): toolsets, agent keys and the Usage tab
- [MCP agent runtime](../reference/mcp/agent-runtime.md): the endpoint and its protocol versions
- [Operating Apiome](./operating-apiome.mdx): the rest of the environment reference
