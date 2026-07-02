"""GraphQL live introspection — MFI-10.3 (#3772).

The third piece of the GraphQL (graph) import adapter. MFI-10.1 turns *SDL text* into a built
``graphql-core`` schema and MFI-10.2 maps that schema onto the canonical model; this module
covers the **other** way an author hands us a GraphQL API — a **live endpoint** with no SDL
file. It runs the standard introspection query against the endpoint, rebuilds the schema from
the ``__schema`` response, and re-prints it to **canonical SDL** so the result is byte-for-byte
the same artifact the file path produces (:class:`~app.graphql_parser.GraphQlParseResult`) and
flows into the same MFI-10.2 normalizer downstream.

What it does, in one call (:func:`introspect_endpoint`):

* **fetch** — POST ``get_introspection_query()`` to the endpoint over an **SSRF-guarded** httpx
  client (:func:`app.ssrf_guard.build_guarded_client`), so a tenant-supplied URL can never be
  pointed at internal/metadata addresses, on the initial request or any redirect hop. Auth is
  attached from the **credential vault** model (:func:`app.mcp_auth.build_auth_headers`) — the
  same ``none``/``bearer``/``header``/``oauth2`` mapping the MCP discovery path uses — so a
  stored bearer token or custom header authenticates the introspection request. The payload is
  supplied **already decrypted** (decryption is the vault's job, MCAT-6.2); this module reads no
  keys.
* **rebuild** — ``build_client_schema`` turns the ``__schema`` payload back into a live
  :class:`~graphql.GraphQLSchema`, which is re-printed and fed through the MFI-10.1 parser so the
  outcome carries canonical SDL, root operations, and type names exactly like a parsed file.
* **fall back** — when introspection is **disabled** (the common production hardening: the
  server answers with a GraphQL error like *"introspection is not allowed"*, or refuses the
  request), the run does **not** fail if the caller supplied an uploaded ``fallback_sdl``: the
  module parses that instead and records *why* it fell back. With no fallback available, the
  result is simply ``ok=False`` with a human reason — never an unhandled exception.

Validity (and the fallback decision) is a **return value**, not an exception:
:func:`introspect_endpoint` always returns a :class:`GraphQlIntrospectionResult` describing what
happened (which source produced the schema, whether introspection succeeded, whether the
fallback was used, the reason, and the underlying parse result). The one thing that *does* raise
is a misconfigured request the caller must fix — an unsafe URL (:class:`SSRFError`) or a
malformed credential (:class:`~app.mcp_auth.CredentialPayloadError`) — surfaced as
:class:`GraphQlIntrospectionError` so a route can return a 4xx.
"""

from __future__ import annotations

import copy
from enum import Enum
from importlib import metadata
from typing import Any, Dict, List, Mapping, Optional

import httpx
from graphql import GraphQLError, GraphQLSchema, build_client_schema, get_introspection_query
from pydantic import BaseModel, ConfigDict, Field

from .graphql_parser import GraphQlDiagnostic, GraphQlParseResult, parse_graphql
from .mcp_auth import AUTH_TYPE_NONE, CredentialPayloadError, build_auth_headers
from .ssrf_guard import SSRFError, build_guarded_client, validate_url

__all__ = [
    "IntrospectionSource",
    "GraphQlIntrospectionResult",
    "GraphQlIntrospectionError",
    "build_introspection_query",
    "schema_from_introspection",
    "sdl_from_introspection",
    "introspect_endpoint",
]

# Default network budget for the introspection POST. Mirrors the import-ingestion fetch
# (``import_ingestion``): a generous total with a tighter connect cap so a dead host fails fast.
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=15.0)

# User-Agent stamped on the introspection request so an endpoint's logs attribute the call.
try:
    _UA = f"apiome-graphql-introspection/{metadata.version('apiome-rest')}"
except metadata.PackageNotFoundError:
    _UA = "apiome-graphql-introspection/dev"

