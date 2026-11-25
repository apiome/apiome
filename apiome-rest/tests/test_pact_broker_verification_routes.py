"""HTTP contract tests for verification results — PFX-1.4 (#6917).

The routes of :mod:`app.pact_broker_verification_routes`, with the store faked
(``test_verification_result_db`` runs them against the real schema):

* publishing needs ``pacts:create`` and reading ``pacts:view``; a denial is a 403 before the
  store is touched;
* a publish answers ``201`` with ``Location`` and the result in the Pact Broker's shape;
* the for-verification form of the URL passes the pending and WIP flags of its metadata on;
* refusals map to their status: 422 with a pointer for a malformed body or an unknown report,
  404 for an unknown pact version or result;
* the provider's branch and tag are recorded through ``PUT`` routes;
* the pact and the pacticipant documents carry the links a Pact verifier follows.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError, PactRecord
from app.pact_selectors import encode_metadata
from app.pacticipant import (
    PacticipantRecord,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
)
from app.verification_result import (
    CODE_REPORT_NOT_FOUND,
    CODE_VERIFICATION_NOT_FOUND,
    VerificationResultRecord,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_SHA = "ab" * 32
_PAIR = f"{_BASE}/pacts/provider/ledger-api/consumer/billing-service"
_RESULTS = f"{_PAIR}/pact-version/{_SHA}/verification-results"
_PACT_VERSION_URL = f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}"
_ROUTES = "app.pact_broker_verification_routes"
_REPORT = "00000000-0000-4000-8000-0000000000aa"

_BODY = {
    "success": False,
    "providerApplicationVersion": "4f1e2d0",
    "buildUrl": "https://ci.example.com/builds/77",
    "testResults": [{"interactionId": "a1", "success": False, "mismatches": [{"attribute": "status"}]}],
    "verifiedBy": {"implementation": "Pact-Rust", "version": "1.2.0"},
}


def _result(**overrides: Any) -> VerificationResultRecord:
    payload: Dict[str, Any] = {
        "id": "r-1",
        "number": 1,
        "consumer_slug": "billing-service",
        "consumer_name": "Billing Service",
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "provider_version": "4f1e2d0",
        "consumer_version": "1.0.0",
        "sha": _SHA,
        "success": False,
        "build_url": "https://ci.example.com/builds/77",
        "provider_branch": "main",
        "test_results": _BODY["testResults"],
        "verified_by": {
            "implementation": "Pact-Rust",
            "version": "1.2.0",
            "client_implementation": None,
            "client_version": None,
            "client_test_framework": None,
        },
        "created_at": "2026-11-24T10:00:00+00:00",
    }
    payload.update(overrides)
    return VerificationResultRecord(**payload)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    """Every permission granted, in both broker route modules."""
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce,
        patch("app.pact_broker_routes.enforce_permission", return_value="test-user-id"),
    ):
        yield enforce


# --- RBAC --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "action"),
    [
        ("post", _RESULTS, "create"),
        ("post", f"{_PAIR}/pact-version/{_SHA}/metadata/czpbXQ/verification-results", "create"),
        ("get", f"{_RESULTS}/latest", "view"),
        ("get", f"{_RESULTS}/1", "view"),
        ("put", f"{_BASE}/pacticipants/ledger-api/branches/main/versions/4f1e2d0", "create"),
        ("put", f"{_BASE}/pacticipants/ledger-api/versions/4f1e2d0/tags/prod", "create"),
    ],
)
def test_every_route_is_gated_on_pacts(method: str, path: str, action: str) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
        patch(f"{_ROUTES}.publish_verification_result") as publish,
        patch(f"{_ROUTES}.get_latest_verification_result") as latest,
        patch(f"{_ROUTES}.record_broker_version") as record,
    ):
        kwargs = {"json": _BODY} if method in ("post", "put") else {}
        response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == ("pacts", action)
    publish.assert_not_called()
    latest.assert_not_called()
    record.assert_not_called()


# --- bi-directional results (PFX-2.3) ---------------------------------------------------------


def test_a_bidirectional_result_reads_back_with_its_comparison_and_contract(allowed: MagicMock) -> None:
    comparison = {"verdict": "fail", "success": False, "providerContractSha": "cd" * 32, "interactions": []}
    result = _result(
        kind="bidirectional",
        comparison=comparison,
        build_url=None,
        verified_by={"implementation": "Apiome bi-directional comparison"},
    )
    with patch(f"{_ROUTES}.get_verification_result", return_value=result):
        response = client.get(f"{_RESULTS}/1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "bidirectional"
    assert body["comparison"] == comparison
    assert body["verifiedBy"] == {"implementation": "Apiome bi-directional comparison"}
    assert body["_links"]["pb:provider-contract"] == {
        "title": "Provider contract",
        "name": "Ledger API 4f1e2d0",
        "href": f"{_ROOT}/contracts/provider/ledger-api/version/4f1e2d0",
    }
    # PFX-2.5 (#6929): the result links its fidelity report.
    assert body["_links"]["apiome:comparison-fidelity"] == {
        "title": "Comparison fidelity report (Apiome)",
        "href": "http://testserver/v1/tenants/acme/pact-comparisons/r-1/fidelity",
    }


def test_a_native_result_has_no_comparison(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_verification_result", return_value=_result()):
        body = client.get(f"{_RESULTS}/1").json()
    assert body["kind"] == "native"
    assert "comparison" not in body and "pb:provider-contract" not in body["_links"]
    assert "apiome:comparison-fidelity" not in body["_links"]


def test_a_verifier_cannot_publish_a_bidirectional_result(allowed: MagicMock) -> None:
    # `kind` and `comparison` are Apiome's to write: a verifier's body cannot set them.
    with patch(f"{_ROUTES}.publish_verification_result", return_value=_result()) as publish:
        response = client.post(_RESULTS, json={**_BODY, "kind": "bidirectional", "comparison": {"verdict": "pass"}})
    assert response.status_code == 201, response.text
    assert not hasattr(publish.call_args.args[5], "kind")
    assert response.json()["kind"] == "native"


# --- publishing --------------------------------------------------------------------------------


def test_a_result_is_published_in_the_brokers_shape(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.publish_verification_result", return_value=_result()) as publish:
        response = client.post(_RESULTS, json=_BODY)
    assert response.status_code == 201, response.text
    assert response.headers["content-type"].startswith("application/hal+json")
    assert response.headers["location"] == f"{_PACT_VERSION_URL}/verification-results/1"
    args, kwargs = publish.call_args
    assert args[1:5] == (_TENANT, "ledger-api", "billing-service", _SHA)
    assert args[5].success is False and args[5].test_results == _BODY["testResults"]
    assert kwargs["pact_pending"] is None and kwargs["wip"] is False
    assert kwargs["actor"].user_id == "test-user-id"
    assert response.json() == {
        "providerName": "Ledger API",
        "providerApplicationVersion": "4f1e2d0",
        "success": False,
        "verificationDate": "2026-11-24T10:00:00+00:00",
        "buildUrl": "https://ci.example.com/builds/77",
        "providerVersionBranch": "main",
        "testResults": _BODY["testResults"],
        "verifiedBy": {"implementation": "Pact-Rust", "version": "1.2.0"},
        "kind": "native",
        "_links": {
            "self": {
                "title": "Verification result",
                "name": "Verification result 1 for Pact between Billing Service (1.0.0) and Ledger API",
                "href": f"{_PACT_VERSION_URL}/verification-results/1",
            },
            "pb:pact-version": {
                "title": "Pact",
                "name": "Pact between Billing Service (1.0.0) and Ledger API",
                "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}",
            },
            "pb:triggered-webhooks": {
                "title": "Webhooks triggered by the publication of this verification result",
                "href": f"{_PACT_VERSION_URL}/verification-results/1/triggered-webhooks",
            },
        },
    }


def test_the_metadata_form_records_the_pending_and_wip_flags(allowed: MagicMock) -> None:
    pending = encode_metadata({"s": [{"b": "main", "l": True, "cv": "v1"}], "p": True})
    wip = encode_metadata({"w": True})
    with patch(f"{_ROUTES}.publish_verification_result", return_value=_result()) as publish:
        assert (
            client.post(f"{_PAIR}/pact-version/{_SHA}/metadata/{pending}/verification-results", json=_BODY).status_code
            == 201
        )
        assert publish.call_args.kwargs["pact_pending"] is True
        assert (
            client.post(f"{_PAIR}/pact-version/{_SHA}/metadata/{wip}/verification-results", json=_BODY).status_code
            == 201
        )
        assert publish.call_args.kwargs["wip"] is True


def test_a_linked_report_is_a_link_not_a_copy(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.publish_verification_result", return_value=_result(report_id=_REPORT)) as publish:
        response = client.post(_RESULTS, json={**_BODY, "providerVerificationReportId": _REPORT})
    assert publish.call_args.args[5].report_id == _REPORT
    assert response.json()["_links"]["pb:provider-verification-report"] == {
        "title": "Provider verification report (Apiome)",
        "href": f"http://testserver/v1/tenants/acme/provider-verifications/{_REPORT}",
    }


def test_a_malformed_body_is_a_located_422_before_the_store(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.publish_verification_result") as publish:
        response = client.post(_RESULTS, json={"success": "yes", "providerApplicationVersion": "1"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-verification-invalid"
    assert response.json()["detail"]["pointer"] == "/success"
    publish.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_PACT_NOT_FOUND, "no pact version"), 404),
        (PactPublicationError(CODE_REPORT_NOT_FOUND, "no report", pointer="/providerVerificationReportId"), 422),
    ],
)
def test_store_refusals_keep_their_status(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.publish_verification_result", side_effect=error):
        response = client.post(_RESULTS, json=_BODY)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code


# --- reading -----------------------------------------------------------------------------------


def test_the_latest_and_a_numbered_result_read_back(allowed: MagicMock) -> None:
    with (
        patch(f"{_ROUTES}.get_latest_verification_result", return_value=_result(number=3)) as latest,
        patch(f"{_ROUTES}.get_verification_result", return_value=_result(number=2)) as numbered,
    ):
        assert client.get(f"{_RESULTS}/latest").json()["_links"]["self"]["href"].endswith("/verification-results/3")
        assert client.get(f"{_RESULTS}/2").json()["_links"]["self"]["href"].endswith("/verification-results/2")
    assert latest.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", _SHA)
    assert numbered.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", _SHA, 2)


def test_a_missing_result_is_a_404_and_a_bad_number_a_422(allowed: MagicMock) -> None:
    missing = PactPublicationError(CODE_VERIFICATION_NOT_FOUND, "no results")
    with patch(f"{_ROUTES}.get_latest_verification_result", side_effect=missing):
        response = client.get(f"{_RESULTS}/latest")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_VERIFICATION_NOT_FOUND
    assert client.get(f"{_RESULTS}/0").status_code == 422
    assert client.get(f"{_RESULTS}/first").status_code == 422


# --- provider branch and tags ------------------------------------------------------------------


def _recorded(created: bool) -> tuple:
    provider = PacticipantRecord(id="p-1", tenant_id=_TENANT, slug="ledger-api", name="Ledger API")
    version = PacticipantVersionRecord(
        id="v-1", pacticipant_id="p-1", number="4f1e2d0", seq=1, branches=["feat/x"], tags=["prod"]
    )
    return provider, RecordedPacticipantVersion(version=version, created=created, head_moved=created)


def test_a_branch_version_is_recorded(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.record_broker_version", return_value=_recorded(True)) as record:
        response = client.put(f"{_BASE}/pacticipants/ledger-api/branches/feat/x/versions/4f1e2d0", json={})
    assert response.status_code == 201
    assert record.call_args.args[1:4] == (_TENANT, "ledger-api", "4f1e2d0")
    assert record.call_args.kwargs["branch"] == "feat/x" and record.call_args.kwargs["tags"] == []
    assert response.json()["_links"]["self"]["href"] == f"{_ROOT}/pacticipants/ledger-api/versions/4f1e2d0"


def test_a_version_tag_is_recorded(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.record_broker_version", return_value=_recorded(False)) as record:
        response = client.put(f"{_BASE}/pacticipants/ledger-api/versions/4f1e2d0/tags/prod", content=b"{}")
    assert response.status_code == 200
    assert record.call_args.kwargs["tags"] == ["prod"] and record.call_args.kwargs["branch"] is None


# --- the links a verifier follows --------------------------------------------------------------


def _pact() -> PactRecord:
    return PactRecord(
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        provider_slug="ledger-api",
        provider_name="Ledger API",
        consumer_version="1.0.0",
        sha=_SHA,
        content={"interactions": []},
    )


def test_a_pact_links_to_where_its_results_are_published(allowed: MagicMock) -> None:
    with patch("app.pact_broker_routes.get_pact_by_sha", return_value=_pact()):
        plain = client.get(f"{_PAIR}/pact-version/{_SHA}").json()["_links"]
        metadata = encode_metadata({"p": True})
        via_link = client.get(f"{_PAIR}/pact-version/{_SHA}/metadata/{metadata}").json()["_links"]
    pact_version = f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}"
    assert plain["pb:publish-verification-results"] == {
        "title": "Publish verification results",
        "href": f"{pact_version}/verification-results",
    }
    assert via_link["pb:publish-verification-results"]["href"] == (
        f"{pact_version}/metadata/{metadata}/verification-results"
    )
    assert plain["pb:latest-verification-results"]["href"] == f"{pact_version}/verification-results/latest"


def test_a_pacticipant_links_to_its_branch_and_tag_templates(allowed: MagicMock) -> None:
    provider = PacticipantRecord(id="p-1", tenant_id=_TENANT, slug="ledger-api", name="Ledger API")
    with patch("app.pact_broker_routes.get_pacticipant", return_value=provider):
        links = client.get(f"{_BASE}/pacticipants/ledger-api").json()["_links"]
    assert links["pb:branch-version"] == {
        "title": "Get or add/create a version for a branch of this pacticipant",
        "href": f"{_ROOT}/pacticipants/ledger-api/branches/{{branch}}/versions/{{version}}",
        "templated": True,
    }
    assert links["pb:version-tag"]["href"] == f"{_ROOT}/pacticipants/ledger-api/versions/{{version}}/tags/{{tag}}"
    assert json.dumps(links)  # serialisable as sent
