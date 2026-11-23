"""SDK compatibility beacon — RDG-1.7 / SGD-3.1 (#4736): contract, store and routes.

* **Only the allowed facts.** A report can carry SDK name and version, API version, revision,
  operation, outcome and a count — unknown keys (a body, a header, a status, a host) and any value
  that is not version- or identifier-shaped are refused with 422.
* **Tenant controls.** The source must exist, be enabled (its ``enabled`` flag is the off switch) and
  be of kind ``sdk_beacon``; only a workspace API key may report.
* **Correlation.** Counts are keyed by the published revision and the manifest's operation id; an
  event naming a revision that is not a published revision of the source's project is rejected.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import sdk_beacon_routes
from app.auth import validate_authentication
from app.main import app
from app.sdk_beacon import SdkBeaconBatch, SdkBeaconEvent
from app.sdk_beacon_store import ingest_beacons, list_beacon_counts

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SOURCE = "33333333-3333-4333-8333-333333333333"
GATEWAY_SOURCE = "44444444-4444-4444-8444-444444444444"
OFF_SOURCE = "55555555-5555-4555-8555-555555555555"
REVISION = "66666666-6666-4666-8666-666666666666"
DRAFT_REVISION = "77777777-7777-4777-8777-777777777777"
NOW = datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc)

URL = "/v1/tenants/acme/usage/sdk-beacon"
READ = "/v1/tenants/acme/usage/sdk-beacons"


def _event(**overrides: Any) -> Dict[str, Any]:
    event = {
        "sdk_name": "comments-go",
        "sdk_version": "1.4.0",
        "api_version": "1.2.0",
        "spec_revision_id": REVISION,
        "operation_id": "getThread",
        "outcome": "ok",
        "count": 3,
    }
    event.update(overrides)
    return event


class FakeDb:
    """Answers the queries the beacon store issues, and records the upserts."""

    def __init__(self) -> None:
        self.sources = {
            SOURCE: {"kind": "sdk_beacon", "enabled": True},
            GATEWAY_SOURCE: {"kind": "access_log", "enabled": True},
            OFF_SOURCE: {"kind": "sdk_beacon", "enabled": False},
        }
        self.published = {REVISION}
        self.rows: Dict[tuple, Dict[str, Any]] = {}

    # load_source
    def execute_query(self, query: str, params: Any = None) -> List[Dict[str, Any]]:
        if "FROM apiome.usage_source" in query:
            source_id, tenant_id = params
            source = self.sources.get(source_id)
            if not source or tenant_id != TENANT:
                return []
            return [
                {
                    "id": source_id,
                    "tenant_id": TENANT,
                    "project_id": PROJECT,
                    "kind": source["kind"],
                    "environment": "prod",
                    "sampling_rate": 1.0,
                    "field_capture": False,
                    "body_sample_rate": 0.0,
                    "body_sample_until": None,
                    "enabled": source["enabled"],
                }
            ]
        if "FROM apiome.versions v" in query:
            ids, project_id = params
            return [{"id": rid} for rid in ids if rid in self.published and project_id == PROJECT]
        if "FROM apiome.usage_sdk_beacon_daily" in query:
            tenant_id, project_id, since = params
            out = []
            for key, row in self.rows.items():
                if key[0] == tenant_id and key[1] == project_id and key[3] >= since:
                    out.append(
                        {
                            "spec_revision_id": key[4],
                            "api_version": key[5],
                            "sdk_name": key[6],
                            "sdk_version": key[7],
                            "operation_id": key[8],
                            "outcome": key[9],
                            "calls": row["calls"],
                            "first_seen_at": row["first_seen_at"],
                            "last_seen_at": row["last_seen_at"],
                        }
                    )
            return out
        raise AssertionError(f"unexpected query: {query}")

    def _guarded_tx(self, work: Any) -> Any:
        return work(self)

    # cursor.execute for the upsert: one statement, one array per column (DBP-1.7, #7190)
    def execute(self, query: str, params: Any) -> None:
        assert "INSERT INTO apiome.usage_sdk_beacon_daily" in query.replace('"', "")
        for values in zip(*params):
            key, (calls, first, last) = tuple(values[:10]), values[10:]
            row = self.rows.setdefault(key, {"calls": 0, "first_seen_at": first, "last_seen_at": last})
            row["calls"] += calls
            row["last_seen_at"] = max(row["last_seen_at"], last)

    def get_project_by_slug(self, slug: str, tenant_id: str):
        return {"id": PROJECT} if slug == "pets" and tenant_id == TENANT else None

    def get_project_by_id(self, project_id: str, tenant_id: str):
        return {"id": PROJECT} if project_id == PROJECT and tenant_id == TENANT else None


@pytest.fixture
def fake(monkeypatch) -> FakeDb:
    db = FakeDb()
    monkeypatch.setattr(sdk_beacon_routes, "db", db)
    return db


@pytest.fixture
def as_key():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT, "auth_method": "api_key", "scopes": ["usage:ingest"], "user_id": None
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------------------------
# The contract: only the allowed facts
# ---------------------------------------------------------------------------------------------


def test_a_well_formed_event_is_accepted() -> None:
    event = SdkBeaconEvent(**_event(operation_id="GET /pets/{petId}"))
    assert event.outcome == "ok" and event.count == 3


@pytest.mark.parametrize(
    "extra",
    [
        {"body": "{}"},
        {"headers": {"Authorization": "Bearer x"}},
        {"status": 500},
        {"latency_ms": 12},
        {"host": "api.example.com"},
        {"url": "https://api.example.com/pets/1"},
        {"user_id": "u-1"},
        {"ip": "10.0.0.1"},
    ],
)
def test_any_other_field_is_refused(extra) -> None:
    with pytest.raises(ValidationError):
        SdkBeaconEvent(**_event(**extra))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sdk_name", "Acme SDK"),
        ("sdk_name", "jane@example.com"),
        ("sdk_version", "1.0 (build 7)"),
        ("api_version", "https://api.example.com"),
        ("operation_id", "getPet?token=secret"),
        ("operation_id", "x" * 300),
        ("outcome", "timeout"),
        ("count", 0),
        ("count", 10_001),
        ("spec_revision_id", "not-a-uuid"),
    ],
)
def test_values_that_are_not_version_or_identifier_shaped_are_refused(field, value) -> None:
    with pytest.raises(ValidationError):
        SdkBeaconEvent(**_event(**{field: value}))


def test_a_report_has_one_to_five_hundred_events() -> None:
    with pytest.raises(ValidationError):
        SdkBeaconBatch(events=[])
    with pytest.raises(ValidationError):
        SdkBeaconBatch(events=[_event()] * 501)
    assert len(SdkBeaconBatch(events=[_event()] * 500).events) == 500


# ---------------------------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------------------------


def test_events_are_aggregated_onto_the_receive_day(fake) -> None:
    batch = SdkBeaconBatch(
        events=[_event(), _event(count=2), _event(outcome="incompatible", count=1)], source_id=SOURCE
    )
    outcome = ingest_beacons(fake, tenant_id=TENANT, source_ref=SOURCE, batch=batch, now=NOW)
    assert (outcome.accepted, outcome.calls, outcome.rejected) == (3, 6, [])
    counts = {key[9]: row["calls"] for key, row in fake.rows.items()}
    assert counts == {"ok": 5, "incompatible": 1}
    assert {key[3] for key in fake.rows} == {date(2026, 11, 15)}


def test_an_unknown_or_unpublished_revision_is_rejected_by_index(fake) -> None:
    batch = SdkBeaconBatch(events=[_event(), _event(spec_revision_id=DRAFT_REVISION)])
    outcome = ingest_beacons(fake, tenant_id=TENANT, source_ref=SOURCE, batch=batch, now=NOW)
    assert outcome.accepted == 1
    assert [(r.index, r.reason) for r in outcome.rejected] == [(1, "revision-unknown")]


def test_the_read_groups_by_manifest_keys(fake) -> None:
    ingest_beacons(fake, tenant_id=TENANT, source_ref=SOURCE, batch=SdkBeaconBatch(events=[_event()]), now=NOW)
    (row,) = list_beacon_counts(fake, tenant_id=TENANT, project_id=PROJECT, days=30, today=NOW.date())
    assert row["spec_revision_id"] == REVISION and row["operation_id"] == "getThread" and row["calls"] == 3


# ---------------------------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------------------------


def test_a_report_is_counted(fake, as_key) -> None:
    response = client.post(URL, json={"schema": "apiome.sdk.beacon/v1", "source_id": SOURCE, "events": [_event()]})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] == 1 and body["calls"] == 3 and body["rejected"] == []


def test_the_source_may_be_named_by_header(fake, as_key) -> None:
    response = client.post(URL, json={"events": [_event()]}, headers={"X-Apiome-Usage-Source": SOURCE})
    assert response.status_code == 202


@pytest.mark.parametrize(
    ("payload", "headers", "status", "code"),
    [
        ({"events": [_event()]}, {}, 400, "usage-source-required"),
        ({"events": [_event()], "source_id": SOURCE}, {"X-Apiome-Usage-Source": OFF_SOURCE}, 400, "usage-batch-invalid"),
        ({"events": [_event()], "source_id": OFF_SOURCE}, {}, 403, "usage-source-disabled"),
        ({"events": [_event()], "source_id": GATEWAY_SOURCE}, {}, 409, "usage-source-kind-mismatch"),
        ({"events": [_event()], "source_id": "99999999-9999-4999-8999-999999999999"}, {}, 404, "usage-source-not-found"),
    ],
)
def test_the_tenant_controls_are_enforced(fake, as_key, payload, headers, status, code) -> None:
    response = client.post(URL, json=payload, headers=headers)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert fake.rows == {}


def test_a_disabled_source_counts_nothing(fake, as_key) -> None:
    client.post(URL, json={"events": [_event()], "source_id": OFF_SOURCE})
    assert fake.rows == {}


def test_a_payload_with_more_than_the_allowed_facts_is_422(fake, as_key) -> None:
    response = client.post(URL, json={"source_id": SOURCE, "events": [_event(body="{\"card\": \"4111\"}")]})
    assert response.status_code == 422
    assert fake.rows == {}


def test_a_session_cannot_report(fake) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT, "auth_method": "jwt", "user_id": "u-1"
    }
    try:
        response = client.post(URL, json={"source_id": SOURCE, "events": [_event()]})
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "usage-ingest-key-required"


def test_the_usage_ingest_scope_admits_the_beacon_door_and_nothing_more() -> None:
    from app.auth import API_KEY_SCOPE_USAGE_INGEST, acceptable_scopes_for_request

    assert API_KEY_SCOPE_USAGE_INGEST in acceptable_scopes_for_request("POST", "/v1/tenants/acme/usage/sdk-beacon")
    assert API_KEY_SCOPE_USAGE_INGEST not in acceptable_scopes_for_request("GET", "/v1/tenants/acme/usage/sdk-beacons")


def test_the_owner_reads_counts_keyed_by_revision_and_operation(fake, as_key, monkeypatch) -> None:
    client.post(URL, json={"source_id": SOURCE, "events": [_event(), _event(outcome="incompatible", count=1)]})
    monkeypatch.setattr(sdk_beacon_routes, "enforce_permission", lambda *a, **k: "u-1")
    response = client.get(READ, params={"project": "pets", "days": 7})
    assert response.status_code == 200, response.text
    counts = {row["outcome"]: row["calls"] for row in response.json()["counts"]}
    assert counts == {"ok": 3, "incompatible": 1}
    assert {row["spec_revision_id"] for row in response.json()["counts"]} == {REVISION}


def test_the_read_needs_consumer_contracts_view(fake, as_key, monkeypatch) -> None:
    from fastapi import HTTPException

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="no")

    monkeypatch.setattr(sdk_beacon_routes, "enforce_permission", deny)
    assert client.get(READ, params={"project": "pets"}).status_code == 403


def test_an_unknown_project_is_404(fake, as_key, monkeypatch) -> None:
    monkeypatch.setattr(sdk_beacon_routes, "enforce_permission", lambda *a, **k: "u-1")
    response = client.get(READ, params={"project": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "usage-project-not-found"