# Hard cap on the introspection response body. A ``__schema`` payload for even a large API is a
# few hundred KB; this bounds a hostile/runaway endpoint without truncating real schemas.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class IntrospectionSource(str, Enum):
    """Which path produced the schema captured in a :class:`GraphQlIntrospectionResult`."""

    #: The live endpoint's ``__schema`` introspection response.
    INTROSPECTION = "introspection"
    #: The caller-supplied uploaded SDL, used because live introspection was unavailable.
    FALLBACK_SDL = "fallback-sdl"


class GraphQlIntrospectionError(Exception):
    """The introspection request was **misconfigured** and must be fixed before retrying.

    Reserved for caller errors a route should surface as a 4xx — an unsafe/blocked URL
    (:class:`~app.ssrf_guard.SSRFError`) or a malformed credential
    (:class:`~app.mcp_auth.CredentialPayloadError`). A *disabled* endpoint or a transient network
    failure is **not** this error: those are ordinary outcomes captured on
    :class:`GraphQlIntrospectionResult` (so the uploaded-SDL fallback can take over).
    """


class GraphQlIntrospectionResult(BaseModel):
    """The outcome of introspecting a live GraphQL endpoint (with optional SDL fallback).

    A successful run has :attr:`ok` ``True``, a :attr:`source` of either
    :attr:`IntrospectionSource.INTROSPECTION` (the live schema) or
    :attr:`IntrospectionSource.FALLBACK_SDL` (the uploaded SDL took over), and a populated
    :attr:`parse_result` carrying the canonical SDL / roots / type names — the same
    :class:`~app.graphql_parser.GraphQlParseResult` the file path produces. A failed run has
    :attr:`ok` ``False``, ``source`` ``None``, and a human :attr:`reason`.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool = Field(description="True when a schema was obtained (live or via fallback) and built.")
    source: Optional[IntrospectionSource] = Field(
        default=None,
        description="Which path produced the schema; ``None`` when neither succeeded.",
    )
    introspection_ok: bool = Field(
        default=False,
        description="Whether the live introspection query itself succeeded (independent of fallback).",
    )
    fallback_used: bool = Field(
        default=False,
        description="True when the uploaded ``fallback_sdl`` was used because introspection was unavailable.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human explanation of why introspection was unavailable / the fallback was used "
        "(``None`` on a clean live introspection).",
    )
    parse_result: Optional[GraphQlParseResult] = Field(
        default=None,
        description="The canonical parse outcome (SDL/roots/types/diagnostics); ``None`` when nothing built.",
    )

    @property
    def sdl(self) -> Optional[str]:
        """The canonical SDL of the obtained schema, or ``None`` when nothing built."""
        return self.parse_result.sdl if self.parse_result is not None else None


# ===========================================================================
# graphql-core seams (pure, no I/O)
# ===========================================================================


def build_introspection_query(*, descriptions: bool = True) -> str:
    """Return the standard GraphQL introspection query to POST to an endpoint.

    A thin wrapper over ``graphql-core``'s :func:`graphql.get_introspection_query` pinned to its
    conservative defaults (newer optional selections — ``specifiedByURL``, repeatable directives,
    input-value deprecation — are left off) so the query is accepted by the widest range of
    server versions.

    Args:
        descriptions: Whether to request type/field ``description`` text (default ``True``).

    Returns:
        The introspection query document as a string.
    """
    return get_introspection_query(descriptions=descriptions)


def schema_from_introspection(introspection: Mapping[str, Any]) -> GraphQLSchema:
    """Rebuild a live :class:`~graphql.GraphQLSchema` from an introspection ``data`` payload.

    Args:
        introspection: The ``data`` object of an introspection response — the mapping that holds
            the ``__schema`` key (i.e. ``response_json["data"]``).

    Returns:
        The reconstructed schema.

    Raises:
        GraphQlIntrospectionError: If the payload is not a usable introspection result (missing
            ``__schema`` or structurally invalid).
    """
    if not isinstance(introspection, Mapping) or "__schema" not in introspection:
        raise GraphQlIntrospectionError(
            "introspection response did not contain a '__schema' payload"
        )
    try:
        # ``build_client_schema`` wants a plain dict; coerce a generic mapping for safety.
        return build_client_schema(dict(introspection))  # type: ignore[arg-type]
    except (GraphQLError, TypeError, KeyError, ValueError) as exc:
        message = exc.message if isinstance(exc, GraphQLError) else str(exc)
        raise GraphQlIntrospectionError(
            f"could not rebuild schema from introspection response: {message}"
        ) from exc


def sdl_from_introspection(introspection: Mapping[str, Any]) -> str:
    """Rebuild the schema from an introspection payload and re-print it as canonical SDL.

    Args:
        introspection: The ``data`` object of an introspection response (holds ``__schema``).

    Returns:
        The canonical SDL of the introspected schema.

    Raises:
        GraphQlIntrospectionError: If the payload cannot be rebuilt into a schema.
    """
    from graphql import print_schema

    return print_schema(schema_from_introspection(introspection))


# ===========================================================================
# Network fetch (SSRF-guarded, vault-authenticated)
# ===========================================================================


class _FetchOutcome:
    """Internal: the classified result of one introspection POST.

    Exactly one of :attr:`data` / :attr:`unavailable_reason` is meaningful — ``data`` holds the
    usable introspection payload on success, otherwise ``unavailable_reason`` says (in
    secret-free terms) why the endpoint could not be introspected so the caller can fall back.
    """

    __slots__ = ("data", "unavailable_reason")

    def __init__(
        self, *, data: Optional[Dict[str, Any]] = None, unavailable_reason: Optional[str] = None
    ) -> None:
        self.data = data
        self.unavailable_reason = unavailable_reason


def _summarize_graphql_errors(errors: Any) -> str:
    """Build a short, secret-free reason string from a response body's ``errors`` array."""
    messages: List[str] = []
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, Mapping):
                message = err.get("message")
                if isinstance(message, str) and message.strip():
                    messages.append(message.strip())
    if not messages:
        return "endpoint returned GraphQL errors with no usable schema"
    joined = "; ".join(messages[:3])
    lowered = joined.lower()
    if "introspection" in lowered and (
        "not allowed" in lowered or "disabled" in lowered or "denied" in lowered
    ):
        return f"introspection is disabled on the endpoint ({joined})"
    return f"endpoint returned GraphQL errors: {joined}"


