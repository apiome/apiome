"""The HAR reader behind ``apiome usage upload`` — RDG-1.4 (#5762).

``tests/fixtures/usage-har/petstore.har`` is the fixture corpus: a devtools-shaped archive with a
bearer token, a session cookie, an API key, query values, an email in a response body, a
base64-encoded body, an aborted request, a ``data:`` URL and a non-object entry. The events it
produces are pinned by apiome-rest's golden ``tests/golden/usage_har_upload/petstore.events.json``,
which ``apiome-rest/tests/test_usage_har_upload.py`` runs through the real ingest pipeline — so the
CLI and the server are proven to agree on one document.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from apiome_cli import usage_har
from apiome_cli.usage_har import (
    MAX_EVENTS_PER_BATCH,
    MAX_FIELD_POINTERS,
    MAX_SAMPLE_BYTES,
    HarObservation,
    HarParseError,
    batches,
    event_from_observation,
    field_pointers,
    iter_har_entries,
    observation_from_entry,
    read_har,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usage-har"
PETSTORE = FIXTURES / "petstore.har"
GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "apiome-rest"
    / "tests"
    / "golden"
    / "usage_har_upload"
    / "petstore.events.json"
)

#: Every credential and value in the fixture that must never reach an event.
SECRETS = (
    "abcDEF1234567890ghiJKL",
    "s3cr3tSessionValue42",
    "ak_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0",
    "c2VjcmV0",
    "alice@example.com",
    "Rex",
    "Spot",
)


def _events(
    path: Path = PETSTORE, **kwargs: Any
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    events, skipped = [], []
    for index, entry in read_har(path):
        observation = observation_from_entry(entry, index=index, label=path.name)
        if observation is None:
            skipped.append((index, "invalid-entry"))
            continue
        event, reason = event_from_observation(
            observation, environment="staging", **kwargs
        )
        if event is None:
            skipped.append((index, str(reason)))
        else:
            events.append(event)
    return events, skipped


def _stream(payload: Any) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


# --- streaming reader -------------------------------------------------------------------------


def test_the_fixture_corpus_matches_the_rest_golden() -> None:
    events, skipped = _events()
    assert events == json.loads(GOLDEN.read_text())
    assert skipped == [(5, "no-response"), (6, "unsupported-url"), (7, "invalid-entry")]


def test_reading_is_deterministic() -> None:
    first, _ = _events()
    second, _ = _events()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_tiny_chunks_read_the_same_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    whole = [entry for _, entry in read_har(PETSTORE)]
    monkeypatch.setattr(usage_har, "_READ_CHUNK", 7)
    assert [entry for _, entry in read_har(PETSTORE)] == whole


def test_a_multibyte_character_split_across_chunks_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_har, "_READ_CHUNK", 3)
    payload = {"log": {"entries": [{"note": "héllo — ✓ 🐕"}]}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert list(iter_har_entries(io.BytesIO(data))) == payload["log"]["entries"]


def test_keys_before_and_after_entries_are_skipped() -> None:
    payload = {
        "x": [1, {"y": 2}],
        "log": {"pages": [{"id": 1}], "entries": [{"a": 1}, {"b": 2}], "z": 1.5e3},
    }
    assert list(iter_har_entries(_stream(payload))) == [{"a": 1}, {"b": 2}]


def test_an_empty_entries_array_yields_nothing() -> None:
    assert list(iter_har_entries(_stream({"log": {"entries": []}}))) == []


@pytest.mark.parametrize(
    "name, message",
    [("truncated.har", "truncated"), ("not-a-har.har", "no 'log' object")],
)
def test_broken_fixtures_are_parse_errors(name: str, message: str) -> None:
    with pytest.raises(HarParseError, match=message):
        list(read_har(FIXTURES / name))


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"", "not a HAR file"),
        (b"[1, 2]", "not a HAR file"),
        (b'{"log": []}', "'log' is not an object"),
        (b'{"log": {"version": "1.2"}}', "no 'entries' array"),
        (b'{"log": {"entries": [{}]}} trailing', "content after"),
        (b'{"log": {"entries": [{} {}]}}', "expected ','"),
        (b'{"log": {"entries": [{}]}', "truncated"),
        (b'{"log": {"entries": ["\xff"]}}', "UTF-8"),
    ],
)
def test_malformed_archives_are_parse_errors(raw: bytes, message: str) -> None:
    with pytest.raises(HarParseError, match=message):
        list(iter_har_entries(io.BytesIO(raw)))


def test_a_byte_order_mark_is_accepted() -> None:
    data = "﻿".encode() + json.dumps({"log": {"entries": [{"a": 1}]}}).encode()
    assert list(iter_har_entries(io.BytesIO(data))) == [{"a": 1}]


# --- entries and events -----------------------------------------------------------------------


def test_an_entry_reads_into_the_http_observation_shape() -> None:
    _, entry = next(iter(read_har(PETSTORE)))
    observation = observation_from_entry(entry, index=0, label="petstore.har")
    assert isinstance(observation, HarObservation)
    assert (
        observation.method,
        observation.response_status,
        observation.source_location,
    ) == ("GET", 200, "entry 0")
    assert ("limit", "10") in observation.query
    assert observation.url.startswith("https://api.example.com/v1/pets")


def test_no_credential_query_value_or_body_value_reaches_an_event() -> None:
    events, _ = _events()
    serialized = json.dumps(events)
    for secret in SECRETS:
        assert secret not in serialized
    for event in events:
        assert not {"headers", "body", "sample", "query"} & set(event)


def test_query_names_are_kept_and_values_dropped() -> None:
    events, _ = _events()
    assert events[0]["path"] == "/v1/pets?limit=&cursor="


def test_auth_present_says_whether_a_credential_header_was_there() -> None:
    events, _ = _events()
    assert [e["auth_present"] for e in events] == [
        "true",
        "true",
        "true",
        "false",
        "false",
    ]


def test_a_base64_body_is_decoded_for_its_fields() -> None:
    events, _ = _events()
    assert events[1]["fields"]["response"] == ["/id", "/name", "/owner", "/owner/email"]


def test_timestamps_are_utc_and_latency_is_rounded() -> None:
    events, _ = _events()
    assert events[1]["observed_at"] == "2026-10-18T10:00:01.250000Z"
    assert events[0]["latency_ms"] == 43


def _observation(**overrides: Any) -> HarObservation:
    from datetime import datetime, timezone

    values: dict[str, Any] = {
        "method": "GET",
        "url": "https://api.example.com/v1/pets",
        "response_status": 200,
        "started_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
        "time_ms": 1.0,
    }
    values.update(overrides)
    return HarObservation(**values)


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"response_status": None}, "no-response"),
        ({"response_status": 0}, "no-response"),
        ({"method": "G E T"}, "invalid-entry"),
        ({"started_at": None}, "invalid-entry"),
        ({"url": "ws://api.example.com/socket"}, "unsupported-url"),
        ({"url": "https://api.example.com:99999/x"}, "unsupported-url"),
        ({"url": "https://api.example.com/" + "a" * 2100}, "unsupported-url"),
    ],
)
def test_entries_without_a_usable_call_are_skipped_with_a_reason(
    overrides: dict[str, Any], reason: str
) -> None:
    assert event_from_observation(_observation(**overrides), environment="prod") == (
        None,
        reason,
    )


def test_an_ipv6_host_is_bracketed_and_a_negative_time_is_zero() -> None:
    event, _ = event_from_observation(
        _observation(url="http://[::1]:8080/v1/pets", time_ms=-1), environment="prod"
    )
    assert event["host"] == "[::1]:8080" and event["latency_ms"] == 0


def test_a_long_user_agent_is_capped_before_it_is_sent() -> None:
    event, _ = event_from_observation(
        _observation(headers=(("User-Agent", "x" * 5000),)), environment="prod"
    )
    assert len(event["user_agent"]) == 1024


# --- field pointers ---------------------------------------------------------------------------


def test_field_pointers_escape_names_and_fold_array_items() -> None:
    body = json.dumps({"a/b": 1, "c~d": {"e": [{"f": 1}, {"g": [1, 2]}]}})
    assert field_pointers(body) == [
        "/a~1b",
        "/c~0d",
        "/c~0d/e",
        "/c~0d/e/0/f",
        "/c~0d/e/0/g",
    ]


def test_field_pointers_skip_names_the_contract_cannot_hold() -> None:
    assert field_pointers(json.dumps({"has space": 1, "ok": 2})) == ["/ok"]


def test_field_pointers_ignore_non_json_and_scalars() -> None:
    assert field_pointers("not json") == []
    assert field_pointers("42") == []
    assert field_pointers(None) == []


def test_field_pointers_are_capped() -> None:
    body = json.dumps({f"k{i:04d}": i for i in range(MAX_FIELD_POINTERS + 50)})
    pointers = field_pointers(body)
    assert len(pointers) == MAX_FIELD_POINTERS and pointers == sorted(pointers)


# --- samples ----------------------------------------------------------------------------------


def test_a_sample_is_attached_only_when_asked() -> None:
    events, _ = _events(sample_bodies=True)
    sample = events[2]["sample"]
    assert sample["request"]["body"] == {"name": "Spot", "tag": "cat"}
    assert sample["request"]["mediaType"] == "application/json"
    plain, _ = _events()
    assert all("sample" not in e for e in plain)


def test_a_sample_over_16_kib_is_not_attached() -> None:
    big = json.dumps({"blob": "x" * MAX_SAMPLE_BYTES})
    event, _ = event_from_observation(
        _observation(response_body=big), environment="prod", sample_bodies=True
    )
    assert "sample" not in event and event["fields"]["response"] == ["/blob"]


# --- batching ---------------------------------------------------------------------------------


def test_batches_hold_at_most_5000_events() -> None:
    event = {"method": "GET", "path": "/v1/pets", "status": 200}
    sizes = [
        len(b) for b in batches(event for _ in range(2 * MAX_EVENTS_PER_BATCH + 1))
    ]
    assert sizes == [MAX_EVENTS_PER_BATCH, MAX_EVENTS_PER_BATCH, 1]


def test_batches_close_before_the_byte_limit() -> None:
    event = {"path": "/" + "a" * 900}
    grouped = list(batches((dict(event) for _ in range(10)), max_bytes=4000))
    assert [len(b) for b in grouped] == [4, 4, 2]
    for batch in grouped:
        assert len(json.dumps({"events": batch})) <= 4000


def test_an_oversized_sample_is_stripped_rather_than_the_event_dropped() -> None:
    event = {"path": "/v1/pets", "sample": {"request": {"body": "x" * 5000}}}
    (batch,) = list(batches([event], max_bytes=1000))
    assert batch == [{"path": "/v1/pets"}]


def test_no_batch_is_yielded_for_no_events() -> None:
    assert list(batches([])) == []
