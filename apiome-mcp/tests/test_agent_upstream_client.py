"""AGX-2.1 upstream call (#4533): timeout and retry budget, safe retries only, bounded body reads."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from apiome_mcp.agent_upstream_client import (
    UpstreamCallPolicy,
    UpstreamResponse,
    UpstreamTimeoutError,
    UpstreamUnreachableError,
    send_upstream,
)

URL = "https://api.example.com/v1/pets"


class _Clock:
    """A fake clock that advances only when ``sleep`` is awaited."""

    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def _send(
    handler: Callable[[httpx.Request], httpx.Response],
    method: str = "GET",
    *,
    policy: UpstreamCallPolicy | None = None,
    clock: _Clock | None = None,
) -> UpstreamResponse:
    clock = clock or _Clock()

    async def run() -> UpstreamResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send_upstream(
                client,
                method,
                URL,
                headers={},
                content=None,
                policy=policy or UpstreamCallPolicy(),
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            )

    return asyncio.run(run())


def _sequence(*answers: httpx.Response | Exception) -> tuple[Callable[[httpx.Request], httpx.Response], list[int]]:
    """A handler answering in order (the last answer repeats); returns it and a call counter."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        answer = answers[min(len(calls), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return handler, calls


def test_a_success_is_returned_after_one_attempt() -> None:
    handler, calls = _sequence(httpx.Response(200, json=[1]))
    response = _send(handler)
    assert (response.status, response.content, response.attempts, len(calls)) == (200, b"[1]", 1, 1)
    assert response.headers["content-type"] == "application/json"


def test_an_idempotent_call_retries_a_503_with_backoff() -> None:
    clock = _Clock()
    handler, calls = _sequence(httpx.Response(503), httpx.Response(503), httpx.Response(200, text="ok"))
    response = _send(handler, clock=clock)
    assert (response.status, response.attempts, len(calls)) == (200, 3, 3)
    assert clock.pauses == [0.2, 0.4]


def test_retries_stop_at_max_retries_and_return_the_last_answer() -> None:
    handler, calls = _sequence(httpx.Response(502))
    response = _send(handler, policy=UpstreamCallPolicy(max_retries=1))
    assert (response.status, len(calls)) == (502, 2)


def test_retry_after_is_honoured() -> None:
    clock = _Clock()
    handler, _ = _sequence(httpx.Response(503, headers={"Retry-After": "3"}), httpx.Response(200))
    _send(handler, clock=clock)
    assert clock.pauses == [3.0]


def test_a_post_is_not_retried_after_a_server_error() -> None:
    handler, calls = _sequence(httpx.Response(503), httpx.Response(200))
    response = _send(handler, "POST")
    assert (response.status, len(calls)) == (503, 1)


def test_a_post_is_retried_when_the_connection_never_opened() -> None:
    handler, calls = _sequence(httpx.ConnectError("refused"), httpx.Response(201))
    response = _send(handler, "POST")
    assert (response.status, len(calls)) == (201, 2)


def test_a_post_is_not_retried_after_a_read_timeout() -> None:
    handler, calls = _sequence(httpx.ReadTimeout("slow"), httpx.Response(201))
    with pytest.raises(UpstreamTimeoutError) as exc:
        _send(handler, "POST")
    assert (exc.value.attempts, len(calls)) == (1, 1)


def test_repeated_timeouts_raise_after_the_retries() -> None:
    handler, calls = _sequence(httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeoutError) as exc:
        _send(handler)
    assert (exc.value.attempts, len(calls)) == (3, 3)


def test_an_unreachable_upstream_raises_unreachable() -> None:
    handler, _ = _sequence(httpx.ConnectError("refused"))
    with pytest.raises(UpstreamUnreachableError):
        _send(handler)


def test_the_budget_caps_the_back_off() -> None:
    clock = _Clock()
    handler, calls = _sequence(httpx.Response(503, headers={"Retry-After": "60"}), httpx.Response(200))
    response = _send(handler, policy=UpstreamCallPolicy(budget_seconds=10), clock=clock)
    assert (response.status, len(calls), clock.pauses) == (503, 1, [])


def test_an_exhausted_budget_raises_a_timeout() -> None:
    clock = _Clock()
    clock.now = 0.0

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += 100.0
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UpstreamTimeoutError):
        _send(handler, policy=UpstreamCallPolicy(budget_seconds=5), clock=clock)


def test_a_slow_body_is_bounded_by_the_attempt_timeout() -> None:
    class _Slow(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            yield b"["
            await asyncio.sleep(5)
            yield b"]"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Slow())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_upstream(
                client,
                "GET",
                URL,
                headers={},
                content=None,
                policy=UpstreamCallPolicy(timeout_seconds=0.2, budget_seconds=0.3, max_retries=0),
            )

    with pytest.raises(UpstreamTimeoutError):
        asyncio.run(run())


def test_a_large_body_is_truncated_and_reports_its_size() -> None:
    body = b"x" * 5000
    handler, _ = _sequence(httpx.Response(200, content=body, headers={"Content-Length": "5000"}))
    response = _send(handler, policy=UpstreamCallPolicy(max_response_bytes=1024))
    assert (len(response.content), response.truncated, response.total_bytes) == (1024, True, 5000)


def test_a_body_that_fits_is_not_truncated() -> None:
    handler, _ = _sequence(httpx.Response(200, content=b"abc"))
    response = _send(handler, policy=UpstreamCallPolicy(max_response_bytes=1024))
    assert (response.content, response.truncated, response.total_bytes) == (b"abc", False, 3)


def test_redirects_are_not_followed() -> None:
    handler, calls = _sequence(httpx.Response(302, headers={"Location": "https://evil.example/steal"}))
    response = _send(handler)
    assert (response.status, len(calls)) == (302, 1)