def _resolve_auth_headers(
    auth_type: Optional[str], auth_payload: Optional[Mapping[str, Any]]
) -> Dict[str, str]:
    """Map a credential-vault entry onto request headers, or ``{}`` for no/anonymous auth.

    Reuses the shared credential-vault auth model (:func:`app.mcp_auth.build_auth_headers`): the
    ``payload`` is supplied **decrypted** and only ever yields headers (never a URL).

    Raises:
        GraphQlIntrospectionError: If the credential is malformed for its ``auth_type``.
    """
    if not auth_type or auth_type == AUTH_TYPE_NONE:
        return {}
    # Explicitly reject a missing payload for any auth type that requires credentials — avoids the
    # silent `auth_payload or {}` default which could produce incomplete headers.
    if auth_payload is None:
        raise GraphQlIntrospectionError(
            f"auth_type={auth_type!r} requires a credential payload (auth_payload)"
        )
    try:
        return build_auth_headers(auth_type, dict(auth_payload))
    except CredentialPayloadError as exc:
        raise GraphQlIntrospectionError(str(exc)) from exc


def _post_introspection(
    endpoint_url: str,
    query: str,
    headers: Mapping[str, str],
    timeout: httpx.Timeout,
    client: Optional[httpx.Client],
) -> _FetchOutcome:
    """POST the introspection query and classify the response.

    A usable ``data`` payload (one carrying ``__schema``) is returned for the success path. Every
    "introspection is unavailable" condition — a transport failure, a non-2xx status, a body of
    GraphQL ``errors``, non-JSON, or a missing ``__schema`` — is captured as an
    ``unavailable_reason`` (never raised), so the caller can fall back to uploaded SDL.

    The request runs over an SSRF-guarded client (built here unless one is injected for testing),
    so every hop — including redirects — is re-validated against the SSRF policy.
    """
    request_headers = {
        "User-Agent": _UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
        **dict(headers),
    }
    payload = {"query": query}

    owns_client = client is None
    http_client = client if client is not None else build_guarded_client(
        timeout=timeout, follow_redirects=True
    )
    try:
        response = http_client.post(endpoint_url, json=payload, headers=request_headers)
    except SSRFError:
        # A redirect hop pointed at a non-public address — a configuration/security problem the
        # caller must fix, not a "fall back to SDL" condition. Re-raise for the orchestrator.
        raise
    except httpx.HTTPError as exc:
        return _FetchOutcome(unavailable_reason=f"could not reach endpoint: {exc}")
    finally:
        if owns_client:
            http_client.close()

    if response.status_code >= 400:
        return _FetchOutcome(
            unavailable_reason=(
                f"endpoint returned HTTP {response.status_code}; introspection may be disabled "
                "or the endpoint may require different auth"
            )
        )

    # Reject an over-large body before parsing/building it — defence in depth against a
    # runaway or hostile endpoint returning a pathologically huge "schema".
    if len(response.content) > _MAX_RESPONSE_BYTES:
        return _FetchOutcome(
            unavailable_reason=(
                f"introspection response exceeds the {_MAX_RESPONSE_BYTES}-byte limit"
            )
        )

    try:
        body = response.json()
    except ValueError:
        return _FetchOutcome(unavailable_reason="endpoint did not return a JSON introspection response")

    if not isinstance(body, Mapping):
        return _FetchOutcome(unavailable_reason="introspection response was not a JSON object")

    data = body.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("__schema"), Mapping):
        # Usable schema present. Per spec a response may carry both ``data`` and ``errors``
        # (partial), but a full ``__schema`` is all we need; ignore any advisory errors.
        # Deep-copy the data so downstream parsing (build_client_schema → print_schema) can
        # mutate nested structures without touching the caller's original payload.
        return _FetchOutcome(data=copy.deepcopy(data))

    # No usable schema. If the body explained itself with ``errors`` (the disabled-introspection
    # case), surface that reason; otherwise report the generic shape problem.
    if body.get("errors"):
        return _FetchOutcome(unavailable_reason=_summarize_graphql_errors(body.get("errors")))
    return _FetchOutcome(
        unavailable_reason="introspection response contained no '__schema' payload"
    )


