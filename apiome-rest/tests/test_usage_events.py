"""The usage event contract ``apiome.usage.event/v1`` — RDG-1.1 (#5759).

Pure tests (no database): the canonical JSON round-trips byte-for-byte, unknown keys are refused at
every level, and no field exists that could carry a header value, a body, a query value or a client
address.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from app.usage_events import (
    CONSUMER_HINT_KINDS,
    LATENCY_BOUNDS_MS,
    MAX_FIELD_POINTERS,
    SOURCE_KINDS,
    USAGE_EVENT_SCHEMA,
    EventFields,
    UsageEvent,
    VersionHint,
    latency_bucket,
)

SOURCE = "6f1c6a8e-2a39-4a8c-9d77-1d2c5e1b9f00"
HMAC = "ab" * 32


def _event(**overrides: Any) -> Dict[str, Any]:
    """A minimal valid event as wire data, with ``overrides`` applied."""
    data: Dict[str, Any] = {
        "observed_at": "2026-10-18T12:00:00Z",
        "source_id": SOURCE,
        "environment": "prod",
        "method": "GET",
        "path": "/pets/{petId}",
        "status": 200,
        "latency_ms": 12,
    }
    data.update(overrides)
    return data


def _full() -> Dict[str, Any]:
    """An event with every optional field set."""
    return _event(
        request_bytes=0,
        response_bytes=512,
        scheme="https",
        host="api.example.com:8443",
        auth_present="true",
        version_hint={"present": "true", "via": "path_segment"},
        user_agent="billing-service/2.1 (+https://example.com)",
        consumer_hint={"kind": "api_key", "hmac": HMAC},
        spec_revision_id="0d0b8a51-55cf-4cf4-a70f-28e2f4e1f2a1",
        agent_key_id="9a1f0c0e-1b5e-4d0f-9b0e-6a3c2d1e0f00",
        fields={"request": ["/query/limit"], "response": ["/name", "/id"]},
    )


# ---------------------------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [_event(), _full()], ids=["minimal", "full"])
def test_round_trip_is_byte_deterministic(data: Dict[str, Any]) -> None:
    first = UsageEvent.model_validate(data).to_json()
    second = UsageEvent.from_json(first).to_json()
    assert first == second
    assert UsageEvent.from_json(first) == UsageEvent.model_validate(data)


def test_canonical_json_is_sorted_compact_and_names_the_schema() -> None:
    text = UsageEvent.model_validate(_full()).to_json()
    parsed = json.loads(text)
    assert list(parsed) == sorted(parsed)
    assert " " not in text.replace("billing-service/2.1 (+https://example.com)", "")
    assert parsed["schema"] == USAGE_EVENT_SCHEMA == "apiome.usage.event/v1"


def test_key_order_and_equivalent_spellings_give_the_same_bytes() -> None:
    a = UsageEvent.model_validate(_event(method="get", auth_present=True, observed_at="2026-10-18T14:00:00+02:00"))
    shuffled = dict(reversed(list(_event(auth_present="true").items())))
    b = UsageEvent.model_validate(shuffled)
    assert a.to_json() == b.to_json()


def test_unset_optionals_are_left_out_and_defaults_are_written() -> None:
    parsed = json.loads(UsageEvent.model_validate(_event()).to_json())
    assert "user_agent" not in parsed and "consumer_hint" not in parsed and "fields" not in parsed
    assert parsed["auth_present"] == "unknown"
    assert parsed["version_hint"] == {"present": "unknown"}


def test_observed_at_is_written_as_utc_microseconds() -> None:
    event = UsageEvent.model_validate(_event(observed_at="2026-10-18T14:00:00.5+02:00"))
    assert event.observed_at == datetime(2026, 10, 18, 12, 0, 0, 500000, tzinfo=timezone.utc)
    assert json.loads(event.to_json())["observed_at"] == "2026-10-18T12:00:00.500000Z"


def test_observed_at_without_a_time_zone_is_refused() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        UsageEvent.model_validate(_event(observed_at="2026-10-18T12:00:00"))


def test_events_are_immutable() -> None:
    event = UsageEvent.model_validate(_event())
    with pytest.raises(ValidationError):
        event.status = 500  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------
# Unknown keys and the privacy invariant
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["headers", "authorization", "body", "request_body", "query", "client_ip", "remote_addr", "cookie"],
)
def test_unknown_top_level_keys_are_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UsageEvent.model_validate(_event(**{key: "x"}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"consumer_hint": {"kind": "header", "hmac": HMAC, "value": "secret"}},
        {"version_hint": {"present": "true", "via": "header", "header_value": "v2"}},
        {"fields": {"request": [], "response": [], "values": {"/id": 1}}},
    ],
    ids=["consumer_hint", "version_hint", "fields"],
)
def test_unknown_nested_keys_are_refused(overrides: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UsageEvent.model_validate(_event(**overrides))


def test_the_contract_has_exactly_the_documented_fields() -> None:
    """A new field must be reviewed against the privacy model, so the list is pinned."""
    wire = {field.alias or name for name, field in UsageEvent.model_fields.items()}
    assert wire == {
        "schema",
        "observed_at",
        "source_id",
        "environment",
        "method",
        "path",
        "status",
        "latency_ms",
        "request_bytes",
        "response_bytes",
        "scheme",
        "host",
        "auth_present",
        "version_hint",
        "user_agent",
        "consumer_hint",
        "spec_revision_id",
        "agent_key_id",
        "fields",
    }


def test_a_different_schema_version_is_refused() -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(schema="apiome.usage.event/v2"))


@pytest.mark.parametrize("path", ["/pets?token=abc", "/pets#frag", "pets", "/pets/a b", "/pets/\x00", ""])
def test_paths_with_a_query_fragment_or_whitespace_are_refused(path: str) -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(path=path))


def test_raw_paths_are_accepted_for_the_pipeline_to_template() -> None:
    assert UsageEvent.model_validate(_event(path="/pets/42")).path == "/pets/42"


def test_user_agent_is_capped_at_256_characters() -> None:
    assert UsageEvent.model_validate(_event(user_agent="a" * 256)).user_agent == "a" * 256
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(user_agent="a" * 257))
    with pytest.raises(ValidationError, match="control"):
        UsageEvent.model_validate(_event(user_agent="ua\r\nX-Injected: 1"))


# ---------------------------------------------------------------------------------------------
# Field rules
# ---------------------------------------------------------------------------------------------


def test_method_is_upper_cased_and_must_be_letters() -> None:
    assert UsageEvent.model_validate(_event(method="patch")).method == "PATCH"
    for bad in ("", "GET /x", "G3T", "A" * 17):
        with pytest.raises(ValidationError):
            UsageEvent.model_validate(_event(method=bad))


@pytest.mark.parametrize("status", [99, 600, "ok"])
def test_status_must_be_an_http_status(status: Any) -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(status=status))


@pytest.mark.parametrize("field", ["latency_ms", "request_bytes", "response_bytes"])
def test_sizes_and_latency_must_not_be_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(**{field: -1}))


@pytest.mark.parametrize("environment", ["prod", "staging", "eu-west_1", "mock"])
def test_environment_names(environment: str) -> None:
    assert UsageEvent.model_validate(_event(environment=environment)).environment == environment


@pytest.mark.parametrize("environment", ["Prod", "1prod", "", "a" * 33, "prod env"])
def test_bad_environment_names_are_refused(environment: str) -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(environment=environment))


def test_scheme_and_host() -> None:
    event = UsageEvent.model_validate(_event(scheme="HTTPS", host="API.example.com"))
    assert (event.scheme, event.host) == ("https", "api.example.com")
    assert UsageEvent.model_validate(_event(host="[::1]:8080")).host == "[::1]:8080"
    for bad in ({"scheme": "ftp"}, {"host": "evil.com/path"}, {"host": "a b"}):
        with pytest.raises(ValidationError):
            UsageEvent.model_validate(_event(**bad))


@pytest.mark.parametrize("value, expected", [(True, "true"), (False, "false"), ("unknown", "unknown")])
def test_auth_present_is_tri_state(value: Any, expected: str) -> None:
    assert UsageEvent.model_validate(_event(auth_present=value)).auth_present == expected


def test_auth_present_refuses_anything_else() -> None:
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(auth_present="Bearer abc"))


def test_version_hint_via_requires_present_true() -> None:
    assert VersionHint(present=True, via="header").present == "true"
    assert VersionHint(present=False).via is None
    with pytest.raises(ValidationError, match="only allowed when present is true"):
        VersionHint(present="unknown", via="user_agent")
    with pytest.raises(ValidationError):
        VersionHint(present="true", via="query")


@pytest.mark.parametrize("kind", CONSUMER_HINT_KINDS)
def test_consumer_hint_kinds(kind: str) -> None:
    event = UsageEvent.model_validate(_event(consumer_hint={"kind": kind, "hmac": HMAC}))
    assert event.consumer_hint is not None and event.consumer_hint.kind == kind


@pytest.mark.parametrize("hmac", ["AB" * 32, "ab" * 31, "secret-api-key", "zz" * 32])
def test_consumer_hint_must_be_a_lowercase_sha256_hmac(hmac: str) -> None:
    """A raw credential can never pass for an HMAC."""
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(_event(consumer_hint={"kind": "header", "hmac": hmac}))


def test_fields_are_sorted_and_deduplicated() -> None:
    fields = EventFields(request=["/b", "/a", "/b"], response=["/items/0/id"])
    assert fields.request == ["/a", "/b"]
    assert fields.response == ["/items/0/id"]


@pytest.mark.parametrize("pointer", ["name", "/a b", "/bad~2escape", "", "/" + "x" * 512])
def test_fields_must_be_json_pointers(pointer: str) -> None:
    with pytest.raises(ValidationError):
        EventFields(request=[pointer])


def test_fields_are_capped_per_direction() -> None:
    EventFields(response=[f"/f{i}" for i in range(MAX_FIELD_POINTERS)])
    with pytest.raises(ValidationError):
        EventFields(response=[f"/f{i}" for i in range(MAX_FIELD_POINTERS + 1)])


def test_ids_must_be_uuids() -> None:
    for field in ("source_id", "spec_revision_id", "agent_key_id"):
        with pytest.raises(ValidationError):
            UsageEvent.model_validate(_event(**{field: "not-a-uuid"}))


# ---------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------


def test_source_kinds_match_the_migration() -> None:
    assert SOURCE_KINDS == ("otlp", "har", "access_log", "mock", "agent", "sdk_beacon")


def test_latency_bounds_are_strictly_increasing() -> None:
    assert list(LATENCY_BOUNDS_MS) == sorted(set(LATENCY_BOUNDS_MS))


@pytest.mark.parametrize(
    "latency, bucket",
    [(0, 0), (5, 0), (6, 1), (10, 1), (11, 2), (999, 7), (1000, 7), (10000, 10), (10001, 11), (10**9, 11)],
)
def test_latency_bucket(latency: int, bucket: int) -> None:
    assert latency_bucket(latency) == bucket


def test_latency_bucket_refuses_negative_latency() -> None:
    with pytest.raises(ValueError):
        latency_bucket(-1)


def test_every_bucket_index_is_reachable() -> None:
    reached = {latency_bucket(b) for b in LATENCY_BOUNDS_MS} | {latency_bucket(LATENCY_BOUNDS_MS[-1] + 1)}
    assert reached == set(range(len(LATENCY_BOUNDS_MS) + 1))


def test_observed_at_accepts_a_datetime() -> None:
    moment = datetime(2026, 10, 18, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
    event = UsageEvent.model_validate(_event(observed_at=moment))
    assert event.observed_at.tzinfo == timezone.utc and event.observed_at.hour == 12
