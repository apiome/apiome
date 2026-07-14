"""Redacted JSON-RPC protocol transcript for passive MCP discovery (CLX-3.1, #4855).

The MCP lint engine (:mod:`app.mcp_lint`) can only see the *surface* a server advertises —
its tools, resources, and prompts. It cannot see how the server *behaved* while that surface
was being enumerated: did it echo a protocol version it was never offered? did it answer with
a malformed JSON-RPC envelope? did its pagination cursor terminate? Those questions are
answerable only from the wire, so this module records one.

A :class:`ProtocolTranscript` is the evidence-grade record of the JSON-RPC exchanges that
*ordinary discovery already performs* — the ``initialize`` handshake and the paginated
``*/list`` calls. It adds **no** network traffic of its own: a :class:`TranscriptRecorder` is
attached to the transport, which calls it from the one chokepoint every request passes through
(:meth:`app.mcp_client.transport_http.StreamableHttpTransport.request`).

Two invariants make this safe to run against any cataloged server, and both are enforced here
rather than left to the caller's good behaviour:

* **Passive only.** :data:`PASSIVE_METHODS` is an allow-list of the read-only protocol methods
  discovery uses. :meth:`TranscriptRecorder.record` refuses anything else, so a business tool
  can never be invoked in the name of conformance evidence — ``tools/call`` is not on the list
  and cannot be recorded. The acceptance criterion "passive checks never invoke arbitrary
  business tools" is therefore a property of the type, not of a convention.
* **Redacted at capture.** Nothing verbatim from the wire is retained. Request parameters are
  reduced to their key names; results are reduced to their top-level key names plus an item
  count; opaque pagination cursors are stored only as a salted-free SHA-256 prefix (enough to
  detect a *cycle* — the same cursor served twice — without persisting the cursor's contents,
  which are server-defined and may encode a query or an identifier); and error messages are
  scrubbed of credential-shaped substrings by :func:`redact_text` before being kept. A
  transcript is therefore safe to persist as evidence and to return over the API.

The transcript is *observational*, so — unlike the surface — it is not deterministic across
runs: a server may page differently or fail intermittently. That split is deliberate and is
the contract the conformance engine relies on (see :mod:`app.mcp_conformance`): rules derived
from the stored surface are deterministic and re-runnable offline, while rules derived from a
transcript are live evidence and only run when a transcript was captured.

Reference (MCP 2025-06-18):
  * lifecycle / initialize  — https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
  * transports & envelopes  — https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  * pagination              — https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

# --- Passive-method allow-list ---------------------------------------------------------------
# The complete set of JSON-RPC methods MCP discovery performs. Every one is read-only: the
# handshake, its completion notification, and the four paginated list endpoints. Recording is
# refused for anything outside this set, which structurally excludes ``tools/call``,
# ``resources/read``, ``prompts/get``, and every server-defined business method.

#: The ``initialize`` handshake method (the only method carrying negotiation state).
METHOD_INITIALIZE = "initialize"

#: The notification that completes the handshake (no response, so never an exchange).
METHOD_INITIALIZED = "notifications/initialized"

#: The four paginated capability-list methods, mirroring
#: :data:`app.mcp_client.discovery.LIST_METHODS`.
LIST_METHODS: Tuple[str, ...] = (
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
)

#: Every method a transcript may record. An allow-list, not a deny-list: a method that is not
#: named here — notably ``tools/call`` — cannot be recorded, so conformance evidence can never
#: be the pretext for invoking a business tool.
PASSIVE_METHODS: frozenset = frozenset((METHOD_INITIALIZE, METHOD_INITIALIZED, *LIST_METHODS))

#: Result key holding the page's item array, per list method (the ``items_key`` of
#: :data:`app.mcp_client.discovery.LIST_METHODS`). Used to count items without keeping them.
LIST_ITEMS_KEY: Mapping[str, str] = {
    "tools/list": "tools",
    "resources/list": "resources",
    "resources/templates/list": "resourceTemplates",
    "prompts/list": "prompts",
}

#: The JSON-RPC version every MCP envelope must carry.
JSONRPC_VERSION = "2.0"


class PassiveMethodError(ValueError):
    """Raised when a non-passive JSON-RPC method is offered to a transcript recorder.

    Signals a programming error — a caller tried to record (and therefore had performed) a
    method outside :data:`PASSIVE_METHODS`, such as ``tools/call``. The conformance lane is
    passive by construction, so this is fatal rather than a finding.
    """

    def __init__(self, method: str) -> None:
        super().__init__(
            f"method '{method}' is not a passive discovery method; "
            f"conformance evidence may only be recorded for {sorted(PASSIVE_METHODS)}"
        )
        self.method = method


# --- Redaction --------------------------------------------------------------------------------
# A server-authored error message is free text and may quote back a request URL, an
# Authorization header, or a token it rejected. Before any such string is retained it is
# scrubbed: credential-shaped substrings are replaced with a fixed placeholder. The patterns
# below are deliberately broad — over-redacting an error message costs nothing (the code and
# shape are what the rules read), while under-redacting would persist a secret.

#: Placeholder substituted for every redacted span.
REDACTED = "[redacted]"

#: Longest error message retained (characters), applied *after* redaction. Bounds the evidence
#: payload so a hostile server cannot inflate a stored transcript with a megabyte-long message.
MAX_MESSAGE_CHARS = 200

#: Credential-shaped patterns scrubbed from any retained free text, in application order:
#: an ``Authorization``-style scheme + credential; a ``key=value`` pair whose key names a
#: secret; and any long opaque token-like run (JWTs, API keys, hex/base64 secrets).
_REDACTION_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:bearer|basic|token|apikey|api[-_ ]key)\s+\S+", re.IGNORECASE),
    re.compile(
        r"\b\w*(?:secret|token|password|passwd|credential|api[-_]?key|authorization)\w*"
        r"\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
)


def redact_text(text: Optional[str]) -> Optional[str]:
    """Scrub credential-shaped substrings from ``text`` and bound its length.

    Applies every pattern in :data:`_REDACTION_PATTERNS` — auth headers, ``key=value`` pairs
    naming a secret, and long opaque tokens — replacing each match with :data:`REDACTED`, then
    truncates the result to :data:`MAX_MESSAGE_CHARS`. Used on any server-authored free text
    (today: JSON-RPC error messages) before it is retained as evidence.

    Args:
        text: The raw text to scrub. ``None`` and blank pass through unchanged.

    Returns:
        The redacted, length-bounded text, or ``None`` when ``text`` was ``None``.
    """
    if text is None:
        return None
    scrubbed = text
    for pattern in _REDACTION_PATTERNS:
        scrubbed = pattern.sub(REDACTED, scrubbed)
    if len(scrubbed) > MAX_MESSAGE_CHARS:
        scrubbed = scrubbed[:MAX_MESSAGE_CHARS] + "…"
    return scrubbed


def cursor_digest(cursor: Optional[str]) -> Optional[str]:
    """Return a stable, non-reversible digest of an opaque pagination ``cursor``.

    A ``nextCursor`` is server-defined and opaque; per the pagination spec a client must not
    parse it, and it may encode a query, an offset, or a record id. It is therefore never
    stored verbatim. A SHA-256 prefix preserves the only property the conformance rules need —
    *equality*, so a cursor served twice (a non-terminating cycle) is detectable — while
    disclosing nothing about the cursor's contents.

    Args:
        cursor: The opaque cursor string, or ``None`` when the page carried none.

    Returns:
        A 16-hex-character digest, or ``None`` when ``cursor`` is ``None``.
    """
    if cursor is None:
        return None
    return hashlib.sha256(cursor.encode("utf-8")).hexdigest()[:16]


def _key_names(value: Any) -> Tuple[str, ...]:
    """Return the sorted top-level key names of a JSON object, or ``()`` for a non-object.

    Only *names* are kept — never values — so a result/params object contributes its shape to
    the transcript without contributing any of its data.
    """
    if not isinstance(value, Mapping):
        return ()
    return tuple(sorted(str(key) for key in value))


# --- Exchange ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolExchange:
    """One recorded request/response pair, reduced to its redacted shape.

    Everything here is either a structural fact (a key name, a count, a status code) or a
    non-reversible digest. No parameter value, result item, or raw cursor is retained.

    Attributes:
        method: The JSON-RPC method; always a member of :data:`PASSIVE_METHODS`.
        request_id: The request's JSON-RPC id, stringified (ids may be int or str).
        param_keys: Sorted top-level key names of the request ``params`` (names only).
        cursor_sent: Digest of the ``cursor`` param, or ``None`` when the request sent none
            (i.e. it asked for the first page).
        http_status: The HTTP status the transport observed for the exchange.
        jsonrpc: The ``jsonrpc`` member the response envelope carried, verbatim. ``None``
            when the envelope omitted it — itself a conformance defect.
        id_echoed: Whether the response echoed the request's id, as JSON-RPC requires.
        error_code: The JSON-RPC error code, or ``None`` on a successful result.
        error_message: The error's message, redacted by :func:`redact_text`; ``None`` on
            success.
        result_keys: Sorted top-level key names of the ``result`` object (names only).
        item_count: For a list method, the number of items on this page; ``None`` otherwise.
        next_cursor: Digest of the ``nextCursor`` the page advertised, or ``None`` when the
            page was terminal (no further pages).
    """

    method: str
    request_id: str
    param_keys: Tuple[str, ...] = ()
    cursor_sent: Optional[str] = None
    http_status: int = 200
    jsonrpc: Optional[str] = None
    id_echoed: bool = True
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    result_keys: Tuple[str, ...] = ()
    item_count: Optional[int] = None
    next_cursor: Optional[str] = None

    @property
    def is_error(self) -> bool:
        """True when the server answered with a JSON-RPC error rather than a result."""
        return self.error_code is not None

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict of this exchange (stable key set)."""
        return {
            "method": self.method,
            "request_id": self.request_id,
            "param_keys": list(self.param_keys),
            "cursor_sent": self.cursor_sent,
            "http_status": self.http_status,
            "jsonrpc": self.jsonrpc,
            "id_echoed": self.id_echoed,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result_keys": list(self.result_keys),
            "item_count": self.item_count,
            "next_cursor": self.next_cursor,
        }


