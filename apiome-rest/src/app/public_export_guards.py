"""Guards for the anonymous public browse export surface (MFX-7.3, #3862).

The public ``/v1/browse/.../export/*`` routes are intentionally unauthenticated, so they carry
extra protection beyond the global :mod:`app.rate_limit` middleware:

* **Dedicated rate limit** — export calls (especially ``/document``) run emitters and are capped
  per client IP at a lower ceiling than generic public traffic. Reuses the global
  ``rate_limit_enabled`` kill switch and window length.
* **Download size cap** — emitted documents over ``public_browse_export_document_max_bytes`` are
  rejected with ``413`` so anonymous callers cannot pull arbitrarily large artifacts.

Published/public-only access remains enforced upstream by
:func:`app.export_source.load_public_export_source` (MFX-7.1).
"""

from __future__ import annotations

import re
import time
from typing import Optional

from fastapi import HTTPException, Request
from starlette.responses import Response

from .config import settings
from .rate_limit import FixedWindowRateLimiter, _client_ip

# Matches the three public export endpoints under browse (targets / preview / document).
_PUBLIC_EXPORT_PATH = re.compile(
    r"^/v1/browse/tenants/[^/]+/projects/[^/]+/versions/[^/]+/export/"
)

_public_export_limiter = FixedWindowRateLimiter()


def is_public_browse_export_path(path: str) -> bool:
    """True when ``path`` is one of the anonymous browse export routes."""
    return bool(_PUBLIC_EXPORT_PATH.match(path))


def enforce_public_export_rate_limit(request: Request) -> None:
    """Raise ``429`` when the caller has exhausted the public-export window.

    Args:
        request: The inbound HTTP request (IP is the bucket key).

    Raises:
        HTTPException: ``429`` with ``Retry-After`` / ``X-RateLimit-*`` when over limit.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.public_browse_export_rate_limit_per_minute)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    client_ip = _client_ip(request)
    allowed, remaining, reset_after, retry_after = _public_export_limiter.check(
        f"pubexport:ip:{client_ip}", limit, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Public export rate limit exceeded; slow down and retry later.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


def response_body_byte_length(response: Response) -> int:
    """Return the UTF-8 byte length of a Starlette response body."""
    body = response.body
    return len(body) if body else 0


def enforce_public_export_document_size(response: Response) -> None:
    """Raise ``413`` when the emitted document exceeds the public download cap.

    Args:
        response: The rendered export download response.

    Raises:
        HTTPException: ``413`` when the body is larger than the configured cap.
    """
    cap = settings.public_browse_export_document_max_bytes
    if cap <= 0:
        return
    size = response_body_byte_length(response)
    if size > cap:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Export document exceeds the {cap}-byte public download limit "
                f"({size} bytes emitted)."
            ),
        )


def public_export_document_max_bytes() -> Optional[int]:
    """The configured public download cap, or ``None`` when disabled (``<= 0``)."""
    cap = settings.public_browse_export_document_max_bytes
    return cap if cap > 0 else None
