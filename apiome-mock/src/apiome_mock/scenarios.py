"""Scenario overrides for the hosted mock (#4454, SIM-4.2).

Named scenarios ("happy path", "quota exceeded", ...) are authored in the
Control Panel and stored in the ``versions.mock_settings`` JSONB column under
the ``"scenarios"`` key::

    {
      "scenarios": {
        "quota-exceeded": {
          "description": "Every list call is throttled.",
          "operations": {
            "GET /pets": {
              "responses": [
                {"status": 429, "headers": {"Retry-After": "60"}, "body": {...}}
              ]
            }
          }
        }
      }
    }

Consumers select a scenario per request with the ``X-Mock-Scenario`` header.
An operation entry with one response is a fixed canned response; two or more
responses form a *sequence* (first call -> first response, second call ->
second response, ...; calls past the end stick on the last response). The
sequence position is tracked in the SIM-4.1 session store, keyed by the
``X-Mock-Session`` token when present, else by scenario + client IP.

Parsing here is deliberately lenient: invalid entries are skipped so a
malformed stored settings blob can never break the runtime. Author-time
validation (including spec response-schema checks) happens in apiome-rest
when the scenarios are saved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from apiome_mock.chaos import ChaosConfig, parse_chaos_block
from apiome_mock.session_store import SessionKey, SessionStore, SessionStoreError

MOCK_SCENARIO_HEADER = "X-Mock-Scenario"
"""Request header naming the scenario to apply; absent -> default behavior."""

SCENARIO_CALL_HEADER = "X-Mock-Scenario-Call"
"""Response header echoing the 1-based sequence call number (sequences only)."""

_SEQUENCE_NAMESPACE = "__mock_scenario_sequence__"
_IP_SESSION_PREFIX = "__mock_scenario_ip__"

# Headers a canned response may never set: they are managed by the framework
# and overriding them can corrupt the HTTP framing of the response.
_RESERVED_HEADERS = frozenset({"content-length", "transfer-encoding", "connection"})

_MIN_STATUS = 100
_MAX_STATUS = 599


@dataclass(frozen=True)
class ScenarioResponse:
    """One canned response (status + headers + optional body)."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: Any
    has_body: bool
    media_type: str


@dataclass(frozen=True)
class Scenario:
    """A named scenario mapping operation keys to canned response sequences."""

    name: str
    description: str
    operations: Mapping[str, tuple[ScenarioResponse, ...]]
    chaos: ChaosConfig | None = None
    """Scenario-scoped chaos knobs (#4455, SIM-4.3); ``None`` -> version-level chaos applies."""


def normalize_operation_key(raw: Any) -> str | None:
    """Normalize an operation key to canonical ``"METHOD /template"`` form.

    Returns ``None`` when ``raw`` is not a ``"method path"`` string (method
    alphabetic, path starting with ``/``).
    """
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split(None, 1)
    if len(parts) != 2:
        return None
    method, path = parts
    if not method.isalpha() or not path.startswith("/"):
        return None
    return f"{method.upper()} {path}"


def parse_mock_scenario_name(request: Request) -> str | None:
    """Return the ``X-Mock-Scenario`` header value, or ``None`` when absent/blank."""
    raw = request.headers.get(MOCK_SCENARIO_HEADER)
    if raw is None:
        return None
    name = raw.strip()
    return name or None


def _parse_headers(raw: Any) -> tuple[tuple[str, str], ...]:
    """Extract string->string header pairs, skipping anything malformed."""
    if not isinstance(raw, dict):
        return ()
    pairs: list[tuple[str, str]] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            continue
        if name.strip().lower() in _RESERVED_HEADERS:
            continue
        pairs.append((name.strip(), value))
    return tuple(pairs)


def _parse_response(raw: Any) -> ScenarioResponse | None:
    """Build one :class:`ScenarioResponse`; ``None`` when the entry is invalid."""
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        return None
    if not _MIN_STATUS <= status <= _MAX_STATUS:
        return None

    headers = _parse_headers(raw.get("headers"))
    has_body = "body" in raw

    media_type = raw.get("mediaType")
    if not isinstance(media_type, str) or not media_type.strip():
        media_type = next(
            (value for name, value in headers if name.lower() == "content-type"),
            "application/json",
        )

    return ScenarioResponse(
        status=status,
        headers=headers,
        body=raw.get("body"),
        has_body=has_body,
        media_type=media_type.strip(),
    )