# --- Transcript -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolTranscript:
    """The redacted record of one passive discovery session's JSON-RPC exchanges.

    Attributes:
        exchanges: Every recorded exchange, in the order it occurred on the wire.
        requested_version: The protocol version the client offered first in ``initialize``.
        negotiated_version: The version the server answered with, verbatim — including a
            version the client does not speak, which is precisely what the version rules
            need to see.
        redacted: Always ``True``; carried explicitly so a persisted transcript states, in
            the payload itself, that it is not verbatim wire data.
    """

    exchanges: Tuple[ProtocolExchange, ...] = ()
    requested_version: Optional[str] = None
    negotiated_version: Optional[str] = None
    redacted: bool = True

    def for_method(self, method: str) -> Tuple[ProtocolExchange, ...]:
        """Return every exchange recorded for ``method``, in wire order.

        For a paginated list method this is one exchange per page fetched, so the tuple's
        length is the page count and its cursors describe the pagination walk.
        """
        return tuple(x for x in self.exchanges if x.method == method)

    def initialize_exchange(self) -> Optional[ProtocolExchange]:
        """Return the ``initialize`` exchange, or ``None`` when none was recorded.

        A transcript may legitimately hold several ``initialize`` exchanges when the handshake
        fell back to an older protocol version after a rejection; the *last* one is the
        exchange that actually established the session, so that is the one returned.
        """
        attempts = self.for_method(METHOD_INITIALIZE)
        return attempts[-1] if attempts else None

    def as_dict(self) -> Dict[str, Any]:
        """Return the whole transcript as a JSON-ready dict (the persisted evidence payload)."""
        return {
            "redacted": self.redacted,
            "requested_version": self.requested_version,
            "negotiated_version": self.negotiated_version,
            "exchanges": [exchange.as_dict() for exchange in self.exchanges],
        }

    def fingerprint(self) -> str:
        """Return a stable hash over the redacted transcript, for identity and staleness checks.

        Computed over :meth:`as_dict` with sorted keys and no whitespace, so two transcripts
        recording the same observed behaviour always hash equal. Note this is *not* expected to
        be stable across two discoveries of the same server — a transcript is observational, and
        page counts or request ids legitimately differ between runs. It identifies *this*
        recording, which is what an immutable evidence row needs.
        """
        return hashlib.sha256(
            json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProtocolTranscript":
        """Rebuild a transcript from its :meth:`as_dict` form (e.g. a persisted evidence row).

        Unknown keys are ignored and absent keys fall back to their defaults, so a transcript
        written by an older revision still loads.

        Args:
            payload: A mapping previously produced by :meth:`as_dict`.

        Returns:
            The reconstructed :class:`ProtocolTranscript`.
        """
        raw_exchanges = payload.get("exchanges")
        exchanges: List[ProtocolExchange] = []
        for entry in raw_exchanges if isinstance(raw_exchanges, list) else []:
            if not isinstance(entry, Mapping):
                continue
            exchanges.append(
                ProtocolExchange(
                    method=str(entry.get("method", "")),
                    request_id=str(entry.get("request_id", "")),
                    param_keys=tuple(entry.get("param_keys") or ()),
                    cursor_sent=entry.get("cursor_sent"),
                    http_status=int(entry.get("http_status") or 0),
                    jsonrpc=entry.get("jsonrpc"),
                    id_echoed=bool(entry.get("id_echoed", True)),
                    error_code=entry.get("error_code"),
                    error_message=entry.get("error_message"),
                    result_keys=tuple(entry.get("result_keys") or ()),
                    item_count=entry.get("item_count"),
                    next_cursor=entry.get("next_cursor"),
                )
            )
        return cls(
            exchanges=tuple(exchanges),
            requested_version=payload.get("requested_version"),
            negotiated_version=payload.get("negotiated_version"),
            redacted=bool(payload.get("redacted", True)),
        )


# --- Recorder ---------------------------------------------------------------------------------


@dataclass
class TranscriptRecorder:
    """Accumulates :class:`ProtocolExchange` entries during one discovery session.

    Attached to a :class:`~app.mcp_client.transport_http.StreamableHttpTransport`, which calls
    :meth:`record` once per JSON-RPC request from the single chokepoint every request passes
    through. The recorder performs no I/O and issues no requests of its own — it only observes
    the exchanges discovery was already going to make — so capturing a transcript costs nothing
    beyond the memory of the reduced records.

    Mutable by design (it is a session-scoped accumulator); :meth:`transcript` freezes the
    accumulated state into an immutable :class:`ProtocolTranscript` for storage and linting.
    """

    exchanges: List[ProtocolExchange] = field(default_factory=list)
    requested_version: Optional[str] = None
    negotiated_version: Optional[str] = None

    def record(
        self,
        method: str,
        *,
        request_id: Any,
        params: Optional[Mapping[str, Any]],
        http_status: int,
        envelope: Optional[Mapping[str, Any]],
    ) -> None:
        """Reduce one request/response pair to a redacted exchange and retain it.

        Args:
            method: The JSON-RPC method just performed. MUST be in :data:`PASSIVE_METHODS`.
            request_id: The request's JSON-RPC id (int or str).
            params: The request's ``params`` object, if any. Only its key names and the
                ``cursor``'s digest are kept; no value is retained.
            http_status: The HTTP status observed for the exchange.
            envelope: The response's JSON-RPC envelope. ``None`` when the response could not
                be parsed at all, which is recorded as a malformed envelope rather than
                dropped — a server that answers unparseable JSON is exactly what the envelope
                rules exist to catch.

        Raises:
            PassiveMethodError: If ``method`` is not a passive discovery method. Recording is
                refused rather than sanitized, so a non-passive call can never be laundered
                into conformance evidence.
        """
        if method not in PASSIVE_METHODS:
            raise PassiveMethodError(method)

        params = params if isinstance(params, Mapping) else None
        cursor = params.get("cursor") if params else None
        envelope = envelope if isinstance(envelope, Mapping) else None

        error = envelope.get("error") if envelope else None
        error = error if isinstance(error, Mapping) else None
        result = envelope.get("result") if envelope else None

        self.exchanges.append(
            ProtocolExchange(
                method=method,
                request_id=str(request_id),
                param_keys=_key_names(params),
                cursor_sent=cursor_digest(cursor if isinstance(cursor, str) else None),
                http_status=http_status,
                jsonrpc=envelope.get("jsonrpc") if envelope else None,
                # An envelope that could not be parsed echoed nothing; a parsed one must echo
                # the id it answers. Compared as strings because a server may return the id
                # with a different JSON type than it was sent with.
                id_echoed=(
                    str(envelope.get("id")) == str(request_id) if envelope else False
                ),
                error_code=_int_or_none(error.get("code")) if error else None,
                error_message=(
                    redact_text(str(error.get("message", ""))) if error else None
                ),
                result_keys=_key_names(result),
                item_count=_item_count(method, result),
                next_cursor=_next_cursor_digest(result),
            )
        )

    def note_versions(
        self, *, requested: Optional[str] = None, negotiated: Optional[str] = None
    ) -> None:
        """Record the protocol versions the handshake offered and settled on.

        Called by the handshake, which is the only layer that knows what the client *asked*
        for — the transport sees only what came back. Both arguments are optional so a caller
        can note the requested version before the response arrives and the negotiated version
        after.
        """
        if requested is not None:
            self.requested_version = requested
        if negotiated is not None:
            self.negotiated_version = negotiated

    def transcript(self) -> ProtocolTranscript:
        """Freeze the accumulated exchanges into an immutable :class:`ProtocolTranscript`."""
        return ProtocolTranscript(
            exchanges=tuple(self.exchanges),
            requested_version=self.requested_version,
            negotiated_version=self.negotiated_version,
        )


def _int_or_none(value: Any) -> Optional[int]:
    """Coerce a JSON-RPC error ``code`` to ``int``, or ``None`` when it is not numeric.

    A non-integer code is itself a defect (JSON-RPC requires an integer), so it is normalized
    to ``None`` rather than guessed at; the envelope rules report the malformed error object.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _item_count(method: str, result: Any) -> Optional[int]:
    """Return how many items a list method's page carried, or ``None`` for a non-list method.

    Reads the page's item array under the method's documented ``items_key``
    (:data:`LIST_ITEMS_KEY`) and returns only its length — the items themselves are never
    retained. A list method whose result omits the array (or holds a non-array there) yields
    ``None``, which the envelope rules read as a missing item array.
    """
    items_key = LIST_ITEMS_KEY.get(method)
    if items_key is None or not isinstance(result, Mapping):
        return None
    items = result.get(items_key)
    return len(items) if isinstance(items, list) else None


def _next_cursor_digest(result: Any) -> Optional[str]:
    """Return the digest of a page's ``nextCursor``, or ``None`` when the page was terminal."""
    if not isinstance(result, Mapping):
        return None
    cursor = result.get("nextCursor")
    return cursor_digest(cursor) if isinstance(cursor, str) else None
