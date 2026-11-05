"""The export webhook delivery pipeline — MFX-38.2 (#4329).

:mod:`app.export_webhook_delivery_pipeline` against an in-memory run table and a mock receiver: the first
attempt, what each answer means (delivered / retried / failed at once), the backoff and ``Retry-After``, the
attempt budget, the sweep that makes the retries, and that every attempt re-sends the same signed bytes.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app import export_webhook_delivery_pipeline as pipeline
from app.export_webhook_delivery import sign_body
from app.ssrf_guard import build_guarded_client

_RUN = "44444444-4444-4444-8444-444444444444"
_TENANT = "11111111-1111-4111-8111-111111111111"
_SECRET = "s3cret-s3cret-s3cret"
_BODY = b'{"event":"export.delivered"}'


class FakeDatabase:
    """The four run-table calls the pipeline makes, in memory."""

    def __init__(self) -> None:
        self.runs: Dict[str, Dict[str, Any]] = {}

    def insert_export_webhook_delivery_run(self, *, run_id: str, status: str, max_attempts: int,
                                           **fields: Any) -> Optional[Dict[str, Any]]:
        self.runs[run_id] = {
            "id": run_id, "status": status, "max_attempts": max_attempts, "attempt_count": 0, "attempts": [],
            "next_attempt_at": datetime.now(timezone.utc) if status == "pending" else None,
            "error_code": None, "error_message": None, "last_http_status": None, **fields,
        }
        return self._public(run_id)

    def record_export_webhook_delivery_attempt(self, run_id: str, *, attempt: Dict[str, Any], status: str,
                                               next_attempt_at: Optional[datetime] = None,
                                               http_status: Optional[int] = None, error_code: Optional[str] = None,
                                               error_message: Optional[str] = None) -> Dict[str, Any]:
        run = self.runs[run_id]
        run.update(status=status, next_attempt_at=next_attempt_at, last_http_status=http_status,
                   error_code=error_code, error_message=error_message, attempt_count=run["attempt_count"] + 1)
        run["attempts"] = [*run["attempts"], attempt]
        return self._public(run_id)

    def claim_next_due_export_webhook_delivery(self) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        for run in self.runs.values():
            if run["status"] in ("pending", "retrying") and run["next_attempt_at"] <= now:
                run["status"] = "delivering"
                return copy.deepcopy(run)
        return None

    def make_due(self, run_id: str = _RUN) -> None:
        self.runs[run_id]["next_attempt_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    def _public(self, run_id: str) -> Dict[str, Any]:
        return {key: value for key, value in copy.deepcopy(self.runs[run_id]).items()
                if key not in ("payload", "signature")}


class Receiver:
    """A mock receiver answering a scripted sequence of responses (or raising)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: List[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def factory(self) -> Callable[..., httpx.Client]:
        return lambda **kw: httpx.Client(transport=httpx.MockTransport(self.handler), **kw)


def _start(database: FakeDatabase, receiver: Receiver, **fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        run_id=_RUN, tenant_id=_TENANT, job_id="job-1", artifact_id="a1", target_url="https://hooks.example/in",
        artifact_delivery="inline", payload=_BODY, payload_sha256=hashlib.sha256(_BODY).hexdigest(),
        signature=sign_body(_SECRET, _BODY),
    )
    values.update(fields)
    row = pipeline.start_delivery(database, client_factory=receiver.factory(), **values)
    assert row is not None
    return row


# ===========================================================================
# The first attempt
# ===========================================================================


def test_a_2xx_delivers_on_the_first_attempt_with_the_signed_body_and_headers() -> None:
    database, receiver = FakeDatabase(), Receiver(httpx.Response(202, text="queued"))
    row = _start(database, receiver)
    assert (row["status"], row["attempt_count"], row["last_http_status"]) == ("delivered", 1, 202)
    assert row["attempts"][0]["responsePreview"] == "queued"
    request = receiver.requests[0]
    assert request.content == _BODY
    expected = "sha256=" + hmac.new(_SECRET.encode(), _BODY, hashlib.sha256).hexdigest()
    assert request.headers["X-Apiome-Signature"] == expected
    assert request.headers["X-Apiome-Event"] == "export.delivered"
    assert request.headers["X-Apiome-Delivery"] == _RUN
    assert request.headers["X-Apiome-Delivery-Attempt"] == "1"
    assert request.headers["Content-Type"].startswith("application/json")


@pytest.mark.parametrize("answer", [
    httpx.Response(500), httpx.Response(502), httpx.Response(408), httpx.Response(425), httpx.Response(429),
    httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
])
def test_a_retryable_failure_schedules_a_retry_on_the_backoff(answer: Any) -> None:
    database = FakeDatabase()
    before = datetime.now(timezone.utc)
    row = _start(database, Receiver(answer))
    assert row["status"] == "retrying"
    assert row["error_code"] in (pipeline.ERROR_RECEIVER_ERROR, pipeline.ERROR_UNREACHABLE)
    delay = (row["next_attempt_at"] - before).total_seconds()
    assert pipeline.BACKOFF_AFTER_FAILURE_SEC[0] - 1 <= delay <= pipeline.BACKOFF_AFTER_FAILURE_SEC[0] + 5


@pytest.mark.parametrize(("status", "needle"), [(400, "HTTP 400"), (401, "HTTP 401"), (404, "HTTP 404"),
                                                (410, "HTTP 410"), (301, "redirects are not followed")])
def test_a_rejection_fails_the_run_at_once(status: int, needle: str) -> None:
    database = FakeDatabase()
    row = _start(database, Receiver(httpx.Response(status, headers={"Location": "https://elsewhere/"})))
    assert (row["status"], row["error_code"], row["attempt_count"]) == ("failed", pipeline.ERROR_REJECTED, 1)
    assert needle in row["error_message"]


def test_retry_after_pushes_the_next_attempt_back() -> None:
    database = FakeDatabase()
    before = datetime.now(timezone.utc)
    row = _start(database, Receiver(httpx.Response(429, headers={"Retry-After": "120"})))
    assert (row["next_attempt_at"] - before).total_seconds() >= 119


def test_the_ssrf_guard_refuses_an_internal_destination_and_the_run_fails() -> None:
    database = FakeDatabase()
    receiver = Receiver(httpx.Response(200))
    row = pipeline.start_delivery(
        database, client_factory=lambda **kw: build_guarded_client(transport=httpx.MockTransport(receiver.handler),
                                                                   **kw),
        run_id=_RUN, tenant_id=_TENANT, job_id="job-1", artifact_id="a1", target_url="http://127.0.0.1:9/hook",
        artifact_delivery="inline", payload=_BODY, payload_sha256="x", signature=sign_body(_SECRET, _BODY),
    )
    assert row is not None
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_DESTINATION_REFUSED)
    assert receiver.requests == []


