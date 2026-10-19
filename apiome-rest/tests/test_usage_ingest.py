"""The usage ingest pipeline as pure functions — RDG-1.2 (#5760).

Everything here runs without a database: parsing and size limits, head sampling (deterministic,
and scaled counts from a 10% sample within 1% of an unsampled run over the fixture corpus), the
edge scrub (a bearer token in a path, a session cookie in a user agent and an email in a query value
never survive it), template matching through ``SpecIndex`` (published revisions only), the ledger's
arithmetic and the opt-in sample reducer. The database half is ``test_usage_ingest_db.py``.
"""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from app.consumer_surface import SpecIndex
from app.inferred_spec import template_path
from app.usage_events import LATENCY_BOUNDS_MS, UsageEvent
from app.usage_ingest import (
    BASIS_COMPLETE,
    BASIS_SAMPLED,
    CODE_BATCH_INVALID,
    CODE_BATCH_TOO_LARGE,
    CODE_BODY_NOT_ACCEPTED,
    MAX_BATCH_BYTES,
    MAX_EVENTS_PER_BATCH,
    MAX_SAMPLE_BYTES,
    QUERY_POINTER_PREFIX,
    HourlyCounter,
    RevisionMatcher,
    SourceConfig,
    UsageIngestError,
    batch_digest,
    decode_body,
    head_sample_keep,
    next_utc_midnight,
    parse_batch,
    plan_batch,
    reduce_sample,
    refuse_closed_body_window,
    rejected_plan,
    scale,
    scrub_event,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = "6f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"

#: A bearer token, a session cookie and an email — none may survive the edge.
BEARER = "Bearer abcDEF1234567890ghiJKL"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
COOKIE_UA = "curl/8.1 session=s3cr3tSessionValue42"
EMAIL = "alice@example.com"

#: The published revision the fixtures match against.
PUBLISHED = {
    "openapi": "3.1.0",
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/pets": {"get": {}, "post": {}},
        "/pets/{petId}": {"get": {}, "delete": {}},
        "/pets/mine": {"get": {}},
        "/users/{userId}/orders": {"get": {}},
    },
}


def _source(**overrides: Any) -> SourceConfig:
    """An OTLP source with ``overrides``."""
    values: Dict[str, Any] = {"id": SOURCE_ID, "tenant_id": "t", "project_id": "p", "kind": "otlp"}
    values.update(overrides)
    return SourceConfig(**values)


def _matcher(*documents: Dict[str, Any]) -> RevisionMatcher:
    """A matcher over ``documents`` (default: the published fixture), newest first."""
    docs = documents or (PUBLISHED,)
    return RevisionMatcher([(f"v{index}", SpecIndex(doc)) for index, doc in enumerate(docs)])


def _event(path: str = "/pets/42", **overrides: Any) -> Dict[str, Any]:
    """One raw event as a source sends it (no schema, source_id or environment)."""
    event: Dict[str, Any] = {
        "observed_at": NOW.isoformat(),
        "method": "GET",
        "path": path,
        "status": 200,
        "latency_ms": 12,
    }
    event.update(overrides)
    return event


# ---------------------------------------------------------------------------------------------
# Parsing and limits
# ---------------------------------------------------------------------------------------------


def test_decode_body_accepts_plain_and_gzip() -> None:
    raw = json.dumps({"events": []}).encode()
    assert decode_body(raw, None) == raw
    assert decode_body(raw, "identity") == raw
    assert decode_body(gzip.compress(raw), "gzip") == raw


def test_decode_body_refuses_oversize_before_and_after_decompression() -> None:
    with pytest.raises(UsageIngestError) as raw_too_big:
        decode_body(b"x" * (MAX_BATCH_BYTES + 1), None)
    assert (raw_too_big.value.status, raw_too_big.value.code) == (413, CODE_BATCH_TOO_LARGE)

    bomb = gzip.compress(b" " * (MAX_BATCH_BYTES + 10))
    assert len(bomb) < MAX_BATCH_BYTES
    with pytest.raises(UsageIngestError) as inflated:
        decode_body(bomb, "gzip")
    assert inflated.value.status == 413


def test_decode_body_refuses_unknown_encoding_and_broken_gzip() -> None:
    for encoding, body in (("br", b"{}"), ("gzip", b"not gzip")):
        with pytest.raises(UsageIngestError) as caught:
            decode_body(body, encoding)
        assert (caught.value.status, caught.value.code) == (400, CODE_BATCH_INVALID)


