"""HTTP contract tests for comparison fidelity reports — PFX-2.5 (#6929).

The routes of :mod:`app.pact_comparison_routes` with the store faked, and the two store reads with a
fake database:

* both routes need ``pacts:view``; a denial is a 403 before the store is touched;
* every read is scoped to the caller's tenant (the tenant id comes from the credential, never the
  URL);
* the list carries each result's verdict, strength, statement, counts and report path;
* the report of an unknown, foreign or native result is a 404 that says which;
* ``limit`` is bounded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_publication import PactPublicationError
from app.verification_result import CODE_VERIFICATION_NOT_FOUND, VerificationResultRecord
from app.verification_result_store import (
    MAX_BIDIRECTIONAL_LIST,
    get_bidirectional_result,
    list_bidirectional_results,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_RESULT_ID = "22222222-2222-4222-8222-222222222222"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session"}
_BASE = "/v1/tenants/acme/pact-comparisons"
_ROUTES = "app.pact_comparison_routes"
_GOLDEN = Path(__file__).parent / "golden" / "pact_oas_compare" / "expected"


def _comparison(name: str = "partial-19-oneof-relaxed") -> Dict[str, Any]:
    return json.loads((_GOLDEN / f"{name}.json").read_text())


def _result(**overrides: Any) -> VerificationResultRecord:
    payload: Dict[str, Any] = {
        "id": _RESULT_ID,
        "number": 2,
        "consumer_slug": "billing-service",
        "consumer_name": "Billing Service",
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "provider_version": "5.1.0",
        "consumer_version": "2.0.0",
        "sha": "ab" * 32,
        "success": True,
        "provider_branch": "main",
        "created_at": "2026-11-24T10:00:00+00:00",
        "kind": "bidirectional",
        "comparison": _comparison(),
    }
    payload.update(overrides)
    return VerificationResultRecord(**payload)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


# --- RBAC -------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [_BASE, f"{_BASE}/{_RESULT_ID}/fidelity"])
def test_both_routes_need_pacts_view(path: str) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
        patch(f"{_ROUTES}.list_bidirectional_results") as listing,
        patch(f"{_ROUTES}.get_bidirectional_result") as reading,
    ):
        response = client.get(path)
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == ("pacts", "view")
    listing.assert_not_called()
    reading.assert_not_called()


def test_a_credential_without_a_tenant_is_refused(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u"}
    with patch(f"{_ROUTES}.list_bidirectional_results") as listing:
        response = client.get(_BASE)
    assert response.status_code == 403
    listing.assert_not_called()


# --- the list ---------------------------------------------------------------------------------


def test_the_list_reads_the_callers_tenant_and_summarises_each_result(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_bidirectional_results", return_value=[_result()]) as listing:
        response = client.get(_BASE, params={"limit": 10})
    assert response.status_code == 200, response.text
    assert listing.call_args.args[1:] == (_TENANT, 10)
    body = response.json()
    assert body["limit"] == 10
    [entry] = body["comparisons"]
    assert entry["id"] == _RESULT_ID
    assert entry["consumer"] == {"name": "Billing Service", "slug": "billing-service", "version": "2.0.0"}
    assert entry["provider"]["version"] == "5.1.0" and entry["provider"]["branch"] == "main"
    assert entry["verdict"] == "partial" and entry["strength"] == "partial"
    assert entry["statement"].startswith("Passed, but not everything was compared")
    assert entry["summary"]["couldNotCompare"] == 1
    assert entry["fidelityPath"] == f"{_BASE}/{_RESULT_ID}/fidelity"
    assert "interactions" not in entry


@pytest.mark.parametrize("limit", [0, MAX_BIDIRECTIONAL_LIST + 1])
def test_the_limit_is_bounded(allowed: MagicMock, limit: int) -> None:
    with patch(f"{_ROUTES}.list_bidirectional_results") as listing:
        response = client.get(_BASE, params={"limit": limit})
    assert response.status_code == 422
    listing.assert_not_called()


def test_an_empty_workspace_lists_nothing(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_bidirectional_results", return_value=[]):
        assert client.get(_BASE).json() == {"comparisons": [], "limit": 50}


# --- the report -------------------------------------------------------------------------------


def test_the_report_names_the_result_and_every_check(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_bidirectional_result", return_value=_result()) as reading:
        response = client.get(f"{_BASE}/{_RESULT_ID}/fidelity")
    assert response.status_code == 200, response.text
    assert reading.call_args.args[1:] == (_TENANT, _RESULT_ID)
    body = response.json()
    assert body["result"]["pactVersionSha"] == "ab" * 32
    assert body["strength"] == "partial"
    [interaction] = body["interactions"]
    assert {check["check"]: check["status"] for check in interaction["checks"]}["response.body"] == "partial"
    assert [note["code"] for note in interaction["couldNotCompare"]] == ["oneof-relaxed"]


def test_an_unknown_foreign_or_native_result_is_a_404_with_the_reason(allowed: MagicMock) -> None:
    refusal = PactPublicationError(
        CODE_VERIFICATION_NOT_FOUND, "verification result 'x' was published by a Pact verifier"
    )
    with patch(f"{_ROUTES}.get_bidirectional_result", side_effect=refusal):
        response = client.get(f"{_BASE}/{_RESULT_ID}/fidelity")
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": CODE_VERIFICATION_NOT_FOUND,
        "message": "verification result 'x' was published by a Pact verifier",
    }


# --- the store reads --------------------------------------------------------------------------


class _FakeDb:
    """Records the one query and answers with ``rows``."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: List[Any] = []

    def execute_query(self, sql: str, params: Any) -> List[Dict[str, Any]]:
        self.calls.append((sql, params))
        return self.rows


