"""HTTP contract tests for provider contracts — PFX-2.1 (#6925).

``PUT|GET /v1/tenants/{t}/pact-broker/contracts/provider/{p}/version/{v}``. The store and the
Apiome renderer are faked (``test_provider_contract_db`` runs them against the real schema); what is
asserted here is the endpoint's own contract:

* publishing is gated on ``pacts:create`` — plus ``versions:view`` when it names an Apiome version —
  and reading on ``pacts:view``; a denial is a 403 before anything is parsed or stored;
* inline content (JSON or YAML, base64) and an Apiome reference both reach the store, as one
  validated, addressed contract;
* a refusal becomes the status of its kind — 422 with a pointer for a non-OpenAPI document or a
  malformed request, 409 for a different contract, 413 over the size limit, 404 for nothing to
  read — and always carries the stable code;
* the response shape, with links back to the base URL the client used.
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

from app.bidirectional_verification import ComparisonRun, RunEntry
from app.config import settings
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_routes import _publish_limiter
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Resource
from app.provider_contract import (
    CODE_CONTRACT_CONFLICT,
    CODE_CONTRACT_NOT_FOUND,
    CODE_SOURCE_NOT_FOUND,
    ApiomeReference,
    ProviderContractError,
    ProviderContractRecord,
    ProviderContractToStore,
    PublishedProviderContract,
)
from app.provider_contract_source import ResolvedSource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_URL = "/v1/tenants/acme/pact-broker/contracts/provider/ledger-api/version/1.4.0"
_ROUTES = "app.provider_contract_routes"
_FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _oas31() -> Dict[str, Any]:
    return json.loads((_FIXTURES / "ledger-api-3.1.json").read_bytes())


def _record(**overrides: Any) -> ProviderContractRecord:
    payload: Dict[str, Any] = {
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "provider_version": "1.4.0",
        "sha": "cd" * 32,
        "content": _oas31(),
        "oas_version": "3.1.0",
        "operation_count": 1,
        "content_type": "application/json",
        "created_at": "2026-11-24T10:00:00+00:00",
    }
    payload.update(overrides)
    return ProviderContractRecord(**payload)


def _published(*, created: bool = True, **overrides: Any) -> PublishedProviderContract:
    return PublishedProviderContract(contract=_record(**overrides), created=created, new_content=created)


@pytest.fixture(autouse=True)
def authenticated() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    _publish_limiter._windows.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


@pytest.fixture
def store() -> Iterator[MagicMock]:
    """The store stood in; the comparisons a publish runs (PFX-2.3) are an empty run."""
    with (
        patch(f"{_ROUTES}.publish_provider_contract", return_value=_published()) as publish,
        patch(f"{_ROUTES}.compare_provider_contract", return_value=ComparisonRun()),
    ):
        yield publish


class TestBidirectionalComparisons:
    def test_a_publish_reports_the_comparisons_it_ran(self, allowed: MagicMock, store: MagicMock) -> None:
        run = ComparisonRun(
            [
                RunEntry("Billing Service", "2.0.0", "Ledger API", "1.4.0", "ab" * 32, "compared", "pass", 1),
                RunEntry("Web", "0.3.0", "Ledger API", "1.4.0", "ef" * 32, "skipped", reason="over the limit"),
            ]
        )
        with patch(f"{_ROUTES}.compare_provider_contract", return_value=run) as compare:
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 201, response.text
        args, kwargs = compare.call_args
        assert args[1:] == (_TENANT, "ledger-api", "1.4.0")
        assert kwargs["actor"].user_id == "test-user-id"
        comparisons = response.json()["comparisons"]
        assert (comparisons["compared"], comparisons["skipped"]) == (1, 1)
        assert comparisons["results"][0] == {
            "consumer": "Billing Service",
            "consumerVersion": "2.0.0",
            "provider": "Ledger API",
            "providerVersion": "1.4.0",
            "pactVersionSha": "ab" * 32,
            "status": "compared",
            "verdict": "pass",
            "verificationNumber": 1,
        }

    def test_a_republish_still_reports_comparisons(self, allowed: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.publish_provider_contract", return_value=_published(created=False)),
            patch(f"{_ROUTES}.compare_provider_contract", return_value=ComparisonRun()) as compare,
        ):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 200
        compare.assert_called_once()
        assert response.json()["comparisons"]["results"] == []

    def test_a_refused_publish_compares_nothing(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny("pacts")),
            patch(f"{_ROUTES}.publish_provider_contract") as publish,
            patch(f"{_ROUTES}.compare_provider_contract") as compare,
        ):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 403
        publish.assert_not_called()
        compare.assert_not_called()

    def test_an_invalid_contract_compares_nothing(self, allowed: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.publish_provider_contract") as publish,
            patch(f"{_ROUTES}.compare_provider_contract") as compare,
        ):
            response = client.put(_URL, json={"content": _b64(b'{"swagger": "2.0"}')})
        assert response.status_code == 422
        publish.assert_not_called()
        compare.assert_not_called()


def _stored_contract(store: MagicMock) -> ProviderContractToStore:
    return store.call_args.kwargs["contract"]


def _deny(denied: str) -> Any:
    """An ``enforce_permission`` that refuses one resource."""

    def enforce(_db: Any, _auth: Any, resource: str, action: str, **_kwargs: Any) -> str:
        if resource == denied:
            raise HTTPException(status_code=403, detail=f"Missing permission: {resource}:{action}")
        return "test-user-id"

    return enforce


# ---------------------------------------------------------------------------------------------
# Publishing inline
# ---------------------------------------------------------------------------------------------


class TestPublishInline:
    def test_a_new_contract_is_201_with_its_document_and_links(self, allowed: MagicMock, store: MagicMock) -> None:
        response = client.put(
            _URL, json={"content": _b64(json.dumps(_oas31()).encode()), "contentType": "application/json"}
        )
        assert response.status_code == 201
        assert response.headers["content-type"].startswith("application/hal+json")
        body = response.json()
        assert body["provider"] == {"name": "Ledger API"}
        assert (body["providerVersion"], body["contractType"], body["oasVersion"]) == ("1.4.0", "oas", "3.1.0")
        assert body["contentSha"] == "cd" * 32
        assert body["source"] == {"kind": "inline"}
        assert body["content"]["info"]["title"] == "Ledger API"
        links = body["_links"]
        assert links["self"]["href"] == f"{_ROOT}/contracts/provider/ledger-api/version/1.4.0"
        assert links["pb:provider"]["href"] == f"{_ROOT}/pacticipants/ledger-api"
        assert links["pb:provider-version"]["href"] == f"{_ROOT}/pacticipants/ledger-api/versions/1.4.0"

    def test_the_store_receives_the_validated_addressed_contract_and_version_details(
        self, allowed: MagicMock, store: MagicMock
    ) -> None:
        raw = (_FIXTURES / "ledger-api-3.0.yaml").read_bytes()
        client.put(
            _URL,
            json={
                "content": _b64(raw),
                "contentType": "application/yaml",
                "branch": "main",
                "tags": ["rc"],
                "buildUrl": "https://ci.example.com/4813",
                "verificationResults": {"success": True, "verifier": "schemathesis"},
            },
        )
        kwargs = store.call_args.kwargs
        assert (kwargs["provider_name"], kwargs["version_number"]) == ("ledger-api", "1.4.0")
        assert (kwargs["branch"], kwargs["tags"], kwargs["build_url"]) == (
            "main",
            ["rc"],
            "https://ci.example.com/4813",
        )
        contract = _stored_contract(store)
        assert (contract.oas_version, contract.content_type, contract.operation_count) == (
            "3.0.3",
            "application/yaml",
            2,
        )
        assert contract.source == "inline"
        assert contract.verification_results is not None and contract.verification_results["success"] is True
        assert kwargs["actor"].user_id == "test-user-id"

    def test_a_republish_of_the_same_contract_is_200(self, allowed: MagicMock) -> None:
        with patch(f"{_ROUTES}.publish_provider_contract", return_value=_published(created=False)):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 200

    def test_a_different_contract_for_the_version_is_409(self, allowed: MagicMock) -> None:
        conflict = ProviderContractError(CODE_CONTRACT_CONFLICT, "fixed once published")
        with patch(f"{_ROUTES}.publish_provider_contract", side_effect=conflict):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == CODE_CONTRACT_CONFLICT

    def test_swagger_20_is_422_located_at_swagger_and_nothing_is_stored(
        self, allowed: MagicMock, store: MagicMock
    ) -> None:
        raw = (_FIXTURES / "swagger-2.0.json").read_bytes()
        response = client.put(_URL, json={"content": _b64(raw)})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert (detail["code"], detail["pointer"]) == ("provider-contract-invalid", "/swagger")
        store.assert_not_called()

    def test_a_meta_schema_error_is_422_with_its_pointer(self, allowed: MagicMock, store: MagicMock) -> None:
        document = _oas31()
        del document["info"]["title"]
        response = client.put(_URL, json={"content": _b64(json.dumps(document).encode())})
        assert response.status_code == 422
        assert response.json()["detail"]["pointer"] == "/info"
        store.assert_not_called()

    @pytest.mark.parametrize(
        "body, code, pointer",
        [
            ({}, "provider-contract-request-invalid", ""),
            ({"content": "e30=", "apiomeVersion": "ledger@1"}, "provider-contract-request-invalid", ""),
            ({"content": "not base64!"}, "provider-contract-request-invalid", "/content"),
            ({"content": "e30=", "contractType": "pact"}, "provider-contract-unsupported", "/contractType"),
            ({"content": "e30=", "contentType": "text/xml"}, "provider-contract-unsupported", "/contentType"),
            ({"content": "e30=", "tags": "rc"}, "provider-contract-request-invalid", "/tags"),
            (
                {"content": "e30=", "verificationResults": {}},
                "provider-contract-request-invalid",
                "/verificationResults/success",
            ),
            (
                {"content": "e30=", "verificationResults": {"success": True, "content": "%%"}},
                "provider-contract-request-invalid",
                "/verificationResults/content",
            ),
        ],
        ids=[
            "no-source",
            "two-sources",
            "bad-base64",
            "pact-type",
            "xml",
            "tags-not-list",
            "results-no-success",
            "results-bad-b64",
        ],
    )
    def test_a_malformed_request_is_422_located_in_the_body(
        self, allowed: MagicMock, store: MagicMock, body: Dict[str, Any], code: str, pointer: str
    ) -> None:
        response = client.put(_URL, json=body)
        assert response.status_code == 422
        assert (response.json()["detail"]["code"], response.json()["detail"]["pointer"]) == (code, pointer)
        store.assert_not_called()

    def test_a_body_that_is_not_json_is_422(self, allowed: MagicMock, store: MagicMock) -> None:
        response = client.put(_URL, content=b"openapi: 3.1.0", headers={"content-type": "application/yaml"})
        assert response.status_code == 422
        store.assert_not_called()

    def test_a_body_over_the_limit_is_413(self, allowed: MagicMock, store: MagicMock) -> None:
        with patch.object(settings, "pact_max_bytes", 100):
            response = client.put(_URL, json={"content": "A" * 400})
        assert response.status_code == 413
        store.assert_not_called()

    def test_a_document_over_the_limit_is_413(self, allowed: MagicMock, store: MagicMock) -> None:
        with patch.object(settings, "pact_max_bytes", 120):
            response = client.put(_URL, json={"content": _b64(b"{" + b" " * 150 + b"}")})
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "provider-contract-too-large"

    def test_a_malformed_version_number_is_the_registry_400(self, allowed: MagicMock) -> None:
        refusal = PacticipantValidationError("pacticipant-invalid-version", "bad version")
        with patch(f"{_ROUTES}.publish_provider_contract", side_effect=refusal):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 400

    def test_publishing_counts_against_the_workspace_budget(self, allowed: MagicMock, store: MagicMock) -> None:
        body = {"content": _b64(json.dumps(_oas31()).encode())}
        with (
            patch.object(settings, "rate_limit_enabled", True),
            patch.object(settings, "pact_publish_rate_limit_per_minute", 1),
        ):
            assert client.put(_URL, json=body).status_code == 201
            limited = client.put(_URL, json=body)
        assert limited.status_code == 429
        assert limited.headers.get("retry-after")


# ---------------------------------------------------------------------------------------------
# Publishing by reference
# ---------------------------------------------------------------------------------------------


_SOURCE = ResolvedSource(project_id="p-1", project_slug="ledger-api", version_id="v-1", version_label="1.4.0")


class TestPublishByReference:
    def test_the_reference_is_resolved_rendered_and_stored(self, allowed: MagicMock, store: MagicMock) -> None:
        rendered = MagicMock(**{"json.return_value": _oas31()})
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE) as resolve,
            patch("app.provider_contract_source.rendered_document", return_value=rendered) as render,
        ):
            response = client.put(_URL, json={"apiomeVersion": "ledger-api@1.4.0", "branch": "main"})
        assert response.status_code == 201
        assert resolve.call_args.args[1:] == (_TENANT, "ledger-api", ApiomeReference("ledger-api", "1.4.0"))
        assert render.call_args.args == ("v-1", "openapi")
        assert render.call_args.kwargs["tenant_id"] == _TENANT
        contract = _stored_contract(store)
        assert (contract.source, contract.source_project_slug, contract.source_version_label) == (
            "apiome",
            "ledger-api",
            "1.4.0",
        )
        assert (contract.source_project_id, contract.source_version_id, contract.content_type) == (
            "p-1",
            "v-1",
            "application/json",
        )

    def test_a_reference_also_needs_versions_view(self, store: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.VERSIONS)),
            patch(f"{_ROUTES}.resolve_apiome_source") as resolve,
        ):
            response = client.put(_URL, json={"apiomeVersion": "ledger-api@1.4.0"})
        assert response.status_code == 403
        resolve.assert_not_called()
        store.assert_not_called()

    def test_inline_content_does_not_need_versions_view(self, store: MagicMock) -> None:
        with patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.VERSIONS)):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.status_code == 201

    def test_an_unknown_source_is_422_at_apiome_version(self, allowed: MagicMock, store: MagicMock) -> None:
        missing = ProviderContractError(CODE_SOURCE_NOT_FOUND, "no project 'nope'", pointer="/apiomeVersion")
        with patch(f"{_ROUTES}.resolve_apiome_source", side_effect=missing):
            response = client.put(_URL, json={"apiomeVersion": "nope@1"})
        assert response.status_code == 422
        assert response.json()["detail"] == {
            "code": CODE_SOURCE_NOT_FOUND,
            "message": "no project 'nope'",
            "pointer": "/apiomeVersion",
        }
        store.assert_not_called()

    def test_a_rendered_document_that_does_not_validate_is_422_naming_the_source(
        self, allowed: MagicMock, store: MagicMock
    ) -> None:
        rendered = MagicMock(**{"json.return_value": {"openapi": "3.1.0"}})
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE),
            patch("app.provider_contract_source.rendered_document", return_value=rendered),
        ):
            response = client.put(_URL, json={"apiomeVersion": "ledger-api@1.4.0"})
        assert response.status_code == 422
        assert "rendered from ledger-api@1.4.0" in response.json()["detail"]["message"]
        store.assert_not_called()

    def test_a_revision_that_cannot_be_rendered_is_source_not_found(self, allowed: MagicMock, store: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE),
            patch("app.provider_contract_source.rendered_document", return_value=None),
        ):
            response = client.put(_URL, json={"apiomeVersion": "ledger-api@1.4.0"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == CODE_SOURCE_NOT_FOUND

    def test_the_response_says_where_the_contract_came_from(self, allowed: MagicMock) -> None:
        published = _published(
            source="apiome",
            source_project_slug="ledger-api",
            source_version_label="1.4.0",
            source_project_id="p-1",
            source_version_id="v-1",
        )
        rendered = MagicMock(**{"json.return_value": _oas31()})
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE),
            patch("app.provider_contract_source.rendered_document", return_value=rendered),
            patch(f"{_ROUTES}.publish_provider_contract", return_value=published),
        ):
            response = client.put(_URL, json={"apiomeVersion": "ledger-api@1.4.0"})
        assert response.json()["source"] == {
            "kind": "apiome",
            "project": "ledger-api",
            "version": "1.4.0",
            "projectId": "p-1",
            "versionId": "v-1",
        }


# ---------------------------------------------------------------------------------------------
# Permissions and reading
# ---------------------------------------------------------------------------------------------


class TestPermissions:
    def test_publishing_without_pacts_create_is_403_before_the_body_is_read(self, store: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.PACTS)),
            patch(f"{_ROUTES}._parse_body") as parse,
        ):
            response = client.put(_URL, json={"content": "e30="})
        assert response.status_code == 403
        parse.assert_not_called()
        store.assert_not_called()

    def test_publishing_checks_pacts_create_on_the_provider(self, allowed: MagicMock, store: MagicMock) -> None:
        client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        first = allowed.call_args_list[0]
        assert (first.args[2], first.args[3], first.kwargs.get("target")) == (Resource.PACTS, "create", "ledger-api")

    def test_reading_without_pacts_view_is_403(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.PACTS)),
            patch(f"{_ROUTES}.get_provider_contract") as read,
        ):
            response = client.get(_URL)
        assert response.status_code == 403
        read.assert_not_called()

    def test_a_credential_without_a_tenant_is_403(self, allowed: MagicMock, store: MagicMock) -> None:
        app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": "u"}
        response = client.put(_URL, json={"content": "e30="})
        assert response.status_code == 403
        store.assert_not_called()


class TestRead:
    def test_the_contract_reads_back_with_its_document(self, allowed: MagicMock) -> None:
        with patch(f"{_ROUTES}.get_provider_contract", return_value=_record()) as read:
            response = client.get(_URL)
        assert response.status_code == 200
        assert read.call_args.args[1:] == (_TENANT, "ledger-api", "1.4.0")
        body = response.json()
        assert body["content"] == _oas31()
        assert body["_links"]["self"]["href"].endswith("/contracts/provider/ledger-api/version/1.4.0")
        allowed.assert_called_once()
        assert allowed.call_args.args[2:] == (Resource.PACTS, "view")

    @pytest.mark.parametrize(
        "error",
        [
            ProviderContractError(CODE_CONTRACT_NOT_FOUND, "none"),
            PacticipantValidationError(CODE_NOT_FOUND, "no provider"),
        ],
        ids=["no-contract", "no-provider"],
    )
    def test_nothing_to_read_is_404(self, allowed: MagicMock, error: Exception) -> None:
        with patch(f"{_ROUTES}.get_provider_contract", side_effect=error):
            response = client.get(_URL)
        assert response.status_code == 404

    def test_links_follow_the_public_url(self, allowed: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.get_provider_contract", return_value=_record()),
            patch.object(settings, "api_public_url", "https://api.example.com"),
        ):
            body = client.get(_URL).json()
        assert body["_links"]["pb:provider"]["href"] == (
            "https://api.example.com/v1/tenants/acme/pact-broker/pacticipants/ledger-api"
        )


# ---------------------------------------------------------------------------------------------
# PFX-2.4 (#6928): self-verification evidence
# ---------------------------------------------------------------------------------------------

_EVIDENCE = _FIXTURES / "evidence"
_REPORT_ID = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"


def _with_report(name: str, content_type: str, verifier: str, success: bool = True) -> Dict[str, Any]:
    """An inline publish body carrying one of the real reports."""
    return {
        "content": _b64(json.dumps(_oas31()).encode()),
        "verificationResults": {
            "success": success,
            "content": _b64((_EVIDENCE / name).read_bytes()),
            "contentType": content_type,
            "verifier": verifier,
        },
    }


def _echo_store(*_args: Any, **_kwargs: Any) -> PublishedProviderContract:
    """A store that returns what it was given, so the response shows the stored evidence."""
    contract = _kwargs["contract"]
    return PublishedProviderContract(
        contract=_record(verification_results=contract.verification_results), created=True, new_content=True
    )


def _conformance_report(version: str = "1.4.0", outcome: str = "passed") -> Any:
    report = MagicMock(**{"model_dump.return_value": {"outcome": outcome}})
    return MagicMock(
        id=_REPORT_ID,
        outcome=outcome,
        artifact_id="p-1",
        artifact_slug="ledger-api",
        version_label=version,
        target_slug="staging-ledger",
        target_environment="staging",
        cases_total=8,
        cases_passed=8 if outcome == "passed" else 6,
        cases_failed=0 if outcome == "passed" else 2,
        cases_errored=0,
        cases_skipped=0,
        operations_total=3,
        operations_exercised=3,
        coverage_percent=100.0,
        report=report,
    )


@pytest.fixture
def echo() -> Iterator[MagicMock]:
    with (
        patch(f"{_ROUTES}.publish_provider_contract", side_effect=_echo_store) as publish,
        patch(f"{_ROUTES}.compare_provider_contract", return_value=ComparisonRun()),
    ):
        yield publish


class TestSelfVerificationEvidence:
    @pytest.mark.parametrize(
        "name, content_type, verifier, kind",
        [
            ("schemathesis-pass.junit.xml", "application/xml", "schemathesis", "junit"),
            ("schemathesis-pass.ndjson", "application/x-ndjson", "schemathesis", "schemathesis-ndjson"),
            ("dredd-pass.xml", "application/xml", "dredd", "junit"),
            ("newman-pass.json", "application/json", "newman", "newman-json"),
        ],
    )
    def test_a_passing_report_is_recorded_as_verified(
        self, allowed: MagicMock, echo: MagicMock, name: str, content_type: str, verifier: str, kind: str
    ) -> None:
        response = client.put(_URL, json=_with_report(name, content_type, verifier))
        assert response.status_code == 201, response.text
        stored = _stored_contract(echo).verification_results
        assert stored is not None
        assert (stored["evidence"]["status"], stored["evidence"]["kind"]) == ("verified", kind)
        assert stored["evidence"]["digest"] == "sha256:" + stored["contentSha256"]
        verification = response.json()["selfVerification"]
        assert (verification["status"], verification["tool"], verification["providerContractVerified"]) == (
            "verified",
            verifier,
            True,
        )
        assert verification["unverifiedPolicy"] == "warn"

    def test_a_failing_report_is_stored_and_the_contract_is_unverified(
        self, allowed: MagicMock, echo: MagicMock
    ) -> None:
        response = client.put(_URL, json=_with_report("dredd-fail.xml", "application/xml", "dredd"))
        assert response.status_code == 201
        verification = response.json()["selfVerification"]
        assert (verification["status"], verification["providerContractVerified"]) == ("failed", False)
        assert verification["summary"] == {"tests": 1, "passed": 0, "failed": 1, "errors": 0, "skipped": 0}

    def test_no_results_read_as_missing(self, allowed: MagicMock, echo: MagicMock) -> None:
        response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        verification = response.json()["selfVerification"]
        assert (verification["status"], verification["providerContractVerified"]) == ("missing", False)
        assert _stored_contract(echo).verification_results is None

    def test_the_policy_is_reported(self, allowed: MagicMock, echo: MagicMock) -> None:
        with patch.object(settings, "pact_unverified_provider_contract", "fail"):
            response = client.put(_URL, json={"content": _b64(json.dumps(_oas31()).encode())})
        assert response.json()["selfVerification"]["unverifiedPolicy"] == "fail"

    def test_an_unsupported_report_type_is_422_and_nothing_is_stored(self, allowed: MagicMock, echo: MagicMock) -> None:
        body = _with_report("dredd-pass.xml", "image/png", "dredd")
        response = client.put(_URL, json=body)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert (detail["code"], detail["pointer"]) == (
            "provider-contract-evidence-unsupported",
            "/verificationResults/contentType",
        )
        echo.assert_not_called()

    def test_a_report_that_is_not_its_type_is_422(self, allowed: MagicMock, echo: MagicMock) -> None:
        body = _with_report("newman-pass.json", "application/xml", "newman")
        response = client.put(_URL, json=body)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "provider-contract-evidence-invalid"
        echo.assert_not_called()

    def test_a_report_over_the_limit_is_413(self, allowed: MagicMock, echo: MagicMock) -> None:
        with patch.object(settings, "pact_evidence_max_bytes", 1024):
            response = client.put(_URL, json=_with_report("newman-pass.json", "application/json", "newman"))
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "provider-contract-evidence-too-large"
        echo.assert_not_called()

    def test_an_apiome_report_is_read_in_the_callers_tenant(self, allowed: MagicMock, echo: MagicMock) -> None:
        rendered = MagicMock(**{"json.return_value": _oas31()})
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE),
            patch("app.provider_contract_source.rendered_document", return_value=rendered),
            patch(f"{_ROUTES}.get_report", return_value=_conformance_report()) as read,
        ):
            response = client.put(
                _URL,
                json={
                    "apiomeVersion": "ledger-api@1.4.0",
                    "verificationResults": {"providerVerificationReportId": _REPORT_ID},
                },
            )
        assert response.status_code == 201, response.text
        assert read.call_args.args == (_TENANT, _REPORT_ID)
        resources = [call.args[2] for call in allowed.call_args_list]
        assert Resource.VERIFICATION_EVIDENCE in resources
        verification = response.json()["selfVerification"]
        assert (verification["status"], verification["kind"], verification["reportId"]) == (
            "verified",
            "apiome-provider-verification",
            _REPORT_ID,
        )
        assert verification["target"] == {"slug": "staging-ledger", "environment": "staging"}

    def test_an_apiome_report_of_another_version_is_inconclusive(self, allowed: MagicMock, echo: MagicMock) -> None:
        rendered = MagicMock(**{"json.return_value": _oas31()})
        with (
            patch(f"{_ROUTES}.resolve_apiome_source", return_value=_SOURCE),
            patch("app.provider_contract_source.rendered_document", return_value=rendered),
            patch(f"{_ROUTES}.get_report", return_value=_conformance_report(version="1.3.0")),
        ):
            response = client.put(
                _URL,
                json={
                    "apiomeVersion": "ledger-api@1.4.0",
                    "verificationResults": {"providerVerificationReportId": _REPORT_ID},
                },
            )
        verification = response.json()["selfVerification"]
        assert verification["status"] == "inconclusive"
        assert "ledger-api@1.3.0" in verification["reasons"][0]

    def test_citing_a_report_needs_verification_evidence_view(self, echo: MagicMock) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.VERIFICATION_EVIDENCE)),
            patch(f"{_ROUTES}.get_report") as read,
        ):
            response = client.put(
                _URL,
                json={
                    "content": _b64(json.dumps(_oas31()).encode()),
                    "verificationResults": {"providerVerificationReportId": _REPORT_ID},
                },
            )
        assert response.status_code == 403
        read.assert_not_called()
        echo.assert_not_called()

    def test_a_report_of_no_report_in_this_tenant_is_422(self, allowed: MagicMock, echo: MagicMock) -> None:
        from app.provider_verification_store import CODE_REPORT_NOT_FOUND, ProviderVerificationStoreError

        missing = ProviderVerificationStoreError(CODE_REPORT_NOT_FOUND, "no report")
        with patch(f"{_ROUTES}.get_report", side_effect=missing):
            response = client.put(
                _URL,
                json={
                    "content": _b64(json.dumps(_oas31()).encode()),
                    "verificationResults": {"providerVerificationReportId": _REPORT_ID},
                },
            )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert (detail["code"], detail["pointer"]) == (
            "provider-contract-evidence-report-not-found",
            "/verificationResults/providerVerificationReportId",
        )
        echo.assert_not_called()

    def test_reading_a_contract_reports_its_evidence(self, allowed: MagicMock) -> None:
        stored = {"success": True, "evidence": {"status": "failed", "kind": "junit", "reasons": ["1 failed"]}}
        with patch(f"{_ROUTES}.get_provider_contract", return_value=_record(verification_results=stored)):
            body = client.get(_URL).json()
        assert body["selfVerification"]["status"] == "failed"
        assert body["selfVerification"]["providerContractVerified"] is False


def test_the_routes_are_in_the_openapi_document() -> None:
    paths = app.openapi()["paths"]
    path = "/v1/tenants/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}"
    assert set(paths[path]) >= {"get", "put"}
    assert "requestBody" in paths[path]["put"]