def test_parse_batch_reads_the_envelope() -> None:
    source, events = parse_batch(json.dumps({"source_id": SOURCE_ID, "events": [_event()]}).encode())
    assert source == SOURCE_ID and len(events) == 1
    assert parse_batch(b'{"events": []}') == (None, [])


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"events": {}}', b'{"events": [], "extra": 1}', b'{"events": [], "source_id": 7}'],
)
def test_parse_batch_refuses_a_malformed_envelope(body: bytes) -> None:
    with pytest.raises(UsageIngestError) as caught:
        parse_batch(body)
    assert caught.value.code == CODE_BATCH_INVALID


def test_parse_batch_caps_the_event_count() -> None:
    body = json.dumps({"events": [{}] * (MAX_EVENTS_PER_BATCH + 1)}).encode()
    with pytest.raises(UsageIngestError) as caught:
        parse_batch(body)
    assert caught.value.status == 413


def test_batch_digest_is_sha256_hex() -> None:
    digest = batch_digest(b"{}")
    assert len(digest) == 64 and digest == batch_digest(b"{}") != batch_digest(b"{ }")


def test_next_utc_midnight() -> None:
    assert next_utc_midnight(NOW) == datetime(2026, 10, 19, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------
# Step 2 — head sampling
# ---------------------------------------------------------------------------------------------


def test_head_sampling_is_deterministic_and_complete_at_rate_one() -> None:
    first = [head_sample_keep(SOURCE_ID, NOW + timedelta(seconds=i), "/pets/1", 200, 0.25) for i in range(500)]
    again = [head_sample_keep(SOURCE_ID, NOW + timedelta(seconds=i), "/pets/1", 200, 0.25) for i in range(500)]
    assert first == again
    assert 75 < sum(first) < 175
    assert all(head_sample_keep(SOURCE_ID, NOW, "/x", 200, 1.0) for _ in range(10))


def test_scale_rounds_half_to_even() -> None:
    assert scale(7, 1.0) == 7
    assert scale(3, 0.1) == 30
    assert scale(1, 0.4) == 2  # 2.5 → 2
    assert scale(0, 0.3) == 0


def _corpus(count: int) -> List[Dict[str, Any]]:
    """The fixture corpus: ``count`` calls over four operations, statuses and latencies."""
    paths = ["/pets", "/pets/{n}", "/pets/mine", "/users/{n}/orders"]
    statuses = [200, 200, 200, 404, 500]
    events = []
    for i in range(count):
        events.append(
            {
                "observed_at": (NOW + timedelta(microseconds=i * 1013)).isoformat(),
                "method": "GET",
                "path": paths[i % 4].replace("{n}", str(i % 997)),
                "status": statuses[i % 5],
                "latency_ms": (i * 7) % 900,
                "request_bytes": i % 50,
                "response_bytes": (i * 3) % 400,
                "scheme": "https",
            }
        )
    return events


def _totals(rate: float, events: List[Dict[str, Any]]) -> Dict[str, int]:
    """Scaled totals over the corpus, batched as a source would send it."""
    source = _source(sampling_rate=rate)
    matcher = _matcher()
    totals = {"calls": 0, "latency_sum_ms": 0, "request_bytes": 0, "response_bytes": 0, "https_calls": 0}
    for start in range(0, len(events), MAX_EVENTS_PER_BATCH):
        plan = plan_batch(events[start : start + MAX_EVENTS_PER_BATCH], source, matcher, now=NOW)
        assert plan.basis == (BASIS_SAMPLED if rate < 1 else BASIS_COMPLETE)
        for counter in plan.hourly.values():
            row = counter.scaled(rate)
            for key in totals:
                totals[key] += row[key]
    return totals


def test_scaled_counts_from_a_ten_percent_sample_are_within_one_percent() -> None:
    events = _corpus(400_000)
    complete = _totals(1.0, events)
    sampled = _totals(0.1, events)
    assert complete["calls"] == len(events)
    for key, expected in complete.items():
        assert abs(sampled[key] - expected) / expected < 0.01, (key, sampled[key], expected)


def test_hourly_counter_scaling_keeps_the_v290_invariants() -> None:
    counter = HourlyCounter()
    for latency, auth, version in ((3, "true", "true"), (40, "unknown", "unknown"), (20_000, "false", "false")):
        event = UsageEvent.model_validate(
            {
                "observed_at": NOW.isoformat(),
                "source_id": SOURCE_ID,
                "environment": "prod",
                "method": "GET",
                "path": "/pets",
                "status": 200,
                "latency_ms": latency,
                "auth_present": auth,
                "version_hint": {"present": version},
            }
        )
        counter.add(event)
    for rate in (1.0, 0.3, 0.07):
        row = counter.scaled(rate)
        assert len(row["latency_buckets"]) == len(LATENCY_BOUNDS_MS) + 1
        assert sum(row["latency_buckets"]) == row["calls"]
        assert row["auth_present_calls"] + row["auth_unknown_calls"] <= row["calls"]
        assert row["versioned_calls"] + row["version_unknown_calls"] <= row["calls"]
        assert row["latency_max_ms"] == 20_000


# ---------------------------------------------------------------------------------------------
# Step 3 — scrubbing
# ---------------------------------------------------------------------------------------------


def test_the_edge_scrub_keeps_no_token_cookie_or_email() -> None:
    raw = [
        _event(f"/sessions/{BEARER.replace(' ', '%20')}"),
        _event(f"/sessions/{JWT}"),
        _event("/pets", user_agent=COOKIE_UA),
        _event(f"/pets?owner={EMAIL}&limit=10"),
        _event(f"/users/{EMAIL}/orders"),
    ]
    plan = plan_batch(raw, _source(field_capture=True), _matcher(), now=NOW)
    assert plan.rejected == 0
    stored = json.dumps(
        {
            "hourly": [list(map(str, key)) for key in plan.hourly],
            "unmatched": [list(map(str, key)) for key in plan.unmatched_rows],
            "fields": [[*map(str, key), *group.pointers] for key, group in plan.field_groups.items()],
        }
    )
    for secret in ("abcDEF1234567890ghiJKL", JWT, "s3cr3tSessionValue42", EMAIL, "alice"):
        assert secret not in stored
    assert plan.scrub_findings >= 4
    # The query *name* survives as a field counter; its value never did.
    pointers = {pointer for group in plan.field_groups.values() for pointer in group.pointers}
    assert f"{QUERY_POINTER_PREFIX}owner" in pointers and f"{QUERY_POINTER_PREFIX}limit" in pointers
    # The email segment was generalized, so the call still lands on its operation.
    assert any(key[3] == "/paths/~1users~1{userId}~1orders/get" for key in plan.hourly)


def test_scrub_event_generalizes_sensitive_segments_and_truncates_the_user_agent() -> None:
    event = UsageEvent.model_validate(
        {
            "observed_at": NOW.isoformat(),
            "source_id": SOURCE_ID,
            "environment": "prod",
            "method": "GET",
            "path": f"/files/{uuid.uuid4()}/{JWT}/raw",
            "status": 200,
            "latency_ms": 1,
            "fields": {"request": ["/name", f"/tokens/{JWT}"], "response": ["/id"]},
        }
    )
    scrubbed = scrub_event(0, event, ["limit", JWT, "has space"], None, user_agent=f"agent {EMAIL}\t" + "x" * 300)
    assert scrubbed.event.path == "/files/{param}/{param}/raw"
    agent = scrubbed.event.user_agent or ""
    assert EMAIL not in agent and "\t" not in agent and len(agent) == 256
    assert scrubbed.query_names == ("limit",)
    assert scrubbed.event.fields is not None and scrubbed.event.fields.request == ["/name"]
    assert scrubbed.findings == 2 + 1 + 2 + 1


def test_query_values_never_reach_the_event() -> None:
    plan = plan_batch([_event(f"/pets?token={JWT}&q={EMAIL}")], _source(), _matcher(), now=NOW)
    assert plan.accepted == 1
    assert "?" not in json.dumps([list(map(str, key)) for key in plan.hourly])


def test_inferred_template_generalizes_identifiers() -> None:
    assert template_path("/orders/12345/items/9f86d081884c7d65") == "/orders/{param}/items/{param}"
    assert template_path("/a/b") == "/a/b"


# ---------------------------------------------------------------------------------------------
# Step 4 — template matching
# ---------------------------------------------------------------------------------------------


def test_a_concrete_path_lands_on_its_template_the_pact_way() -> None:
    plan = plan_batch(
        [_event("/pets/42"), _event("/pets/mine"), _event("/v1/pets/7"), _event("/pets/{petId}")],
        _source(),
        _matcher(),
        now=NOW,
    )
    keys = sorted(key[3] for key in plan.hourly)
    assert keys == ["/paths/~1pets~1mine/get", "/paths/~1pets~1{petId}/get"]
    assert plan.accepted == 4


def test_an_operation_no_published_revision_declares_is_unmatched() -> None:
    # The draft declares GET /pets/{petId}/toys; only published revisions are handed to the matcher.
    plan = plan_batch([_event("/pets/42/toys"), _event("/pets/42", method="PATCH")], _source(), _matcher(), now=NOW)
    assert plan.accepted == 0 and plan.unmatched == 2
    assert sorted(key[2:] for key in plan.unmatched_rows) == [("GET", "/pets/{param}/toys"), ("PATCH", "/pets/{param}")]


def test_newest_published_revision_wins_and_spec_revision_id_is_preferred() -> None:
    newer = {"openapi": "3.1.0", "paths": {"/pets/{id}": {"get": {}}}}
    matcher = RevisionMatcher([("new", SpecIndex(newer)), ("old", SpecIndex(PUBLISHED))])
    assert matcher.match("GET", "/pets/1") == ("new", "/paths/~1pets~1{id}/get", "/pets/{id}")
    assert matcher.match("GET", "/pets/1", "old")[0] == "old"
    assert matcher.match("GET", "/nothing") is None


def test_unmatched_rows_count_status_classes_and_seen_times() -> None:
    later = (NOW + timedelta(minutes=5)).isoformat()
    plan = plan_batch(
        [_event("/x/1", status=500), _event("/x/2", status=201, observed_at=later)], _source(), _matcher(), now=NOW
    )
    (counter,) = plan.unmatched_rows.values()
    row = counter.scaled(1.0)
    assert row["calls"] == 2 and row["calls_5xx"] == 1 and row["calls_2xx"] == 1
    assert counter.first_seen == NOW and counter.last_seen == NOW + timedelta(minutes=5)


def test_fields_are_counted_only_with_field_capture() -> None:
    raw = [
        _event("/pets/1", fields={"request": [], "response": ["/id", "/name"]}),
        _event("/pets/2?limit=3", fields={"response": ["/id"]}),
    ]
    assert plan_batch(raw, _source(), _matcher(), now=NOW).field_groups == {}
    plan = plan_batch(raw, _source(field_capture=True), _matcher(), now=NOW)
    groups = {key[3]: group for key, group in plan.field_groups.items()}
    assert groups["response"].inspected == 2 and groups["response"].pointers == {"/id": 2, "/name": 1}
    assert groups["request"].inspected == 2 and groups["request"].pointers == {f"{QUERY_POINTER_PREFIX}limit": 1}


# ---------------------------------------------------------------------------------------------
# Rejections and the ledger
# ---------------------------------------------------------------------------------------------


def test_every_event_is_exactly_one_outcome() -> None:
    raw: List[Any] = [
        _event("/pets/1"),
        _event("/nowhere"),
        "not an object",
        _event("/pets/1", status=99),
        _event("/pets/1", source_id=str(uuid.uuid4())),
        _event("/pets/1", environment="mock"),
        _event("/pets/1", unknown_key=True),
        _event("/pets/1", observed_at="2026-10-01T00:00:00Z"),
    ]
    plan = plan_batch(raw, _source(), _matcher(), now=NOW, is_day_finalized=lambda day: day == date(2026, 10, 1))
    counts = plan.ledger_counts()
    assert counts["received"] == counts["accepted"] + counts["sampled_out"] + counts["unmatched"] + counts["rejected"]
    assert (plan.accepted, plan.unmatched, plan.rejected) == (1, 1, 6)
    assert [reason for _, reason in plan.rejections] == [
        "invalid-event",
        "invalid-event",
        "source-mismatch",
        "environment-reserved",
        "invalid-event",
        "day-finalized",
    ]


def test_a_mock_source_may_report_the_mock_environment() -> None:
    plan = plan_batch([_event("/pets/1", environment="mock")], _source(kind="mock"), _matcher(), now=NOW)
    assert plan.accepted == 1


def test_rejected_plan_rejects_every_event() -> None:
    plan = rejected_plan([{}, {}, {}], "quota-exceeded")
    assert plan.ledger_counts()["rejected"] == 3 == plan.received
    assert plan.hourly == {} and plan.samples == []


# ---------------------------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------------------------


def _sample(**response: Any) -> Dict[str, Any]:
    return {
        "request": {"headers": {"Authorization": BEARER, "Cookie": "sid=abc123def"}, "body": None},
        "response": {"headers": {"Content-Type": "application/json"}, "body": {"id": 1}, **response},
    }


def test_a_body_is_refused_unless_the_window_is_open() -> None:
    raw = [_event(sample=_sample())]
    for source in (
        _source(),
        _source(body_sample_rate=0.05, body_sample_until=NOW - timedelta(minutes=1)),
    ):
        with pytest.raises(UsageIngestError) as caught:
            refuse_closed_body_window(raw, source, NOW)
        assert (caught.value.status, caught.value.code) == (422, CODE_BODY_NOT_ACCEPTED)
    refuse_closed_body_window([_event()], _source(), NOW)
    refuse_closed_body_window(raw, _source(body_sample_rate=0.05, body_sample_until=NOW + timedelta(days=1)), NOW)


def test_reduce_sample_removes_credentials_and_refuses_what_still_flags() -> None:
    exchange = reduce_sample(_sample(), method="GET", path="/pets/{petId}", status=200)
    assert exchange is not None
    text = json.dumps(exchange)
    assert "abcDEF1234567890ghiJKL" not in text and "abc123def" not in text
    assert exchange["request"]["path"] == "/pets/{petId}" and exchange["redaction"]["count"] >= 2

    # An email is a personal-data pattern the reducer removes; a credential in free text is not
    # removable field-by-field, so the re-scan refuses the whole sample.
    assert EMAIL not in json.dumps(reduce_sample(_sample(body={"owner": EMAIL}), method="GET", path="/p", status=200))
    assert reduce_sample(_sample(body=f"note: {BEARER}"), method="GET", path="/p", status=200) is None
    assert reduce_sample(_sample(body="x" * (MAX_SAMPLE_BYTES + 1)), method="GET", path="/p", status=200) is None


def test_samples_are_taken_from_kept_events_at_the_body_rate() -> None:
    source = _source(body_sample_rate=0.05, body_sample_until=NOW + timedelta(days=1))
    raw = [
        _event(f"/pets/{i}", observed_at=(NOW + timedelta(seconds=i)).isoformat(), sample=_sample())
        for i in range(400)
    ]
    plan = plan_batch(raw, source, _matcher(), now=NOW)
    assert plan.accepted == 400
    assert 5 <= len(plan.samples) + plan.samples_dropped <= 40
    for _env, _at, operation_key, status, exchange in plan.samples:
        assert operation_key == "/paths/~1pets~1{petId}/get" and status == 200
        assert "authorization" not in {name.lower() for name in exchange["request"]["headers"]}


def test_a_long_user_agent_is_scrubbed_then_truncated_not_rejected() -> None:
    long_agent = "x" * 300 + f" token={JWT}"
    built = plan_batch([_event("/pets/1", user_agent=long_agent)], _source(), _matcher(), now=NOW)
    assert (built.accepted, built.rejected) == (1, 0)
    assert built.scrub_findings >= 1


def test_a_hostile_batch_of_long_token_shaped_strings_plans_in_bounded_time() -> None:
    # A 2,000-character word used to cost the secret-assignment pattern quadratic time per scan.
    import time

    word = "a" * 2000
    raw = [_event(f"/blob/{word}{i}", user_agent=word) for i in range(1000)]
    started = time.monotonic()
    plan = plan_batch(raw, _source(), _matcher(), now=NOW)
    assert time.monotonic() - started < 20
    # Longer than the index's 1,024-character template column, so each is rejected — not stored cut.
    assert plan.rejected == 1000 and {reason for _, reason in plan.rejections} == {"template-unstorable"}


def test_values_the_index_cannot_store_are_rejected_not_written() -> None:
    spaced = {"openapi": "3.1.0", "paths": {"/odd/{pet id}": {"get": {}}, "/pets/{petId}": {"get": {}}}}
    plan = plan_batch(
        [_event("/odd/1"), _event("/pets/1", latency_ms=2**31)],
        _source(),
        RevisionMatcher([("v0", SpecIndex(spaced))]),
        now=NOW,
    )
    # The spec's own template has a space the operation_key CHECK refuses; the latency would
    # overflow latency_max_ms (INTEGER).
    assert sorted(reason for _, reason in plan.rejections) == ["invalid-event", "template-unstorable"]
    assert plan.hourly == {}


def test_the_sample_size_is_measured_as_postgres_measures_it() -> None:
    # ``jsonb::text`` writes ", " and ": ", so an exchange that fits when compact may not fit stored.
    body = {f"k{i:04d}": i for i in range(1270)}
    compact = len(json.dumps({"body": body}, separators=(",", ":")))
    assert compact < MAX_SAMPLE_BYTES < len(json.dumps({"body": body}))
    assert reduce_sample({"response": {"body": body}}, method="GET", path="/p", status=200) is None
