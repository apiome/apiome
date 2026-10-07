"""AGX-2.1 upstream call — one request with a timeout and retry budget (#4533).

:func:`send_upstream` sends the request the proxy built and returns what came back, bounded in time
and size:

* **Time.** Each attempt gets at most ``timeout_seconds`` (connect at most
  ``connect_timeout_seconds``), and all attempts together, including back-off pauses, at most
  ``budget_seconds``. An attempt that would start with less than a moment left is not started.
* **Retries** happen only when repeating cannot do harm. An idempotent method (``GET``, ``HEAD``,
  ``OPTIONS``, ``PUT``, ``DELETE``, ``TRACE``) is retried after a timeout, a dropped connection or
  a ``502``/``503``/``504``. Any other method is retried only when the connection could not be
  opened, because then the request was never sent. Back-off doubles from ``backoff_seconds``; a
  ``Retry-After`` the upstream sends is honoured when it fits the budget.
* **Size.** At most ``max_response_bytes`` of the body are read; the rest is not downloaded and the
  response is marked truncated.

Redirects are not followed: a ``3xx`` is returned as is. Following one could carry an injected
credential to another host.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

import httpx

__all__ = [
    "IDEMPOTENT_METHODS",
    "RETRYABLE_STATUSES",
    "UpstreamCallPolicy",
    "UpstreamResponse",
    "UpstreamTimeoutError",
    "UpstreamUnreachableError",
    "send_upstream",
]

#: Methods safe to send twice (RFC 9110 §9.2.2).
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"})

#: Statuses that mean "try again", retried for idempotent methods.
RETRYABLE_STATUSES = frozenset({502, 503, 504})

#: An attempt is not started with less than this much budget left (seconds).
_MIN_ATTEMPT_SECONDS = 0.05


@dataclass(frozen=True)
class UpstreamCallPolicy:
    """How long and how often one upstream call may take.

    Attributes:
        timeout_seconds: Most time one attempt may take.
        connect_timeout_seconds: Most time opening the connection may take.
        max_retries: Retries after the first attempt (0 = one attempt only).
        budget_seconds: Most time all attempts and pauses may take together.
        backoff_seconds: Pause before the first retry; doubles each retry.
        max_response_bytes: Most body bytes read.
    """

    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    max_retries: int = 2
    budget_seconds: float = 45.0
    backoff_seconds: float = 0.2
    max_response_bytes: int = 65_536


@dataclass(frozen=True)
class UpstreamResponse:
    """What the upstream answered.

    Attributes:
        status: The HTTP status.
        headers: Response headers, names lower-cased.
        content: The body bytes read (at most ``max_response_bytes``).
        truncated: Whether the body was longer than what was read.
        total_bytes: The full body size when known (``Content-Length``, or the read size when the
            whole body was read).
        attempts: How many attempts were made.
        elapsed_ms: Time spent on the upstream, all attempts and pauses included.
    """

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes = b""
    truncated: bool = False
    total_bytes: int | None = None
    attempts: int = 1
    elapsed_ms: int = 0

    @property
    def content_type(self) -> str | None:
        """The response's ``Content-Type``, if any."""
        return self.headers.get("content-type")


class UpstreamTimeoutError(Exception):
    """The upstream did not answer within the budget.

    Attributes:
        attempts: Attempts made.
        elapsed_ms: Time spent.
    """

    def __init__(self, attempts: int, elapsed_ms: int) -> None:
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        super().__init__(f"upstream timed out after {attempts} attempt(s)")


class UpstreamUnreachableError(Exception):
    """No connection to the upstream could be made (refused, DNS, TLS, reset).

    Attributes:
        attempts: Attempts made.
        elapsed_ms: Time spent.
    """

    def __init__(self, attempts: int, elapsed_ms: int) -> None:
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        super().__init__(f"upstream unreachable after {attempts} attempt(s)")


def _retry_after(headers: Mapping[str, str]) -> float | None:
    """A ``Retry-After`` given in seconds, if any (an HTTP-date is ignored)."""
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


async def _attempt(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: Mapping[str, str],
    content: bytes | None,
    *,
    timeout: float,
    connect_timeout: float,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes, bool, int | None]:
    """One attempt, bounded by ``timeout`` overall; returns ``(status, headers, body, truncated, total)``."""
    request_timeout = httpx.Timeout(timeout, connect=min(connect_timeout, timeout))
    async with asyncio.timeout(timeout):
        async with client.stream(method, url, headers=dict(headers), content=content, timeout=request_timeout) as resp:
            body = bytearray()
            truncated = False
            async for chunk in resp.aiter_bytes():
                room = max_bytes - len(body)
                if len(chunk) > room:
                    body.extend(chunk[:room])
                    truncated = True
                    break
                body.extend(chunk)
            response_headers = {k.lower(): v for k, v in resp.headers.items()}
            total: int | None = len(body) if not truncated else None
            declared = response_headers.get("content-length")
            if truncated and declared and declared.isdigit():
                total = int(declared)
            return resp.status_code, response_headers, bytes(body), truncated, total


async def send_upstream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    content: bytes | None,
    policy: UpstreamCallPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> UpstreamResponse:
    """Send one request within ``policy``'s time, retry and size limits.

    Args:
        client: The shared HTTP client (redirects off).
        method: The HTTP method.
        url: The absolute URL, credentials already applied.
        headers: The request headers, credentials already applied.
        content: The request body, or ``None``.
        policy: The limits.
        sleep: Pause function (tests).
        monotonic: Clock (tests).

    Returns:
        The last response. A ``502``/``503``/``504`` is returned once retries are used up.

    Raises:
        UpstreamTimeoutError: Every attempt timed out, or the budget ran out.
        UpstreamUnreachableError: The last attempt could not connect or lost the connection.
    """
    started = monotonic()
    idempotent = method.upper() in IDEMPOTENT_METHODS
    attempts = 0
    last_error: Exception | None = None
    last_response: UpstreamResponse | None = None

    def elapsed_ms() -> int:
        return max(0, int(round((monotonic() - started) * 1000)))

    def remaining() -> float:
        return policy.budget_seconds - (monotonic() - started)

    while True:
        left = remaining()
        if left < _MIN_ATTEMPT_SECONDS:
            break
        attempts += 1
        retry_pause: float | None = None
        try:
            status, response_headers, body, truncated, total = await _attempt(
                client,
                method,
                url,
                headers,
                content,
                timeout=min(policy.timeout_seconds, left),
                connect_timeout=policy.connect_timeout_seconds,
                max_bytes=policy.max_response_bytes,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The connection never opened, so the request was never sent: safe for any method.
            last_error = exc
        except (TimeoutError, httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            last_error = exc
            if not idempotent:
                break
        else:
            response = UpstreamResponse(
                status=status,
                headers=response_headers,
                content=body,
                truncated=truncated,
                total_bytes=total,
                attempts=attempts,
                elapsed_ms=elapsed_ms(),
            )
            if not (idempotent and status in RETRYABLE_STATUSES) or attempts > policy.max_retries:
                return response
            retry_pause = _retry_after(response_headers)
            last_error = None
            last_response = response
        if attempts > policy.max_retries:
            break
        pause = policy.backoff_seconds * (2 ** (attempts - 1)) if retry_pause is None else retry_pause
        if pause >= remaining() - _MIN_ATTEMPT_SECONDS:
            break
        await sleep(pause)

    if last_error is None and last_response is not None:
        return last_response
    if isinstance(last_error, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)):
        raise UpstreamUnreachableError(max(attempts, 1), elapsed_ms())
    raise UpstreamTimeoutError(max(attempts, 1), elapsed_ms())