def _parse_scenario(name: str, raw: Any) -> Scenario | None:
    """Build one :class:`Scenario`; ``None`` when the entry is unusable."""
    if not isinstance(raw, dict):
        return None
    description = raw.get("description")
    operations_raw = raw.get("operations")
    operations: dict[str, tuple[ScenarioResponse, ...]] = {}
    if isinstance(operations_raw, dict):
        for op_key_raw, override in operations_raw.items():
            op_key = normalize_operation_key(op_key_raw)
            if op_key is None or not isinstance(override, dict):
                continue
            responses_raw = override.get("responses")
            if not isinstance(responses_raw, list):
                continue
            responses = tuple(parsed for entry in responses_raw if (parsed := _parse_response(entry)) is not None)
            if responses:
                operations[op_key] = responses
    return Scenario(
        name=name,
        description=description if isinstance(description, str) else "",
        operations=operations,
        chaos=parse_chaos_block(raw.get("chaos")),
    )


def parse_scenarios(mock_settings: Any) -> dict[str, Scenario]:
    """Parse ``versions.mock_settings`` into scenario definitions by name.

    Accepts the raw JSONB value (dict, JSON text, or ``None``) and never
    raises: unusable scenarios / operations / responses are silently skipped.
    """
    settings: Any = mock_settings
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            return {}
    if not isinstance(settings, dict):
        return {}
    scenarios_raw = settings.get("scenarios")
    if not isinstance(scenarios_raw, dict):
        return {}

    scenarios: dict[str, Scenario] = {}
    for name, raw in scenarios_raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        scenario = _parse_scenario(name.strip(), raw)
        if scenario is not None:
            scenarios[scenario.name] = scenario
    return scenarios


async def _sequence_call_number(
    *,
    scenario: Scenario,
    operation_key: str,
    tenant: str,
    project: str,
    version: str,
    session_token: str | None,
    client_ip: str,
    store: SessionStore | None,
) -> int:
    """Allocate the 1-based call number for a sequence.

    The counter lives in the SIM-4.1 session store under the caller's
    ``X-Mock-Session`` token, so a new token (or session expiry) resets the
    sequence. Without a session header the counter falls back to a synthetic
    scenario + client IP session. When no store is available, or the store is
    at capacity, the sequence serves its first response.
    """
    if store is None:
        return 1
    token = session_token or f"{_IP_SESSION_PREFIX}:{scenario.name}:{client_ip}"
    key = SessionKey(tenant=tenant, project=project, version=version, session_token=token)
    collection_path = f"{_SEQUENCE_NAMESPACE}/{scenario.name}/{operation_key}"
    try:
        return await store.next_integer_id(key, collection_path)
    except SessionStoreError:
        return 1


def _build_response(canned: ScenarioResponse) -> Response:
    """Serialize one canned response into a FastAPI :class:`Response`."""
    media_type = canned.media_type
    response: Response
    if not canned.has_body:
        response = Response(status_code=canned.status)
    elif media_type.endswith("json") or media_type.endswith("+json"):
        response = JSONResponse(status_code=canned.status, content=canned.body, media_type=media_type)
    elif isinstance(canned.body, str):
        response = Response(content=canned.body, status_code=canned.status, media_type=media_type)
    elif canned.body is None:
        response = Response(status_code=canned.status, media_type=media_type)
    else:
        # Non-string body under a non-JSON media type: keep the declared media
        # type but serialize the JSON value as text.
        response = Response(
            content=json.dumps(canned.body),
            status_code=canned.status,
            media_type=media_type,
        )
    for name, value in canned.headers:
        response.headers[name] = value
    return response


async def serve_scenario_response(
    *,
    scenario: Scenario,
    responses: tuple[ScenarioResponse, ...],
    operation_key: str,
    tenant: str,
    project: str,
    version: str,
    session_token: str | None,
    client_ip: str,
    store: SessionStore | None,
) -> Response:
    """Return the canned response for one scenario-overridden operation.

    Single-response overrides always serve that response. Sequences advance
    per call (position from :func:`_sequence_call_number`) and stick on the
    last response once exhausted. The response echoes the scenario name in
    ``X-Mock-Scenario`` and, for sequences, the call number in
    ``X-Mock-Scenario-Call``.
    """
    call_number = 1
    if len(responses) > 1:
        call_number = await _sequence_call_number(
            scenario=scenario,
            operation_key=operation_key,
            tenant=tenant,
            project=project,
            version=version,
            session_token=session_token,
            client_ip=client_ip,
            store=store,
        )
    index = min(call_number - 1, len(responses) - 1)
    response = _build_response(responses[index])
    response.headers[MOCK_SCENARIO_HEADER] = scenario.name
    if len(responses) > 1:
        response.headers[SCENARIO_CALL_HEADER] = str(call_number)
    return response