# ===========================================================================
# Orchestration
# ===========================================================================


def _parse_or_fallback(
    sdl: str, *, source: IntrospectionSource, source_label: str, reason: Optional[str]
) -> GraphQlIntrospectionResult:
    """Run ``sdl`` through the MFI-10.1 parser and wrap it as an introspection result."""
    parse_result = parse_graphql(sdl, source_label=source_label)
    return GraphQlIntrospectionResult(
        ok=parse_result.ok,
        source=source if parse_result.ok else None,
        introspection_ok=source == IntrospectionSource.INTROSPECTION and parse_result.ok,
        fallback_used=source == IntrospectionSource.FALLBACK_SDL,
        reason=reason,
        parse_result=parse_result,
    )


def introspect_endpoint(
    endpoint_url: str,
    *,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: Optional[httpx.Timeout] = None,
    fallback_sdl: Optional[str] = None,
    descriptions: bool = True,
    source_label: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> GraphQlIntrospectionResult:
    """Introspect a live GraphQL endpoint, falling back to uploaded SDL when it is disabled.

    Posts the standard introspection query to ``endpoint_url`` (SSRF-guarded, optionally
    authenticated from the credential vault), rebuilds the schema from the ``__schema`` response,
    and re-prints it through the MFI-10.1 parser so the canonical SDL / roots / type names match
    the file-import path exactly. When the endpoint has introspection **disabled** (or is briefly
    unreachable), the uploaded ``fallback_sdl`` — if supplied — is parsed instead and the reason
    is recorded.

    Validity is a *return value*: the function returns a :class:`GraphQlIntrospectionResult`
    describing the outcome rather than raising for a disabled endpoint. It raises only for a
    request the caller must fix (an unsafe URL or a malformed credential).

    Args:
        endpoint_url: The GraphQL endpoint to introspect (http/https; validated for SSRF).
        auth_type: Credential-vault auth type (``none``/``bearer``/``header``/``oauth2``); ``None``
            or ``"none"`` runs the request unauthenticated.
        auth_payload: The **decrypted** credential payload for ``auth_type`` (e.g.
            ``{"token": "…"}`` for ``bearer``). Ignored for ``none``.
        headers: Extra request headers merged in (after auth headers, so a caller can add a tenant
            header without overriding the credential).
        timeout: httpx timeout; defaults to a 30s total / 15s connect budget.
        fallback_sdl: Uploaded SDL to parse when live introspection is unavailable.
        descriptions: Whether the introspection query requests description text.
        source_label: Label used to attribute parse diagnostics; defaults to the endpoint URL (or
            ``"fallback.graphql"`` for the fallback path).
        client: An httpx client to use instead of building an SSRF-guarded one — a dependency-
            injection seam for tests. Callers in production omit this so the guarded client is used.

    Returns:
        A :class:`GraphQlIntrospectionResult`.

    Raises:
        GraphQlIntrospectionError: If ``endpoint_url`` is rejected by the SSRF policy or the
            credential is malformed for its ``auth_type``.
    """
    label = source_label or endpoint_url

    # 1) Reject an unsafe URL up front with a clean error (the guarded client also re-checks every
    #    hop). An SSRF rejection is a config/security problem, never a "fall back to SDL" case.
    try:
        validate_url(endpoint_url)
    except SSRFError as exc:
        raise GraphQlIntrospectionError(str(exc)) from exc

    # 2) Resolve auth headers from the credential vault (raises on a malformed credential).
    auth_headers = _resolve_auth_headers(auth_type, auth_payload)
    merged_headers = {**auth_headers, **dict(headers or {})}

    # 3) Fetch + classify. An SSRF rejection on a redirect hop is the one fetch failure that
    #    raises (the caller must fix it); everything else becomes a fall-back reason.
    query = build_introspection_query(descriptions=descriptions)
    try:
        outcome = _post_introspection(
            endpoint_url, query, merged_headers, timeout or _HTTP_TIMEOUT, client
        )
    except SSRFError as exc:
        raise GraphQlIntrospectionError(str(exc)) from exc

    # 4a) Live introspection succeeded: rebuild → canonical SDL → parse.
    if outcome.data is not None:
        try:
            sdl = sdl_from_introspection(outcome.data)
        except GraphQlIntrospectionError as exc:
            # The endpoint answered but the payload would not rebuild — treat as unavailable so
            # the uploaded SDL can still rescue the import.
            return _unavailable(label, fallback_sdl, reason=str(exc))
        return _parse_or_fallback(
            sdl, source=IntrospectionSource.INTROSPECTION, source_label=label, reason=None
        )

    # 4b) Introspection unavailable (disabled / unreachable / malformed response).
    return _unavailable(label, fallback_sdl, reason=outcome.unavailable_reason)


def _unavailable(
    endpoint_label: str, fallback_sdl: Optional[str], *, reason: Optional[str]
) -> GraphQlIntrospectionResult:
    """Build the result for an introspection that could not produce a live schema.

    Falls back to ``fallback_sdl`` when one is supplied; otherwise returns a not-``ok`` result
    carrying the reason as a diagnostic so a caller can surface why nothing was imported.
    """
    reason = reason or "live introspection was unavailable"
    if fallback_sdl is not None and fallback_sdl.strip():
        fallback = _parse_or_fallback(
            fallback_sdl,
            source=IntrospectionSource.FALLBACK_SDL,
            source_label="fallback.graphql",
            reason=reason,
        )
        if fallback.ok:
            return fallback
        # The uploaded SDL itself did not build; report that alongside the introspection reason.
        return GraphQlIntrospectionResult(
            ok=False,
            source=None,
            introspection_ok=False,
            fallback_used=True,
            reason=f"{reason}; uploaded SDL fallback also failed to build",
            parse_result=fallback.parse_result,
        )

    return GraphQlIntrospectionResult(
        ok=False,
        source=None,
        introspection_ok=False,
        fallback_used=False,
        reason=reason,
        parse_result=GraphQlParseResult(
            ok=False, diagnostics=[GraphQlDiagnostic(message=reason)]
        ),
    )
