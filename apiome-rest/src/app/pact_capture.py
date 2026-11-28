"""Consumer-tagged mock capture: the rules shared by the mock runtime and the REST API — PFX-9.1 (#7319).

A call to the hosted mock is recorded *for a consumer* when it carries
``X-Mock-Capture: <consumer>@<version>`` or arrives through a private capture URL
(``/{tenant}/{project}/{version}/~capture/{token}/…``). Untagged calls are never recorded. What is
recorded is later turned into one consumer's pact (PFX-9.2), so every call keeps the facts a pact
needs: method, path, the spec's path template, status, and where the answer came from — the spec,
a scenario, a stateful session, chaos, a forced status, nothing in the spec (off-spec), or a
refusal of the request itself.

This module is pure (no I/O) so both sides apply the same rules:

* :func:`classify_capture_header` reads the header: the guarded upstream proxy's opt-in values
  (``on``, ``record``, …; PMR-2.4) stay the proxy's, ``off`` means "not this one", a value with an
  ``@`` is a consumer tag, and anything else is reported back as not recorded with the reason —
  never silently ignored;
* :func:`new_link_token` / :func:`link_token_hash` make and recognise private capture URL tokens;
  only the SHA-256 digest is ever stored;
* :func:`origin_for_layer` maps the runtime's serving layer to the stored ``origin``;
* :func:`redact_call` reduces one call to what may be stored, with the mock's redaction rules
  (:func:`app.mock_capture.redact_exchange`: the always-on credential rules plus the version's own
  ``proxyCapture.redaction`` additions). A record that still looks credential-bearing afterwards is
  refused rather than stored.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .mock_capture import MAX_CAPTURE_BODY_BYTES, redact_exchange, residual_credential_pointers

__all__ = [
    "CAPTURE_HEADER",
    "CAPTURE_SESSION_HEADER",
    "CAPTURE_URL_SEGMENT",
    "CaptureHeaderProblem",
    "ConsumerTag",
    "DEFAULT_LINK_DAYS",
    "DEFAULT_RETENTION_DAYS",
    "LINK_TOKEN_PREFIX",
    "MAX_CALLS_PER_SESSION",
    "MAX_LINK_DAYS",
    "MAX_LIVE_SESSIONS_PER_TENANT",
    "MAX_NAME_CHARS",
    "MAX_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "ORIGINS",
    "REFUSAL_REASONS",
    "RedactedCall",
    "classify_capture_header",
    "decode_body",
    "link_token_hash",
    "looks_like_link_token",
    "mock_session_digest",
    "name_problem",
    "new_link_token",
    "origin_for_layer",
    "redact_call",
    "retention_problem",
]

#: The request header that tags a call, and the response header that says what happened to it.
CAPTURE_HEADER = "X-Mock-Capture"

#: Response header naming the session a tagged call was queued for (``<consumer>@<version>``).
CAPTURE_SESSION_HEADER = "X-Mock-Capture-Session"

#: The path segment that introduces a private capture URL token.
CAPTURE_URL_SEGMENT = "~capture"

#: Longest consumer name or consumer version accepted (characters).
MAX_NAME_CHARS = 200

#: Retention, in days: the default for a tenant without a setting, and the bounds of the setting.
DEFAULT_RETENTION_DAYS = 7
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 30

#: Calls one session stores; beyond it calls are counted as ``session-full`` and not stored.
MAX_CALLS_PER_SESSION = 5000

#: Live sessions one tenant may have; a call that would open another is counted on the tenant.
MAX_LIVE_SESSIONS_PER_TENANT = 500

#: Private capture URLs: the token prefix, and how many days a link lasts by default and at most.
LINK_TOKEN_PREFIX = "mcap_"
DEFAULT_LINK_DAYS = 7
MAX_LINK_DAYS = 30

#: Every stored ``origin``, as the database's check constraint lists them.
ORIGINS = ("spec", "scenario", "session", "chaos", "forced", "off-spec", "rejected")

#: Why a tagged call was not stored, by code; each is said on the response or counted on a session.
REFUSAL_REASONS: Dict[str, str] = {
    "invalid-tag": "X-Mock-Capture must be <consumer>@<version>, e.g. orders-ui@3.4.0.",
    "unknown-link": "This capture URL is unknown, revoked or expired.",
    "link-mismatch": "This capture URL belongs to another mock version.",
    "queue-full": "Too many calls are waiting to be written; this one was not recorded.",
    "session-full": f"The session already holds {MAX_CALLS_PER_SESSION} calls.",
    "too-many-sessions": f"The workspace already has {MAX_LIVE_SESSIONS_PER_TENANT} live capture sessions.",
    "credential-residual": "Something credential-shaped survived redaction, so the call was not stored.",
    "write-failed": "The call could not be written.",
}

#: Header values that ask the guarded upstream proxy to record (PMR-2.4) — not a consumer tag.
_PROXY_OPT_IN_VALUES = frozenset({"on", "1", "true", "yes", "record"})

#: Header values that mean "do not record this call".
_OFF_VALUES = frozenset({"off", "0", "false", "no", ""})

#: Request headers never stored with a call: the tag itself and the stateful session token (kept
#: only as a digest in ``mock_session``).
_UNSTORED_REQUEST_HEADERS = frozenset({"x-mock-capture", "x-mock-session"})

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_TOKEN_SHAPE = re.compile(r"^mcap_[A-Za-z0-9_-]{32,64}$")

#: Serving layers (``apiome_mock.handler.LAYER_*``) and the origin each is stored as.
_LAYER_ORIGINS: Dict[str, str] = {
    "scenario": "scenario",
    "stateful": "session",
    "chaos-error": "chaos",
    "forced-status": "forced",
    "no-operation": "off-spec",
    "method-not-allowed": "off-spec",
    "lifecycle": "off-spec",
    "unknown-scenario": "rejected",
    "request-invalid": "rejected",
    "not-acceptable": "rejected",
    "template-limit": "rejected",
    "unresolved": "rejected",
    "example": "spec",
    "synthesis": "spec",
    "empty": "spec",
    "correlation": "spec",
}


@dataclass(frozen=True)
class ConsumerTag:
    """Whose call this is: a consumer and that consumer's version.

    Attributes:
        consumer: The consumer's name as the caller wrote it (``orders-ui``, ``Orders UI``).
        version: The consumer's version (``3.4.0``, ``3.4.0+a1c9e02``).
    """

    consumer: str
    version: str

    @property
    def label(self) -> str:
        """``<consumer>@<version>``, as written on the response."""
        return f"{self.consumer}@{self.version}"


@dataclass(frozen=True)
class CaptureHeaderProblem:
    """A capture header that could not be used, and why.

    Attributes:
        code: A :data:`REFUSAL_REASONS` key.
        message: The sentence written on the response.
    """

    code: str
    message: str


def name_problem(value: Any, label: str) -> Optional[str]:
    """Why ``value`` cannot be a consumer name or version, or ``None`` when it can.

    Args:
        value: The candidate.
        label: ``"consumer"`` or ``"version"``, named in the message.

    Returns:
        The reason, or ``None``.
    """
    if not isinstance(value, str) or not value.strip():
        return f"The {label} is empty."
    if value != value.strip():
        return f"The {label} has leading or trailing spaces."
    if len(value) > MAX_NAME_CHARS:
        return f"The {label} is longer than {MAX_NAME_CHARS} characters."
    if _CONTROL_CHARS.search(value):
        return f"The {label} contains a control character."
    return None


def classify_capture_header(value: Optional[str]) -> Union[None, str, ConsumerTag, CaptureHeaderProblem]:
    """Read an ``X-Mock-Capture`` request header.

    The value splits on its **last** ``@``, so a scoped package name keeps its own
    (``@acme/web@1.2.0`` is consumer ``@acme/web``, version ``1.2.0``).

    Args:
        value: The header value, or ``None`` when absent.

    Returns:
        ``None`` when the call is not to be recorded (no header, or an ``off`` value);
        ``"proxy"`` for the guarded upstream proxy's own opt-in values;
        a :class:`ConsumerTag` for ``<consumer>@<version>``;
        a :class:`CaptureHeaderProblem` for anything else, so the caller is told it was not
        recorded instead of being ignored.
    """
    if value is None:
        return None
    text = value.strip()
    lowered = text.lower()
    if lowered in _OFF_VALUES:
        return None
    if lowered in _PROXY_OPT_IN_VALUES:
        return "proxy"
    if "@" not in text:
        return CaptureHeaderProblem("invalid-tag", REFUSAL_REASONS["invalid-tag"])
    consumer, _, version = text.rpartition("@")
    for part, label in ((consumer, "consumer"), (version, "version")):
        problem = name_problem(part, label)
        if problem:
            return CaptureHeaderProblem("invalid-tag", f"{REFUSAL_REASONS['invalid-tag']} {problem}")
    return ConsumerTag(consumer=consumer, version=version)


def new_link_token() -> Tuple[str, str, str]:
    """Make a private capture URL token.

    Returns:
        ``(token, token_hash, token_prefix)``: the token to show once, its SHA-256 digest to store,
        and the first characters to show in lists (``mcap_k3f9…``).
    """
    token = LINK_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, link_token_hash(token), token[: len(LINK_TOKEN_PREFIX) + 4]


def link_token_hash(token: str) -> str:
    """The stored digest of a capture URL token (SHA-256, hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_link_token(token: str) -> bool:
    """Whether ``token`` has the shape of a capture URL token (checked before any lookup)."""
    return bool(_TOKEN_SHAPE.match(token))


def mock_session_digest(token: Optional[str]) -> Optional[str]:
    """A short digest of an ``X-Mock-Session`` token: groups a conversation without storing it."""
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def origin_for_layer(layer: str) -> str:
    """The stored ``origin`` for a serving layer; an unknown layer is stored as ``rejected``."""
    return _LAYER_ORIGINS.get(layer, "rejected")


def retention_problem(days: Any) -> Optional[str]:
    """Why ``days`` cannot be a retention setting, or ``None`` when it can."""
    if isinstance(days, bool) or not isinstance(days, int):
        return "Retention must be a whole number of days."
    if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        return f"Retention must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days."
    return None


def decode_body(raw: Optional[bytes], media_type: Optional[str]) -> Tuple[Any, bool, bool]:
    """Turn a raw body into what :func:`redact_call` expects.

    Args:
        raw: The body bytes (``None`` or empty for no body).
        media_type: The declared media type, parameters allowed.

    Returns:
        ``(value, textual, oversize)``: a JSON value or text (``None`` for no body or a dropped
        one), whether it was JSON or text, and whether it was over the capture limit.
    """
    if not raw:
        return None, True, False
    if len(raw) > MAX_CAPTURE_BODY_BYTES:
        return None, True, True
    kind = (media_type or "").split(";", 1)[0].strip().lower()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, False, False
    if "json" in kind:
        try:
            return json.loads(text), True, False
        except ValueError:
            return text, True, False
    if kind.startswith("text/") or any(hint in kind for hint in ("xml", "yaml", "x-www-form-urlencoded")) or not kind:
        return text, True, False
    return None, False, False


@dataclass(frozen=True)
class RedactedCall:
    """One call reduced to what may be stored.

    Attributes:
        request: ``{"method", "path", "query", "headers", "body", "mediaType"?}``.
        response: ``{"status", "headers", "body", "mediaType"?}``.
        redactions: Every removal, as ``{"pointer", "rule", "reason"}``.
    """

    request: Dict[str, Any]
    response: Dict[str, Any]
    redactions: List[Dict[str, str]]


def redact_call(
    *,
    policy: Mapping[str, Any],
    method: str,
    path: str,
    query_params: Sequence[Tuple[str, str]],
    request_headers: Mapping[str, str],
    request_body: Optional[bytes],
    request_media_type: Optional[str],
    status: int,
    response_headers: Mapping[str, str],
    response_body: Optional[bytes],
    response_media_type: Optional[str],
) -> Union[RedactedCall, CaptureHeaderProblem]:
    """Reduce one mock call to its stored form with the mock's redaction rules.

    Args:
        policy: The version's ``proxyCapture`` policy (``{}`` applies the always-on rules alone).
        method: The request method.
        path: The request path, relative to the version prefix.
        query_params: The query as ordered ``(name, value)`` pairs.
        request_headers: The request headers; the capture tag and session token are left out.
        request_body: The raw request body.
        request_media_type: The request's ``Content-Type``.
        status: The response status.
        response_headers: The response headers.
        response_body: The raw response body.
        response_media_type: The response's ``Content-Type``.

    Returns:
        The :class:`RedactedCall`, or a ``credential-residual`` :class:`CaptureHeaderProblem` when
        something credential-shaped survived (the call must then not be stored).
    """
    kept_headers = {
        name: value for name, value in request_headers.items() if name.lower() not in _UNSTORED_REQUEST_HEADERS
    }
    req_value, req_textual, req_oversize = decode_body(request_body, request_media_type)
    res_value, res_textual, res_oversize = decode_body(response_body, response_media_type)
    exchange = redact_exchange(
        policy=policy,
        method=method,
        path=path,
        query_params=query_params,
        request_headers=kept_headers,
        request_body=req_value,
        request_media_type=request_media_type,
        request_body_textual=req_textual,
        request_body_oversize=req_oversize,
        status=status,
        response_headers=dict(response_headers),
        response_body=res_value,
        response_media_type=response_media_type,
        response_body_textual=res_textual,
        response_body_oversize=res_oversize,
    )
    if residual_credential_pointers({"request": exchange.request, "response": exchange.response}):
        return CaptureHeaderProblem("credential-residual", REFUSAL_REASONS["credential-residual"])
    return RedactedCall(
        request=exchange.request,
        response=exchange.response,
        redactions=exchange.decisions_as_json(),
    )
