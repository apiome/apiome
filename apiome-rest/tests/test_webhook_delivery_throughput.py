"""Webhook delivery throughput and tenant isolation against a stub receiver (DBP-1.18, #7201).

The acceptance criteria: at least 1,000 deliveries a minute against a fast receiver, and one slow
receiver does not delay the other tenants. Both run the real delivery code
(:func:`app.push_webhook_delivery.process_due_push_webhook_deliveries` and
:func:`app.export_webhook_delivery_pipeline.process_due_export_webhook_deliveries`) over an in-memory
queue; push deliveries POST over HTTP to a local stub server.
"""

from __future__ import annotations

import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Sequence
from unittest.mock import patch

import httpx
import pytest

from app import export_webhook_delivery_pipeline as pipeline
from app.push_webhook_delivery import process_due_push_webhook_deliveries

#: Seconds the stub's slow route takes to answer.
SLOW_SECONDS = 1.5


class _StubHandler(BaseHTTPRequestHandler):
    """``/fast`` answers at once, ``/slow`` after :data:`SLOW_SECONDS`."""

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path.startswith("/slow"):
            time.sleep(SLOW_SECONDS)
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def receiver() -> Iterator[str]:
    """A local stub receiver; yields its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class PushQueue:
    """The push delivery queue in memory: the batch claim and the attempt write the pipeline calls."""

    def __init__(self, events: Sequence[Dict[str, Any]]) -> None:
        self.pending: List[Dict[str, Any]] = list(events)
        self.lock = threading.Lock()
        self.finished: Dict[str, float] = {}
        self.statuses: Dict[str, str] = {}
        self.claim_sizes: List[int] = []
        self.started = time.monotonic()

    def claim_due_push_webhook_deliveries(
        self, *, limit: int, exclude_tenant_ids: Sequence[str] = ()
    ) -> List[Dict[str, Any]]:
        with self.lock:
            taken = [e for e in self.pending if e["tenant_id"] not in set(exclude_tenant_ids)][:limit]
            for event in taken:
                self.pending.remove(event)
            self.claim_sizes.append(len(taken))
            return [dict(e) for e in taken]

    def finalize_push_webhook_delivery_attempt(self, event_id: str, **kwargs: Any) -> None:
        with self.lock:
            self.finished[event_id] = time.monotonic() - self.started
            self.statuses[event_id] = kwargs["new_status"]


def _event(base_url: str, tenant: str, route: str) -> Dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "subscription_id": str(uuid.uuid4()),
        "event_type": "test.event",
        "payload": {"k": "v"},
        "event_status": "pending",
        "attempt_count": 0,
        "next_retry_at": None,
        "subscription_url": f"{base_url}/{route}",
        "subscription_active": True,
        "signing_secret_encrypted": b"x",
    }


def test_push_delivery_exceeds_1000_a_minute_against_a_fast_receiver(receiver: str) -> None:
    tenants = [str(uuid.uuid4()) for _ in range(8)]
    events = [_event(receiver, tenants[n % len(tenants)], "fast") for n in range(400)]
    queue = PushQueue(events)
    with patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"):
        started = time.monotonic()
        made = process_due_push_webhook_deliveries(queue, workers=8, per_tenant=2, batch_size=50, deadline_seconds=60)
        elapsed = time.monotonic() - started
    assert made == 400
    assert set(queue.statuses.values()) == {"delivered"}
    per_minute = made / elapsed * 60
    assert per_minute >= 1000, f"{per_minute:.0f} deliveries a minute"
    # The queue was drained in batches, not one claim per event.
    assert max(queue.claim_sizes) > 1


def test_a_slow_receiver_does_not_delay_other_tenants(receiver: str) -> None:
    slow_tenant = str(uuid.uuid4())
    fast_tenants = [str(uuid.uuid4()) for _ in range(3)]
    # The slow tenant's events are the oldest: they are claimed first.
    events = [_event(receiver, slow_tenant, "slow") for _ in range(4)]
    events += [_event(receiver, fast_tenants[n % 3], "fast") for n in range(30)]
    queue = PushQueue(events)
    slow_ids = {e["event_id"] for e in events[:4]}
    with patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"):
        made = process_due_push_webhook_deliveries(queue, workers=6, per_tenant=2, batch_size=10, deadline_seconds=60)
    assert made == 34
    fast_done = [t for event_id, t in queue.finished.items() if event_id not in slow_ids]
    slow_done = [t for event_id, t in queue.finished.items() if event_id in slow_ids]
    # Every other tenant's event was delivered before the slow receiver answered even once.
    assert max(fast_done) < min(slow_done)
    assert min(slow_done) >= SLOW_SECONDS * 0.9


class ExportQueue:
    """The export delivery runs in memory: the batch claim and the attempt write the pipeline calls."""

    def __init__(self, runs: Sequence[Dict[str, Any]]) -> None:
        self.pending: List[Dict[str, Any]] = list(runs)
        self.lock = threading.Lock()
        self.finished: Dict[str, float] = {}
        self.started = time.monotonic()

    def claim_due_export_webhook_deliveries(
        self, *, limit: int, exclude_tenant_ids: Sequence[str] = ()
    ) -> List[Dict[str, Any]]:
        with self.lock:
            taken = [r for r in self.pending if r["tenant_id"] not in set(exclude_tenant_ids)][:limit]
            for run in taken:
                self.pending.remove(run)
            return [dict(r) for r in taken]

    def record_export_webhook_delivery_attempt(self, run_id: str, **kwargs: Any) -> Dict[str, Any]:
        with self.lock:
            self.finished[run_id] = time.monotonic() - self.started
        return {"id": run_id, "status": kwargs.get("status")}


def test_export_delivery_isolates_a_slow_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_REQUEST_TIMEOUT_SEC", 5.0, raising=False)
    slow_tenant, fast_tenant = str(uuid.uuid4()), str(uuid.uuid4())

    def _run(tenant: str, url: str) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant,
            "target_url": url,
            "attempt_count": 0,
            "max_attempts": 4,
            "payload": b"{}",
            "signature": "sha256=00",
        }

    runs = [_run(slow_tenant, "https://slow.example/in") for _ in range(3)]
    runs += [_run(fast_tenant, "https://fast.example/in") for _ in range(10)]
    slow_ids = {r["id"] for r in runs[:3]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "slow.example":
            time.sleep(0.6)
        return httpx.Response(204)

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    queue = ExportQueue(runs)
    made = pipeline.process_due_export_webhook_deliveries(
        queue, client_factory=factory, workers=4, per_tenant=1, batch_size=4, deadline_seconds=60
    )
    assert made == 13
    fast_done = [t for run_id, t in queue.finished.items() if run_id not in slow_ids]
    slow_done = [t for run_id, t in queue.finished.items() if run_id in slow_ids]
    assert max(fast_done) < min(slow_done)
