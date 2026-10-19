"""The usage event contract, ``apiome.usage.event/v1`` — RDG-1.1 (#5759).

Every usage source (the OTLP receiver, a HAR upload, a gateway access log, the mock and agent
runtimes, the SDK beacon) turns what it saw into these events, and the RDG-1.2 ingest pipeline turns
the events into the counters of the usage index (migration V290). This module is the contract only:
pure models and helpers, no I/O.

An event describes **one call** with exactly the facts the index keeps, so nothing the index must
never store can reach it:

* the method, the path (already templated when the source knows the route, raw otherwise — the
  ingest pipeline templates and scrubs raw paths), the status, the latency, the byte sizes, the
  scheme and the host;
* ``auth_present`` — whether the call carried a credential header, never its value
  (tri-state ``true | false | unknown``);
* ``version_hint`` — whether the call carried a version marker and where (a path segment, a header
  name or a user-agent marker), never the header's value;
* the scrubbed user agent (at most 256 characters);
* ``consumer_hint`` — a kind and an HMAC the edge computed (RDG-1.8 binds it to a consumer), never
  the raw value;
* the correlation fields Apiome-controlled sources set (``spec_revision_id``, ``agent_key_id``, read
  by ATQ-4);
* ``fields`` — the JSON Pointers present in the request or response body, computed at the edge from
  a body the edge then discards.

There is no field for a header value, a body, a query string or a client address, and unknown keys
are refused, so a source cannot smuggle one in. :meth:`UsageEvent.to_json` writes the canonical
form (sorted keys, no whitespace, UTC timestamps), so ``to_json(from_json(to_json(e)))`` is
byte-identical — batch digests and goldens depend on it.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional, Tuple
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

__all__ = [
    "CONSUMER_HINT_KINDS",
    "DEFAULT_ENVIRONMENT",
    "ENVIRONMENT_PATTERN",
    "LATENCY_BOUNDS_MS",
    "MAX_FIELD_POINTERS",
    "MAX_USER_AGENT_LENGTH",
    "MOCK_ENVIRONMENT",
    "SOURCE_KINDS",
    "USAGE_EVENT_SCHEMA",
    "ConsumerHint",
    "EventFields",
    "UsageEvent",
    "VersionHint",
    "latency_bucket",
]

#: The contract's name and version, written into every event as ``schema``.
USAGE_EVENT_SCHEMA = "apiome.usage.event/v1"

#: Source kinds ``usage_source.kind`` accepts (V290).
SOURCE_KINDS: Tuple[str, ...] = ("otlp", "har", "access_log", "mock", "agent", "sdk_beacon")

#: The environment a source reports to unless it names another.
DEFAULT_ENVIRONMENT = "prod"

#: The environment reserved for the mock runtime's own source (RDG-1.6).
MOCK_ENVIRONMENT = "mock"

#: An environment name: lower-case, starts with a letter, at most 32 characters (the V290 CHECK).
ENVIRONMENT_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"

#: Upper bounds (ms) of the latency histogram — equal to V290's ``usage_latency_bounds()``.
LATENCY_BOUNDS_MS: Tuple[int, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)

#: The longest user agent an event may carry.
MAX_USER_AGENT_LENGTH = 256

#: The most field pointers an event may carry per direction.
MAX_FIELD_POINTERS = 512

#: Consumer-hint kinds — the binding kinds of RDG-1.8.
CONSUMER_HINT_KINDS: Tuple[str, ...] = ("header", "api_key", "jwt_claim", "user_agent")

TriState = Literal["true", "false", "unknown"]

_METHOD = re.compile(r"^[A-Z]{1,16}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?$|^\[[0-9A-Fa-f:.]{2,45}\](:[0-9]{1,5})?$")
_POINTER = re.compile(r"^(/([^~\s]|~[01])*)+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_PATH_LENGTH = 2048
_MAX_POINTER_LENGTH = 512


def latency_bucket(latency_ms: int) -> int:
    """The histogram bucket a latency falls in.

    Args:
        latency_ms: A non-negative latency in milliseconds.

    Returns:
        The index into ``latency_buckets``: ``i`` when ``latency_ms <= LATENCY_BOUNDS_MS[i]`` (and
        above the previous bound), ``len(LATENCY_BOUNDS_MS)`` for anything slower than the largest
        bound.

    Raises:
        ValueError: When ``latency_ms`` is negative.
    """
    if latency_ms < 0:
        raise ValueError("latency_ms must not be negative")
    return bisect_left(LATENCY_BOUNDS_MS, latency_ms)


def _tri_state(value: Any) -> Any:
    """Accept a JSON boolean for a tri-state and write it as the canonical string."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return value


