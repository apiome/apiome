"""HTTP contract and unit tests for the provider-contract pre-publish check — PFX-8.6 (#7303).

``POST /v1/tenants/{t}/pact-broker/contracts/provider/{p}/version/{v}/check``. The comparison is
faked here (``test_provider_contract_check_db`` runs it against the real schema); what is asserted
is the endpoint's own contract and :mod:`app.provider_contract_check`'s report:

* the check is gated on ``pacts:view`` (``versions:view`` too with ``apiomeVersion``), denied
  before anything is read, and budgeted with the pact check;
* inline content, ``contentUrl`` (read once, echoed back in ``fetched``) and the refusals —
  an unreadable document with its pointer, a URL that cannot be read, both a URL and content;
* ``tags`` / ``buildUrl`` are named in ``ignored``, never silently dropped;
* the report: per-pact failures, operations no pact uses, a conflicting earlier contract, an
  unknown provider, AsyncAPI coverage left out with its reason.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.bidirectional_store import PreviewEntry
from app.bidirectional_verification import StoredComparison
from app.config import settings
from app.import_source import ImportSourceError
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_check_routes import _check_limiter
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Resource
from app.provider_contract import (
    CODE_CONTRACT_NOT_FOUND,
    CODE_URL_UNREADABLE,
    ProviderContractError,
    ProviderContractRecord,
    prepare_contract,
)
from app.provider_contract_check import (
    MAX_FAILURES_PER_PACT,
    FetchedContract,
    fetch_contract_url,
    run_contract_check,
)
from app.provider_contract_evidence import missing_evidence

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_URL = "/v1/tenants/acme/pact-broker/contracts/provider/ledger-api/version/1.4.0/check"
_ROUTES = "app.provider_contract_check_routes"
_CHECK = "app.provider_contract_check"
_FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"


def _oas() -> Dict[str, Any]:
    return json.loads((_FIXTURES / "ledger-api-3.1.json").read_bytes())


def _b64(document: Any) -> str:
    return base64.b64encode(json.dumps(document).encode()).decode()


@pytest.fixture(autouse=True)
def authenticated() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    _check_limiter._windows.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce,
        patch("app.provider_contract_routes.enforce_permission", return_value="test-user-id"),
    ):
        yield enforce


@pytest.fixture
def no_provider() -> Iterator[MagicMock]:
    """The provider is not registered: nothing to compare with."""
    with patch(
        f"{_CHECK}.get_pacticipant", side_effect=PacticipantValidationError(CODE_NOT_FOUND, "no such pacticipant")
    ) as lookup:
        yield lookup


# --- the route -----------------------------------------------------------------------------------


class TestRoute:
    def test_a_check_without_pacts_view_is_refused_before_anything_is_read(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=HTTPException(status_code=403, detail="no")) as enforce,
            patch(f"{_ROUTES}.run_contract_check") as run,
        ):
            response = client.post(_URL, json={"content": _b64(_oas())})
        assert response.status_code == 403
        assert enforce.call_args.args[2] == Resource.PACTS
        run.assert_not_called()

    def test_an_inline_contract_is_checked_and_reported(self, allowed: MagicMock, no_provider: MagicMock) -> None:
        response = client.post(_URL, json={"content": _b64(_oas()), "branch": "main"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == {"name": "ledger-api", "exists": False}
        assert body["providerVersion"] == "1.4.0"
        assert body["contract"]["contractType"] == "oas"
        assert body["contract"]["oasVersion"] == "3.1.0"
        assert body["contract"]["operationCount"] == 1
        assert body["selfVerification"]["status"] == "missing"
        assert body["selfVerification"]["providerContractVerified"] is False
        assert body["results"] == []
        assert body["summary"]["publishable"] is True
        assert body["coverage"]["unused"] == [{"method": "GET", "path": "/invoices/{id}", "operationId": "getInvoice"}]
        assert "ignored" not in body

    def test_an_apiome_version_needs_versions_view(self, no_provider: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", return_value="u"),
            patch(
                "app.provider_contract_routes.enforce_permission",
                side_effect=HTTPException(status_code=403, detail="versions"),
            ) as versions,
        ):
            response = client.post(_URL, json={"apiomeVersion": "ledger-api@1.4.0"})
        assert response.status_code == 403
        assert versions.call_args.args[2] == Resource.VERSIONS

    def test_an_unreadable_document_is_a_422_with_its_pointer(self, allowed: MagicMock) -> None:
        response = client.post(_URL, json={"content": _b64({"swagger": "2.0"})})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "provider-contract-invalid"
        assert detail["pointer"] == "/swagger"

    def test_a_url_is_read_once_and_its_bytes_come_back(self, allowed: MagicMock, no_provider: MagicMock) -> None:
        raw = json.dumps(_oas()).encode()
        fetched = FetchedContract(url="https://api.example.com/openapi.json", raw=raw)
        with patch(f"{_ROUTES}.fetch_contract_url", return_value=fetched) as fetch:
            response = client.post(_URL, json={"contentUrl": " https://api.example.com/openapi.json "})
        assert response.status_code == 200, response.text
        assert fetch.call_args.args == ("https://api.example.com/openapi.json",)
        assert fetch.call_args.kwargs == {"max_bytes": settings.pact_max_bytes}
        assert response.json()["fetched"] == {
            "url": "https://api.example.com/openapi.json",
            "bytes": len(raw),
            "content": base64.b64encode(raw).decode(),
        }

    def test_a_url_that_cannot_be_read_is_a_422(self, allowed: MagicMock) -> None:
        refusal = ProviderContractError(CODE_URL_UNREADABLE, "could not read it: 404", pointer="/contentUrl")
        with patch(f"{_ROUTES}.fetch_contract_url", side_effect=refusal):
            response = client.post(_URL, json={"contentUrl": "https://api.example.com/missing.yaml"})
        assert response.status_code == 422
        assert response.json()["detail"] == {
            "code": CODE_URL_UNREADABLE,
            "message": "could not read it: 404",
            "pointer": "/contentUrl",
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"contentUrl": "https://a.example.com/x.yaml", "content": "e30="},
            {"contentUrl": "https://a.example.com/x.yaml", "apiomeVersion": "a@1"},
            {"contentUrl": 7},
        ],
    )
    def test_a_url_with_another_source_or_not_a_string_is_refused(
        self, allowed: MagicMock, body: Dict[str, Any]
    ) -> None:
        with patch(f"{_ROUTES}.fetch_contract_url") as fetch:
            response = client.post(_URL, json=body)
        assert response.status_code == 422
        assert response.json()["detail"]["pointer"] == "/contentUrl"
        fetch.assert_not_called()

    def test_a_body_that_is_not_json_is_refused(self, allowed: MagicMock) -> None:
        response = client.post(_URL, content=b"not json", headers={"content-type": "application/json"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "provider-contract-request-invalid"

    def test_fields_a_check_does_not_use_are_named(self, allowed: MagicMock, no_provider: MagicMock) -> None:
        response = client.post(
            _URL, json={"content": _b64(_oas()), "tags": ["prod"], "buildUrl": "https://ci.example.com/1"}
        )
        assert response.status_code == 200, response.text
        assert [entry["field"] for entry in response.json()["ignored"]] == ["tags", "buildUrl"]

    def test_checks_share_the_pact_check_budget(
        self, allowed: MagicMock, no_provider: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "pact_check_rate_limit_per_minute", 1)
        assert client.post(_URL, json={"content": _b64(_oas())}).status_code == 200
        response = client.post(_URL, json={"content": _b64(_oas())})
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "pact-check-rate-limited"
        assert "Retry-After" in response.headers

    def test_the_route_is_in_the_openapi_document(self) -> None:
        paths = app.openapi()["paths"]
        assert (
            "post"
            in paths[
                "/v1/tenants/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}/check"
            ]
        )


# --- the report ----------------------------------------------------------------------------------


def _contract(document: Any = None):  # noqa: ANN202 - ProviderContractToStore
    return prepare_contract(document or _oas(), content_type="application/json")


def _comparison(success: bool, failures: int = 0) -> StoredComparison:
    interaction = {
        "description": "a request for an invoice",
        "operation": {"method": "get", "path": "/invoices/{id}"},
        "failures": [{"code": "response.body.type", "message": f"failure {n}"} for n in range(failures)],
    }
    payload = {"interactions": [interaction], "summary": {"interactions": 1}, "comparisonVerdict": "pass"}
    return StoredComparison(success=success, verdict="pass" if success else "fail", test_results=[], payload=payload)


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.id = "22222222-2222-4222-8222-222222222222"
    provider.name = "Ledger API"
    return provider


def _run(entries: Any, existing: Any = None, document: Any = None):  # noqa: ANN202 - CheckOutcome
    with (
        patch(f"{_CHECK}.get_pacticipant", return_value=_provider()),
        patch(f"{_CHECK}.preview_provider_contract", return_value=entries) as preview,
        patch(
            f"{_CHECK}.get_provider_contract",
            side_effect=existing or ProviderContractError(CODE_CONTRACT_NOT_FOUND, "none"),
        ),
    ):
        outcome = run_contract_check(
            MagicMock(),
            _TENANT,
            provider_ref="ledger-api",
            provider_version="1.4.0",
            branch="main",
            contract=_contract(document),
            evidence=missing_evidence(),
            self_verification={"status": "missing"},
        )
    return outcome, preview


class TestReport:
    def test_each_pact_reports_its_verdict_failures_and_environments(self) -> None:
        entries = [
            PreviewEntry(
                "Orders UI", "3.3.2", "ab" * 32, ("production",), _comparison(False, MAX_FAILURES_PER_PACT + 2)
            ),
            PreviewEntry("Mobile App", "5.1.0", "cd" * 32, (), _comparison(True)),
            PreviewEntry("Checkout", "1.0.0", "ef" * 32, (), None, "over the limit of 200 pacts compared per publish"),
        ]
        outcome, preview = _run(entries)
        target = preview.call_args.args[3]
        assert (target.branches, target.contract_sha) == (("main",), outcome.contract.sha)
        orders, mobile, checkout = outcome.to_dict()["results"]
        assert orders["success"] is False and orders["environments"] == ["production"]
        assert len(orders["failures"]) == MAX_FAILURES_PER_PACT and orders["moreFailures"] == 2
        assert orders["failures"][0] == {
            "interaction": "a request for an invoice",
            "operation": "GET /invoices/{id}",
            "code": "response.body.type",
            "message": "failure 0",
        }
        assert mobile["success"] is True and mobile["failures"] == []
        assert checkout["success"] is None and "over the limit" in checkout["reason"]
        summary = outcome.summary()
        assert (summary["compared"], summary["compatible"], summary["incompatible"], summary["notCompared"]) == (
            2,
            1,
            1,
            1,
        )
        assert outcome.coverage == {"operations": 1, "used": 1, "unused": [], "unusedMore": 0}

    def test_a_different_earlier_contract_makes_it_unpublishable(self) -> None:
        record = MagicMock(spec=ProviderContractRecord)
        record.sha = "00" * 32
        record.created_at = "2026-11-20T10:00:00+00:00"
        with (
            patch(f"{_CHECK}.get_pacticipant", return_value=_provider()),
            patch(f"{_CHECK}.preview_provider_contract", return_value=[]),
            patch(f"{_CHECK}.get_provider_contract", return_value=record),
        ):
            outcome = run_contract_check(
                MagicMock(),
                _TENANT,
                provider_ref="ledger-api",
                provider_version="1.4.0",
                branch=None,
                contract=_contract(),
                evidence=missing_evidence(),
                self_verification={},
            )
        assert outcome.existing == {"contentSha": "00" * 32, "sameContent": False, "createdAt": record.created_at}
        assert outcome.summary()["publishable"] is False

    def test_an_asyncapi_contract_has_no_coverage_and_says_why(self) -> None:
        asyncapi = {
            "asyncapi": "3.0.0",
            "info": {"title": "Orders", "version": "1.0.0"},
            "channels": {},
        }
        outcome, _ = _run([], document=asyncapi)
        payload = outcome.to_dict()
        assert payload["coverage"] is None
        assert "OpenAPI" in payload["coverageReason"]
        assert payload["contract"]["contractType"] == "asyncapi"

    def test_a_registry_refusal_other_than_not_found_is_raised(self) -> None:
        refusal = PacticipantValidationError("pacticipant-name-invalid", "bad name")
        with patch(f"{_CHECK}.get_pacticipant", side_effect=refusal), pytest.raises(PacticipantValidationError):
            run_contract_check(
                MagicMock(),
                _TENANT,
                provider_ref="!!",
                provider_version="1",
                branch=None,
                contract=_contract(),
                evidence=missing_evidence(),
                self_verification={},
            )


class TestFetch:
    def test_a_refused_or_unreachable_url_is_a_contract_error(self) -> None:
        with (
            patch(f"{_CHECK}.check_public_url"),
            patch(f"{_CHECK}.guarded_get", side_effect=ImportSourceError("HTTP 404 from the contract")),
            pytest.raises(ProviderContractError) as caught,
        ):
            fetch_contract_url("https://api.example.com/openapi.yaml", max_bytes=1000)
        assert caught.value.code == CODE_URL_UNREADABLE
        assert caught.value.pointer == "/contentUrl"
        assert "HTTP 404" in str(caught.value)

    def test_a_private_address_is_refused_before_any_request(self) -> None:
        with patch(f"{_CHECK}.guarded_get") as get, pytest.raises(ProviderContractError):
            fetch_contract_url("http://127.0.0.1/openapi.yaml", max_bytes=1000)
        get.assert_not_called()

    def test_the_bytes_read_are_returned(self) -> None:
        with patch(f"{_CHECK}.check_public_url"), patch(f"{_CHECK}.guarded_get", return_value="openapi: 3.1.0\n"):
            fetched = fetch_contract_url("https://api.example.com/openapi.yaml", max_bytes=1000)
        assert fetched.raw == b"openapi: 3.1.0\n"
        assert fetched.to_dict()["bytes"] == 15
