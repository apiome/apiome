"""Reading an import batch, and who may send one — PFX-6.7 (#6959).

No database: :func:`app.pact_migration.parse_import_request` is pure, and the route tests stub the
permission predicate (the live-database behaviour is ``test_pact_migration_db``).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_migration import (
    MAX_RECORDS,
    DeploymentImport,
    EnvironmentImport,
    MigrationOutcome,
    PacticipantImport,
    PactImport,
    RefusedRecord,
    ReleaseImport,
    VerificationImport,
    VersionImport,
    WebhookImport,
    count_outcomes,
    parse_import_request,
    parse_timestamp,
)
from app.pact_publication import PactPublicationError

PACT = {
    "consumer": {"name": "Billing Service"},
    "provider": {"name": "Ledger API"},
    "interactions": [
        {"description": "an invoice", "request": {"method": "GET", "path": "/i/1"}, "response": {"status": 200}}
    ],
    "metadata": {"pactSpecification": {"version": "2.0.0"}},
}


def _parse(*records: Any) -> List[Any]:
    raw = json.dumps({"source": "https://broker.example.com", "records": list(records)}).encode()
    with patch("app.pact_webhook.validate_host", lambda _host: None):
        return list(parse_import_request(raw, max_pact_bytes=1_000_000).records)


def _one(record: Dict[str, Any]) -> Any:
    return _parse(record)[0]


# ---------------------------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,fragment",
    [
        (b"not json", "not JSON"),
        (b"[]", "JSON object"),
        (b"{}", "/records"),
        (b'{"records": []}', "non-empty"),
        (json.dumps({"records": [{}] * (MAX_RECORDS + 1)}).encode(), f"at most {MAX_RECORDS}"),
        (b'{"records": [{"kind": "pacticipant", "name": "A"}], "source": 7}', "/source"),
    ],
)
def test_a_malformed_envelope_refuses_the_request(raw: bytes, fragment: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_import_request(raw, max_pact_bytes=1000)
    assert caught.value.code == "pact-migration-invalid"
    assert fragment in str(caught.value)


def test_a_malformed_record_is_refused_and_the_rest_is_read() -> None:
    records = _parse("x", {"kind": "team"}, {"name": "No kind"}, {"kind": "pacticipant", "name": "Billing Service"})
    assert [type(r) for r in records] == [RefusedRecord, RefusedRecord, RefusedRecord, PacticipantImport]
    assert records[0].message == "/records/0: must be a JSON object"
    assert records[1].message.startswith("/records/1/kind: must be one of pacticipant")
    assert records[1].kind == "team" and records[2].kind is None


# ---------------------------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------------------------


def test_timestamps_are_read_as_iso_8601_in_utc() -> None:
    assert parse_timestamp("2025-03-01T09:30:00Z") == datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)
    assert parse_timestamp("2025-03-01T09:30:00") == datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)
    assert parse_timestamp("2025-03-01T10:30:00+01:00") == datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)
    assert parse_timestamp(None) is None


@pytest.mark.parametrize(
    "value", ["yesterday", "", 1700000000, (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()]
)
def test_a_bad_timestamp_refuses_the_record(value: Any) -> None:
    refused = _one({"kind": "pacticipant", "name": "Billing Service", "created_at": value})
    assert isinstance(refused, RefusedRecord)
    assert refused.message.startswith("/records/0/created_at")


# ---------------------------------------------------------------------------------------------
# Each kind
# ---------------------------------------------------------------------------------------------


def test_a_pacticipant_record() -> None:
    record = _one(
        {
            "kind": "pacticipant",
            "name": "Billing Service",
            "repository_url": "https://github.com/acme/billing",
            "main_branch": "main",
            "labels": ["team-billing", "team-billing", "tier-1"],
            "created_at": "2025-03-01T09:30:00Z",
        }
    )
    assert isinstance(record, PacticipantImport)
    assert (record.slug, record.key, record.main_branch) == ("billing-service", "billing-service", "main")
    assert record.labels == ("team-billing", "tier-1")
    assert record.created_at == datetime(2025, 3, 1, 9, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "record,pointer",
    [
        ({"kind": "pacticipant"}, "/name"),
        ({"kind": "pacticipant", "name": "!!!"}, "/name"),
        ({"kind": "pacticipant", "name": "A", "repository_url": "ftp://x"}, "/repository_url"),
        ({"kind": "pacticipant", "name": "A", "labels": "x"}, "/labels"),
        ({"kind": "pacticipant", "name": "A", "labels": [""]}, "/labels/0"),
    ],
)
def test_a_bad_pacticipant_is_refused_at_the_field(record: Dict[str, Any], pointer: str) -> None:
    refused = _one(record)
    assert isinstance(refused, RefusedRecord), refused
    assert refused.message.startswith(f"/records/0{pointer}"), refused.message


def test_a_version_record_reads_branches_and_tags_in_both_forms() -> None:
    record = _one(
        {
            "kind": "version",
            "pacticipant": "Billing Service",
            "number": "4f2a9c1",
            "branches": ["main", "main", "release"],
            "tags": ["prod", {"name": "audited", "created_at": "2025-03-02T00:00:00Z"}, "prod"],
        }
    )
    assert isinstance(record, VersionImport)
    assert record.key == "billing-service/4f2a9c1"
    assert record.branches == ("main", "release")
    assert [(t.name, t.created_at) for t in record.tags] == [
        ("prod", None),
        ("audited", datetime(2025, 3, 2, tzinfo=timezone.utc)),
    ]


@pytest.mark.parametrize(
    "extra,pointer",
    [
        ({"number": " 1 "}, "/number"),
        ({"number": "1", "build_url": "not a url"}, "/build_url"),
        ({"number": "1", "branches": [7]}, "/branches/0"),
        ({"number": "1", "tags": [{"name": "x", "created_at": "never"}]}, "/tags/0/created_at"),
    ],
)
def test_a_bad_version_is_refused_at_the_field(extra: Dict[str, Any], pointer: str) -> None:
    refused = _one({"kind": "version", "pacticipant": "Billing Service", **extra})
    assert isinstance(refused, RefusedRecord), refused
    assert refused.message.startswith(f"/records/0{pointer}"), refused.message


def test_a_pact_record_is_checked_as_a_publish_checks_it() -> None:
    record = _one(
        {
            "kind": "pact",
            "consumer": "billing-service",
            "provider": "Ledger API",
            "consumer_version": "1",
            "content": PACT,
        }
    )
    assert isinstance(record, PactImport)
    assert record.pact.consumer_name == "Billing Service"  # the document's name wins over the handle
    assert record.key == "ledger-api/billing-service/1"
    mismatched = _one(
        {"kind": "pact", "consumer": "Other", "provider": "Ledger API", "consumer_version": "1", "content": PACT}
    )
    assert isinstance(mismatched, RefusedRecord)
    assert mismatched.message.startswith("/records/0/content/consumer/name")
    missing = _one({"kind": "pact", "consumer": "A", "provider": "B", "consumer_version": "1"})
    assert missing.message.startswith("/records/0/content: must be a JSON object")


def test_a_verification_record() -> None:
    base = {"kind": "verification", "consumer": "Billing Service", "provider": "Ledger API", "consumer_version": "1"}
    record = _one({**base, "number": 3, "result": {"success": False, "providerApplicationVersion": "7"}})
    assert isinstance(record, VerificationImport)
    assert (record.number, record.result.success, record.key) == (3, False, "ledger-api/billing-service/1/3")
    for number in (0, "3", True, None):
        refused = _one({**base, "number": number, "result": {"success": True, "providerApplicationVersion": "7"}})
        assert refused.message.startswith("/records/0/number"), number
    no_version = _one({**base, "number": 1, "result": {"success": True}})
    assert no_version.message.startswith("/records/0/result")


def test_environment_deployment_and_release_records() -> None:
    environment, deployment, release = _parse(
        {"kind": "environment", "name": "production", "display_name": "Production", "production": True},
        {
            "kind": "deployment",
            "pacticipant": "Ledger API",
            "version": "7",
            "environment": "production",
            "application_instance": "eu",
        },
        {"kind": "release", "pacticipant": "Ledger API", "version": "7", "environment": "production"},
    )
    assert isinstance(environment, EnvironmentImport) and environment.environment.production is True
    assert isinstance(deployment, DeploymentImport) and deployment.key == "ledger-api/7@production/eu"
    assert isinstance(release, ReleaseImport) and release.key == "ledger-api/7@production"
    spaced = _one({"kind": "environment", "name": "pro duction"})
    assert spaced.message.startswith("/records/0/name")
    bad_instance = _one(
        {"kind": "deployment", "pacticipant": "A", "version": "1", "environment": "e", "application_instance": " eu"}
    )
    assert bad_instance.message.startswith("/records/0/application_instance")


def test_a_webhook_record() -> None:
    body = {
        "events": [{"name": "contract_published"}],
        "request": {"method": "POST", "url": "https://ci.example.com/h"},
    }
    record = _one({"kind": "webhook", "uuid": "3F1B2C4D-5E6F-4A7B-8C9D-0E1F2A3B4C5D", "webhook": body})
    assert isinstance(record, WebhookImport)
    assert record.uuid == "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d" and record.key == record.uuid
    assert _one({"kind": "webhook", "webhook": body}).key == "webhook#0"
    assert _one({"kind": "webhook", "uuid": "abc", "webhook": body}).message == "/records/0/uuid: must be a UUID"


@pytest.mark.parametrize(
    ("request_part", "field"),
    [
        ({"headers": {"Authorization": "**********"}}, "header_authorization"),
        ({"username": "ci", "password": "**********"}, "password"),
    ],
)
def test_a_redacted_webhook_secret_waits_for_a_placeholder_secret(request_part: Dict[str, Any], field: str) -> None:
    """PFX-8.15: a redacted value becomes a reference to a value-less secret; the webhook is turned off."""
    uuid = "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    body = {"request": {"method": "POST", "url": "https://ci.example.com/h", **request_part}}
    record = _one({"kind": "webhook", "uuid": uuid, "webhook": body})
    assert not isinstance(record, RefusedRecord)
    ((name, description),) = record.placeholders
    assert name.startswith("migrated_") and name.endswith(field) and len(name) <= 64
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
    assert "Waiting for a value" in description and uuid in description
    assert record.webhook.enabled is False
    stored = record.webhook.password if field == "password" else record.webhook.secret_headers["Authorization"]
    assert stored == "${user." + name + "}"
    # The same webhook names the same placeholder on a re-run, so nothing is created twice.
    again = _one({"kind": "webhook", "uuid": uuid, "webhook": body})
    assert again.placeholders == record.placeholders


def test_a_redacted_plain_header_becomes_a_sealed_placeholder() -> None:
    """A header Apiome would not call secret, but the source redacted, is never sent as `**********`."""
    body = {"request": {"method": "POST", "url": "https://ci.example.com/h", "headers": {"X-Build": "**********"}}}
    record = _one({"kind": "webhook", "webhook": body})
    ((name, _),) = record.placeholders
    assert "X-Build" not in record.webhook.headers
    assert record.webhook.secret_headers["X-Build"] == "${user." + name + "}"
    assert record.webhook.enabled is False


def test_a_webhook_with_its_secrets_needs_no_placeholder() -> None:
    body = {"request": {"method": "POST", "url": "https://ci.example.com/h", "username": "ci", "password": "s3cret"}}
    record = _one({"kind": "webhook", "webhook": body})
    assert record.placeholders == [] and record.webhook.enabled is True and record.webhook.password == "s3cret"


def test_count_outcomes() -> None:
    results = [MigrationOutcome(index=i, outcome=o) for i, o in enumerate(["created", "created", "refused"])]
    assert count_outcomes(results) == {"created": 2, "refused": 1}


# ---------------------------------------------------------------------------------------------
# Who may send a batch
# ---------------------------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)
BODY = {"records": [{"kind": "environment", "name": "staging"}]}


@pytest.fixture
def granted(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Authenticate as a member of ``acme``; ``granted.set(...)`` chooses the pacts permissions held."""
    held: Dict[str, Any] = {"permissions": set()}
    app.dependency_overrides[validate_broker_authentication] = lambda: {
        "tenant_id": "tenant-acme",
        "user_id": "user-1",
        "auth_method": "jwt",
    }

    def enforce(_db: Any, _auth: Any, resource: Any, action: Any, **_: Any) -> str:
        permission = f"{getattr(resource, 'value', resource)}:{getattr(action, 'value', action)}"
        if permission not in held["permissions"]:
            raise HTTPException(status_code=403, detail=f"Missing permission {permission}")
        return "user-1"

    monkeypatch.setattr("app.pact_migration_routes.enforce_permission", enforce)
    monkeypatch.setattr("app.pact_migration_routes.import_records", lambda *a, **k: [])
    monkeypatch.setattr("app.pact_migration_routes.check_records", lambda *a, **k: [])
    yield held
    app.dependency_overrides.pop(validate_broker_authentication, None)


@pytest.mark.parametrize(
    "path,permissions,status",
    [
        ("/import", {"pacts:view"}, 403),
        ("/import", {"pacts:view", "pacts:create"}, 403),
        ("/import", {"pacts:view", "pacts:edit"}, 403),
        ("/import", {"pacts:create", "pacts:edit"}, 200),
        ("/check", set(), 403),
        ("/check", {"pacts:view"}, 200),
    ],
)
def test_the_permissions_an_import_and_a_check_need(granted: Any, path: str, permissions: set, status: int) -> None:
    granted["permissions"] = permissions
    response = client.post(f"/v1/tenants/acme/pact-migration{path}", json=BODY)
    assert response.status_code == status, response.text


def test_a_malformed_envelope_is_a_422_naming_the_problem(granted: Any) -> None:
    granted["permissions"] = {"pacts:view", "pacts:create", "pacts:edit"}
    response = client.post("/v1/tenants/acme/pact-migration/import", json={"records": []})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-migration-invalid"
