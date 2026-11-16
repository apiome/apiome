"""An in-process OTLP/HTTP collector for the ATQ-4.4 tests (#5846).

Accepts ``POST /v1/traces`` and ``POST /v1/metrics`` (protobuf, optionally gzip), decodes them with
the ``opentelemetry-proto`` messages the exporter itself uses, and keeps what arrived. ``fail=True``
answers every export with ``503`` instead, to show that a broken collector never fails a call.
"""

from __future__ import annotations

import gzip
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


@dataclass
class CollectedExports:
    """What the stub received."""

    traces: list[ExportTraceServiceRequest] = field(default_factory=list)
    metrics: list[ExportMetricsServiceRequest] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    raw: list[bytes] = field(default_factory=list)

    def spans(self) -> list[Any]:
        """Every span received, in arrival order."""
        return [
            span
            for request in self.traces
            for resource_spans in request.resource_spans
            for scope_spans in resource_spans.scope_spans
            for span in scope_spans.spans
        ]

    def metric_points(self, name: str) -> list[Any]:
        """Every data point of metric ``name`` received."""
        points: list[Any] = []
        for request in self.metrics:
            for resource_metrics in request.resource_metrics:
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        if metric.name != name:
                            continue
                        data = metric.sum if metric.HasField("sum") else metric.histogram
                        points.extend(data.data_points)
        return points


def attributes(item: Any) -> dict[str, Any]:
    """A proto span's or data point's attributes as a plain dict."""
    out: dict[str, Any] = {}
    for kv in item.attributes:
        value = kv.value
        kind = value.WhichOneof("value")
        out[kv.key] = getattr(value, kind) if kind else None
    return out


@contextmanager
def otlp_collector(*, fail: bool = False, parse: bool = True) -> Iterator[tuple[str, CollectedExports]]:
    """Serve the stub on a free localhost port; yield ``(root URL, what it collected)``.

    ``parse=False`` keeps only the raw bodies (a real collector decodes in its own process, so the
    overhead benchmark must not charge decoding to the runtime).
    """
    collected = CollectedExports()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's name
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            if fail:
                self.send_response(503)
                self.end_headers()
                return
            with lock:
                collected.headers.append({k.lower(): v for k, v in self.headers.items()})
                collected.raw.append(body)
                if not parse:
                    pass
                elif self.path == "/v1/traces":
                    request = ExportTraceServiceRequest()
                    request.ParseFromString(body)
                    collected.traces.append(request)
                elif self.path == "/v1/metrics":
                    metrics = ExportMetricsServiceRequest()
                    metrics.ParseFromString(body)
                    collected.metrics.append(metrics)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - silence the stub
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", collected
    finally:
        server.shutdown()
        server.server_close()
