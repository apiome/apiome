"""Tests for the in-process metrics registry and error envelope (RC1-3.2, #3617)."""

from app.observability import (
    MetricsRegistry,
    build_error_envelope,
    new_request_id,
)


def _registry() -> MetricsRegistry:
    """A registry whose clock starts at a fixed monotonic origin for deterministic rate math."""
    return MetricsRegistry(_start_monotonic=0.0)


def test_counts_requests_and_status_classes():
    reg = _registry()
    reg.request_finished(status_code=200, latency_ms=10.0)
    reg.request_finished(status_code=201, latency_ms=20.0)
    reg.request_finished(status_code=404, latency_ms=5.0)

    snap = reg.snapshot(now_monotonic=10.0)
    assert snap.total_requests == 3
    assert snap.requests_by_status_class == {"2xx": 2, "4xx": 1}
    assert snap.error_count == 0
    assert snap.error_rate == 0.0


def test_error_rate_counts_only_5xx():
    reg = _registry()
    reg.request_finished(status_code=200, latency_ms=1.0)
    reg.request_finished(status_code=500, latency_ms=1.0)
    reg.request_finished(status_code=503, latency_ms=1.0)
    reg.request_finished(status_code=404, latency_ms=1.0)

    snap = reg.snapshot(now_monotonic=10.0)
    assert snap.error_count == 2
    assert snap.error_rate == 0.5  # 2 of 4 requests were 5xx


def test_requests_per_second_uses_uptime():
    reg = _registry()
    for _ in range(20):
        reg.request_finished(status_code=200, latency_ms=1.0)
    snap = reg.snapshot(now_monotonic=10.0)  # 20 requests over 10 seconds
    assert snap.requests_per_second == 2.0


def test_latency_percentiles():
    reg = _registry()
    for ms in range(1, 101):  # 1..100 ms
        reg.request_finished(status_code=200, latency_ms=float(ms))
    snap = reg.snapshot(now_monotonic=10.0)
    lat = snap.latency_ms
    assert lat["count"] == 100
    assert lat["max"] == 100.0
    assert lat["avg"] == 50.5
    # Nearest-rank: p50 ~ 50, p95 ~ 95, p99 ~ 99 over a uniform 1..100 distribution.
    assert 49.0 <= lat["p50"] <= 51.0
    assert 94.0 <= lat["p95"] <= 96.0
    assert 98.0 <= lat["p99"] <= 100.0


def test_empty_latency_is_zeroed():
    snap = _registry().snapshot(now_monotonic=1.0)
    assert snap.latency_ms == {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}


def test_in_flight_gauge():
    reg = _registry()
    reg.request_started()
    reg.request_started()
    assert reg.snapshot(now_monotonic=1.0).in_flight == 2
    reg.request_finished(status_code=200, latency_ms=1.0)
    assert reg.snapshot(now_monotonic=1.0).in_flight == 1


def test_latency_window_is_bounded():
    reg = _registry()
    for _ in range(5000):  # exceeds the 4096 retention cap
        reg.request_finished(status_code=200, latency_ms=1.0)
    snap = reg.snapshot(now_monotonic=10.0)
    assert snap.total_requests == 5000  # counters are unbounded
    assert snap.latency_ms["count"] <= 4096  # but the sample window is capped


def test_new_request_id_is_unique():
    assert new_request_id() != new_request_id()


def test_error_envelope_preserves_detail_and_adds_error():
    env = build_error_envelope(
        status_code=404,
        message="Not found",
        detail="Version not found: a/b/c",
        error_type="http_error",
        request_id="rid-1",
    )
    # detail preserved verbatim (backward compatibility with existing clients/tests).
    assert env["detail"] == "Version not found: a/b/c"
    # consistent error object + top-level request id.
    assert env["error"] == {
        "status": 404,
        "message": "Not found",
        "type": "http_error",
        "request_id": "rid-1",
    }
    assert env["request_id"] == "rid-1"


def test_error_envelope_preserves_structured_detail():
    detail = [{"loc": ["body", "name"], "msg": "field required"}]
    env = build_error_envelope(
        status_code=422,
        message="Request validation failed",
        detail=detail,
        error_type="validation_error",
        request_id=None,
    )
    assert env["detail"] == detail
    assert env["error"]["type"] == "validation_error"
    assert env["request_id"] is None