def test_an_internal_crash_on_the_first_attempt_leaves_the_run_for_the_sweep() -> None:
    database = FakeDatabase()

    def boom(**_kw: Any) -> httpx.Client:
        raise RuntimeError("no client")

    row = pipeline.start_delivery(database, client_factory=boom, run_id=_RUN, tenant_id=_TENANT, job_id="j",
                                  artifact_id="a", target_url="https://hooks.example/in", artifact_delivery="inline",
                                  payload=_BODY, payload_sha256="x", signature=sign_body(_SECRET, _BODY))
    assert row is not None and row["status"] == "delivering"


# ===========================================================================
# The sweep
# ===========================================================================


def test_the_sweep_retries_with_the_same_bytes_until_delivered() -> None:
    database = FakeDatabase()
    receiver = Receiver(httpx.Response(503), httpx.Response(500), httpx.Response(200))
    _start(database, receiver)
    assert pipeline.process_due_export_webhook_deliveries(database, client_factory=receiver.factory()) == 0
    for _ in range(2):
        database.make_due()
        assert pipeline.process_due_export_webhook_deliveries(database, client_factory=receiver.factory()) == 1
    run = database.runs[_RUN]
    assert (run["status"], run["attempt_count"]) == ("delivered", 3)
    assert [a["httpStatus"] for a in run["attempts"]] == [503, 500, 200]
    assert {r.content for r in receiver.requests} == {_BODY}
    assert len({r.headers["X-Apiome-Signature"] for r in receiver.requests}) == 1
    assert [r.headers["X-Apiome-Delivery-Attempt"] for r in receiver.requests] == ["1", "2", "3"]


def test_the_backoff_grows_with_each_failure() -> None:
    database = FakeDatabase()
    receiver = Receiver(httpx.Response(500))
    _start(database, receiver)
    delays = []
    for _ in range(2):
        database.make_due()
        before = datetime.now(timezone.utc)
        pipeline.process_due_export_webhook_deliveries(database, client_factory=receiver.factory())
        delays.append((database.runs[_RUN]["next_attempt_at"] - before).total_seconds())
    assert delays[0] == pytest.approx(pipeline.BACKOFF_AFTER_FAILURE_SEC[1], abs=5)
    assert delays[1] == pytest.approx(pipeline.BACKOFF_AFTER_FAILURE_SEC[2], abs=5)


def test_running_out_of_attempts_fails_the_run_naming_the_last_error() -> None:
    database = FakeDatabase()
    receiver = Receiver(httpx.Response(500))
    _start(database, receiver)
    for _ in range(pipeline.MAX_ATTEMPTS - 1):
        database.make_due()
        pipeline.process_due_export_webhook_deliveries(database, client_factory=receiver.factory())
    run = database.runs[_RUN]
    assert (run["status"], run["attempt_count"]) == ("failed", pipeline.MAX_ATTEMPTS)
    assert run["error_code"] == pipeline.ERROR_ATTEMPTS_EXHAUSTED
    assert "HTTP 500" in run["error_message"]
    database.make_due()
    assert pipeline.process_due_export_webhook_deliveries(database, client_factory=receiver.factory()) == 0


def test_a_sweep_crash_is_recorded_so_the_run_is_not_stuck() -> None:
    database = FakeDatabase()
    _start(database, Receiver(httpx.Response(500)))
    database.make_due()

    def boom(**_kw: Any) -> httpx.Client:
        raise RuntimeError("no client")

    assert pipeline.process_due_export_webhook_deliveries(database, client_factory=boom) == 1
    run = database.runs[_RUN]
    assert (run["status"], run["error_code"], run["attempt_count"]) == ("retrying", pipeline.ERROR_INTERNAL, 2)


def test_attempt_results_classify_answers() -> None:
    assert pipeline.AttemptResult(http_status=204).delivered
    assert pipeline.AttemptResult(http_status=None).retryable
    assert not pipeline.AttemptResult(http_status=None, refused=True).retryable
    assert pipeline.AttemptResult(http_status=503).retryable
    assert not pipeline.AttemptResult(http_status=403).retryable