class _Strict(BaseModel):
    """Shared configuration: unknown keys are refused and parsed events are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ConsumerHint(_Strict):
    """Who made the call, as an HMAC the edge computed (RDG-1.8 binds it to a consumer).

    Attributes:
        kind: What was hashed: a header value, an API key, a JWT claim or the user agent.
        hmac: Lower-case hex HMAC-SHA256 of the value under the tenant's key. The raw value never
            leaves the edge.
    """

    kind: Literal["header", "api_key", "jwt_claim", "user_agent"]
    hmac: str = Field(pattern=r"^[0-9a-f]{64}$")


class VersionHint(_Strict):
    """Whether the call named an API version, and where.

    Attributes:
        present: ``true`` when a version marker was seen, ``false`` when the source could tell
            there was none, ``unknown`` when it could not tell.
        via: Where the marker was (``path_segment``, ``header`` — the header's name, never its value
            — or ``user_agent``). Only set when ``present`` is ``true``.
    """

    present: TriState = "unknown"
    via: Optional[Literal["path_segment", "header", "user_agent"]] = None

    @field_validator("present", mode="before")
    @classmethod
    def _present(cls, value: Any) -> Any:
        return _tri_state(value)

    @model_validator(mode="after")
    def _via_needs_present(self) -> "VersionHint":
        if self.via is not None and self.present != "true":
            raise ValueError("version_hint.via is only allowed when present is true")
        return self


class EventFields(_Strict):
    """The fields present in the call's bodies, as JSON Pointers (names only, never values).

    Attributes:
        request: Pointers present in the request, sorted and without duplicates.
        response: Pointers present in the response, sorted and without duplicates.
    """

    request: List[str] = Field(default_factory=list, max_length=MAX_FIELD_POINTERS)
    response: List[str] = Field(default_factory=list, max_length=MAX_FIELD_POINTERS)

    @field_validator("request", "response")
    @classmethod
    def _pointers(cls, value: List[str]) -> List[str]:
        for pointer in value:
            if len(pointer) > _MAX_POINTER_LENGTH or not _POINTER.match(pointer):
                raise ValueError(f"not a JSON Pointer of at most {_MAX_POINTER_LENGTH} characters: {pointer!r}")
        return sorted(set(value))


class UsageEvent(_Strict):
    """One observed call — ``apiome.usage.event/v1``.

    Attributes:
        schema_id: Always :data:`USAGE_EVENT_SCHEMA` (serialized as ``schema``).
        observed_at: When the call happened; must carry a time zone, stored as UTC.
        source_id: The ``usage_source`` that observed it.
        environment: The environment it happened in (``prod``, ``staging``, ``mock``, ...).
        method: The HTTP method, upper-case.
        path: The path, without query or fragment — templated (``/pets/{petId}``) when the source
            knows the route, raw (``/pets/42``) otherwise.
        status: The response status code.
        latency_ms: How long the call took, in milliseconds.
        request_bytes: The request body size, when known.
        response_bytes: The response body size, when known.
        scheme: ``http`` or ``https``, when known.
        host: The server host (and port) the call was addressed to, when known. Never the client's
            address.
        auth_present: Whether a credential header was present (never its value).
        version_hint: Whether a version marker was present, and where.
        user_agent: The scrubbed user agent, at most 256 characters.
        consumer_hint: The consumer, as a kind and an HMAC.
        spec_revision_id: The revision that served the call (set by Apiome-controlled sources).
        agent_key_id: The agent key that made the call (set by the agent runtime).
        fields: The JSON Pointers present in the request and response bodies.
    """

    schema_id: Literal["apiome.usage.event/v1"] = Field(USAGE_EVENT_SCHEMA, alias="schema")
    observed_at: datetime
    source_id: UUID
    environment: str = Field(pattern=ENVIRONMENT_PATTERN)
    method: str
    path: str = Field(min_length=1, max_length=_MAX_PATH_LENGTH)
    status: int = Field(ge=100, le=599)
    latency_ms: int = Field(ge=0)
    request_bytes: Optional[int] = Field(default=None, ge=0)
    response_bytes: Optional[int] = Field(default=None, ge=0)
    scheme: Optional[Literal["http", "https"]] = None
    host: Optional[str] = None
    auth_present: TriState = "unknown"
    version_hint: VersionHint = Field(default_factory=VersionHint)
    user_agent: Optional[str] = Field(default=None, max_length=MAX_USER_AGENT_LENGTH)
    consumer_hint: Optional[ConsumerHint] = None
    spec_revision_id: Optional[UUID] = None
    agent_key_id: Optional[UUID] = None
    fields: Optional[EventFields] = None

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must carry a time zone")
        return value.astimezone(timezone.utc)

    @field_validator("method", mode="before")
    @classmethod
    def _method(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.upper()
            if not _METHOD.match(value):
                raise ValueError("method must be 1-16 letters")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("path must start with '/'")
        if "?" in value or "#" in value:
            raise ValueError("path must not carry a query or fragment (query values never reach an event)")
        if _CONTROL.search(value) or any(ch.isspace() for ch in value):
            raise ValueError("path must not contain whitespace or control characters")
        return value

    @field_validator("scheme", mode="before")
    @classmethod
    def _scheme(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value

    @field_validator("host")
    @classmethod
    def _host(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _HOST.match(value):
            raise ValueError("host must be a host name or bracketed address, with an optional port")
        return value.lower() if value is not None else None

    @field_validator("auth_present", mode="before")
    @classmethod
    def _auth_present(cls, value: Any) -> Any:
        return _tri_state(value)

    @field_validator("user_agent")
    @classmethod
    def _user_agent(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and _CONTROL.search(value):
            raise ValueError("user_agent must not contain control characters")
        return value

    @field_serializer("observed_at")
    def _write_observed_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def to_dict(self) -> dict:
        """The event as JSON-ready data, without the optional fields that are unset.

        Returns:
            A dict whose keys are the wire names (``schema``, ``observed_at``, ...).
        """
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def to_json(self) -> str:
        """The event's canonical JSON: sorted keys, no whitespace, UTF-8 text, UTC microseconds.

        Returns:
            A string that :meth:`from_json` reads back into an equal event whose ``to_json`` is
            byte-identical.
        """
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "UsageEvent":
        """Parse an event from JSON.

        Args:
            text: One JSON object.

        Returns:
            The validated event.

        Raises:
            pydantic.ValidationError: When a key is unknown, a value is out of range or the schema
                id is not ``apiome.usage.event/v1``.
        """
        return cls.model_validate_json(text)
