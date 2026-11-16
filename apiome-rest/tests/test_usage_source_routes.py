"""``POST /v1/tenants/{tenant}/usage/sources/har`` and its store — RDG-1.4 (#5762).

The database is a fake that answers the store's three statements (load a named source, find the
project's HAR source, create one), so these tests pin the decisions: a named source must be the
project's and a ``har`` one, a disabled source is refused rather than replaced, a missing one is
created with field capture on, the environment is validated, and the ``usage:ingest`` scope admits
the route.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.auth import API_KEY_SCOPE_USAGE_INGEST, acceptable_scopes_for_request, validate_authentication
from app.main import app
from app.usage_ingest import UsageIngestError
from app.usage_source_store import resolve_har_source

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
OTHER_PROJECT = "33333333-3333-3333-3333-333333333333"
SOURCE_ID = "6f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"
URL = "/v1/tenants/acme/usage/sources/har"


def _row(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": SOURCE_ID,
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "kind": "har",
        "environment": "staging",
        "sampling_rate": 1,
        "field_capture": True,
        "body_sample_rate": 0,
        "body_sample_until": None,
        "enabled": True,
    }
    row.update(overrides)
    return row


class FakeDb:
    """Answers ``usage_source`` reads and inserts; records every statement."""

    def __init__(self, *, named: Optional[Dict[str, Any]] = None, found: Optional[Dict[str, Any]] = None) -> None:
        self.named = named
        self.found = found
        self.statements: List[str] = []

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        self.statements.append(" ".join(query.split()))
        if "INSERT INTO apiome.usage_source" in query:
            return [_row(id="44444444-4444-4444-4444-444444444444", environment=params[3])]
        if "WHERE id = %s::uuid" in query:
            return [self.named] if self.named else []
        return [self.found] if self.found else []

    def get_project_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return {"id": PROJECT_ID, "slug": slug} if slug == "pets" else None

    def get_project_by_id(self, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return {"id": project_id, "slug": "pets"} if project_id == PROJECT_ID else None


def _resolve(db: FakeDb, **kwargs: Any):
    params = {"tenant_id": TENANT_ID, "project_id": PROJECT_ID, "environment": "staging", **kwargs}
    return resolve_har_source(db, **params)


def test_an_existing_har_source_is_answered_and_nothing_is_created() -> None:
    db = FakeDb(found=_row())
    resolved = _resolve(db)
    assert resolved.created is False and resolved.source.id == SOURCE_ID
    assert not any("INSERT" in s for s in db.statements)
    assert "kind = %s AND environment = %s" in db.statements[0]


def test_a_missing_source_is_created_with_field_capture_on() -> None:
    db = FakeDb()
    resolved = _resolve(db, environment="qa")
    assert resolved.created is True
    assert resolved.source.kind == "har" and resolved.source.field_capture is True
    assert resolved.source.environment == "qa"
    insert = db.statements[-1]
    assert "INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment, field_capture)" in insert


def test_a_disabled_source_is_refused_not_replaced() -> None:
    db = FakeDb(found=_row(enabled=False))
    with pytest.raises(UsageIngestError) as caught:
        _resolve(db)
    assert caught.value.status == 403 and caught.value.code == "usage-source-disabled"
    assert not any("INSERT" in s for s in db.statements)


def test_a_named_source_must_be_the_projects_and_a_har_source() -> None:
    with pytest.raises(UsageIngestError) as other_project:
        _resolve(FakeDb(named=_row(project_id=OTHER_PROJECT)), source_ref=SOURCE_ID)
    assert (other_project.value.status, other_project.value.code) == (409, "usage-source-project-mismatch")

    with pytest.raises(UsageIngestError) as wrong_kind:
        _resolve(FakeDb(named=_row(kind="otlp")), source_ref=SOURCE_ID)
    assert (wrong_kind.value.status, wrong_kind.value.code) == (409, "usage-source-kind-mismatch")

    resolved = _resolve(FakeDb(named=_row()), source_ref=SOURCE_ID)
    assert resolved.source.id == SOURCE_ID and resolved.created is False


def test_an_unknown_named_source_is_not_found() -> None:
    with pytest.raises(UsageIngestError) as caught:
        _resolve(FakeDb(), source_ref=SOURCE_ID)
    assert caught.value.status == 404


@pytest.mark.parametrize("environment", ["mock", "Prod", "1st", "", "x" * 33])
def test_invalid_or_reserved_environments_are_refused(environment: str) -> None:
    with pytest.raises(UsageIngestError) as caught:
        _resolve(FakeDb(), environment=environment)
    assert caught.value.status == 400


def test_the_ingest_scope_admits_the_route() -> None:
    assert API_KEY_SCOPE_USAGE_INGEST in acceptable_scopes_for_request("POST", URL)
    assert API_KEY_SCOPE_USAGE_INGEST not in acceptable_scopes_for_request("GET", URL)
    other_kind = "/v1/tenants/acme/usage/sources/otlp"
    assert API_KEY_SCOPE_USAGE_INGEST not in acceptable_scopes_for_request("POST", other_kind)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, FakeDb]]:
    """A test client whose route reads the fake database."""
    db = FakeDb(found=_row(body_sample_rate=0.05, body_sample_until=datetime.now(timezone.utc) + timedelta(days=1)))
    monkeypatch.setattr("app.usage_source_routes.db", db)
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "api_key",
        "tenant_id": TENANT_ID,
        "id": "k-1",
        "scopes": ["usage:ingest"],
    }
    yield TestClient(app), db
    app.dependency_overrides.pop(validate_authentication, None)


def test_the_route_answers_the_source_in_camel_case(client: tuple[TestClient, FakeDb]) -> None:
    test_client, _db = client
    response = test_client.post(URL, json={"project": "pets", "environment": "staging"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sourceId": SOURCE_ID,
        "projectId": PROJECT_ID,
        "kind": "har",
        "environment": "staging",
        "samplingRate": 1.0,
        "fieldCapture": True,
        "bodySamplesOpen": True,
        "created": False,
    }


def test_the_route_refuses_an_unknown_project_and_a_conflicting_source(client: tuple[TestClient, FakeDb]) -> None:
    test_client, db = client
    missing = test_client.post(URL, json={"project": "nope", "environment": "staging"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "project-not-found"

    db.named = _row(kind="access_log")
    conflict = test_client.post(URL, json={"project": "pets", "environment": "staging", "sourceId": SOURCE_ID})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "usage-source-kind-mismatch"


def test_the_route_refuses_unknown_keys(client: tuple[TestClient, FakeDb]) -> None:
    test_client, _db = client
    response = test_client.post(URL, json={"project": "pets", "environment": "staging", "kind": "otlp"})
    assert response.status_code == 422