def _row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": _RESULT_ID,
        "number": 1,
        "success": True,
        "consumer_slug": "billing-service",
        "consumer_name": "Billing Service",
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "provider_version": "5.1.0",
        "sha": "ab" * 32,
        "kind": "bidirectional",
        "comparison": _comparison("pass-01-get-invoice-v2"),
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(("asked", "bounded"), [(10, 10), (0, 1), (10_000, MAX_BIDIRECTIONAL_LIST)])
def test_the_list_query_is_tenant_scoped_bidirectional_and_bounded(asked: int, bounded: int) -> None:
    fake = _FakeDb([_row()])
    [record] = list_bidirectional_results(fake, _TENANT, asked)
    sql, params = fake.calls[0]
    assert "r.tenant_id = %s::uuid AND r.kind = 'bidirectional' ORDER BY r.seq DESC LIMIT %s" in sql
    assert params == (_TENANT, bounded)
    assert record.kind == "bidirectional"


def test_a_result_is_read_by_id_within_the_tenant() -> None:
    fake = _FakeDb([_row()])
    record = get_bidirectional_result(fake, _TENANT, _RESULT_ID)
    sql, params = fake.calls[0]
    assert "r.id = %s::uuid AND r.tenant_id = %s::uuid" in sql
    assert params == (_RESULT_ID, _TENANT)
    assert record.comparison is not None


def test_a_malformed_id_is_not_found_without_a_query() -> None:
    fake = _FakeDb([])
    with pytest.raises(PactPublicationError) as caught:
        get_bidirectional_result(fake, _TENANT, "not-a-uuid")
    assert caught.value.code == CODE_VERIFICATION_NOT_FOUND
    assert fake.calls == []


def test_an_id_of_another_tenant_is_not_found() -> None:
    with pytest.raises(PactPublicationError) as caught:
        get_bidirectional_result(_FakeDb([]), _TENANT, _RESULT_ID)
    assert caught.value.code == CODE_VERIFICATION_NOT_FOUND
    assert "this workspace has no bi-directional result" in str(caught.value)


def test_a_native_result_has_no_report() -> None:
    fake = _FakeDb([_row(kind="native", comparison=None)])
    with pytest.raises(PactPublicationError) as caught:
        get_bidirectional_result(fake, _TENANT, _RESULT_ID)
    assert "published by a Pact verifier" in str(caught.value)
