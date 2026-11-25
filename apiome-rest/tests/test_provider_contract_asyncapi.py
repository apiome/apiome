"""AsyncAPI provider contracts and message comparisons end to end — PFX-3.6 (#6936).

The message comparison engine has its own corpus (``test_pact_asyncapi_compare``). These tests hold
the parts around it together:

* an AsyncAPI 2.x / 3.x document is a provider contract (``contractType: asyncapi``, read from the
  document when omitted) — and every structural refusal is located;
* the publish and read routes enforce ``pacts:create`` / ``pacts:view`` before anything is parsed,
  hand the caller's tenant to the store, and report the contract as AsyncAPI;
* the bi-directional store compares an AsyncAPI contract with the pact's messages;
* the PFX-2.5 fidelity report lists the message checks for such a comparison.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import bidirectional_store as store
from app.bidirectional_verification import ComparisonRun, ContractTarget
from app.main import app
from app.pact_asyncapi_compare import MESSAGE_FAILURE_CLASSES, MESSAGE_WARNING_CLASSES
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_routes import _publish_limiter
from app.pact_comparison_fidelity import MESSAGE_CHECK_LABELS, build_fidelity_report, check_of_finding
from app.permissions import Resource
from app.provider_contract import (
    CODE_CONTRACT_INVALID,
    CODE_UNSUPPORTED,
    ProviderContractError,
    ProviderContractRecord,
    PublishedProviderContract,
    PublishProviderContractRequest,
    check_request,
    prepare_contract,
    validate_asyncapi_contract,
    validate_contract,
)

CORPUS = Path(__file__).parent / "golden" / "pact_asyncapi_compare"
_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_URL = "/v1/tenants/acme/pact-broker/contracts/provider/orders-service/version/2.1.0"
_ROUTES = "app.provider_contract_routes"

client = TestClient(app)


def _orders() -> Dict[str, Any]:
    return yaml.safe_load((CORPUS / "providers" / "orders-3.0.yaml").read_text())


def _lights() -> Dict[str, Any]:
    return json.loads((CORPUS / "providers" / "streetlights-2.6.json").read_text())


def _corpus_pact(case: str) -> Dict[str, Any]:
    return json.loads((CORPUS / "pacts" / f"{case}.json").read_text())


def _refusal(document: Dict[str, Any]) -> ProviderContractError:
    with pytest.raises(ProviderContractError) as caught:
        validate_asyncapi_contract(document)
    assert caught.value.code == CODE_CONTRACT_INVALID
    return caught.value


# =============================================================================================
# What an AsyncAPI provider contract is
# =============================================================================================


class TestValidation:
    def test_both_corpus_documents_are_contracts(self) -> None:
        assert validate_asyncapi_contract(_orders()) == "3.0.0"
        assert validate_asyncapi_contract(_lights()) == "2.6.0"

    @pytest.mark.parametrize(
        ("document", "pointer"),
        [
            ({"openapi": "3.1.0"}, "/openapi"),
            ({"swagger": "2.0"}, "/swagger"),
            ({"info": {"title": "t", "version": "1"}}, "/asyncapi"),
            ({"asyncapi": "1.2.0", "info": {"title": "t", "version": "1"}}, "/asyncapi"),
            ({"asyncapi": "3.0.0"}, "/info"),
            ({"asyncapi": "3.0.0", "info": {"title": "t"}}, "/info"),
            ({"asyncapi": "2.6.0", "info": {"title": "t", "version": "1"}}, "/channels"),
            ({"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "channels": []}, "/channels"),
            ({"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "channels": {"a/b": 1}}, "/channels/a~1b"),
            (
                {"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "channels": {"c": {"messages": []}}},
                "/channels/c/messages",
            ),
            (
                {"asyncapi": "2.6.0", "info": {"title": "t", "version": "1"}, "channels": {"c": {"publish": "x"}}},
                "/channels/c/publish",
            ),
            ({"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "operations": []}, "/operations"),
            (
                {"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "operations": {"o": {"action": "emit"}}},
                "/operations/o/action",
            ),
            (
                {
                    "asyncapi": "3.0.0",
                    "info": {"title": "t", "version": "1"},
                    "channels": {"c": {"messages": {"m": {"$ref": "#/components/messages/missing"}}}},
                },
                "/channels/c/messages/m/$ref",
            ),
        ],
    )
    def test_each_structural_problem_is_located(self, document: Dict[str, Any], pointer: str) -> None:
        assert _refusal(document).pointer == pointer

    def test_a_reference_out_of_the_document_is_not_refused(self) -> None:
        # The comparison reports such a payload as not usable; publishing it is allowed.
        document = _orders()
        assert document["channels"]["external"]["messages"]["ExternalEvent"]["payload"]["$ref"].startswith("https:")
        assert validate_asyncapi_contract(document) == "3.0.0"

    def test_the_contract_type_is_read_from_the_document_when_omitted(self) -> None:
        assert validate_contract(_orders(), None) == ("asyncapi", "3.0.0")
        oas = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
        assert validate_contract(oas, None) == ("oas", "3.1.0")

    def test_an_asyncapi_document_sent_as_oas_is_refused_with_the_fix(self) -> None:
        with pytest.raises(ProviderContractError) as caught:
            validate_contract(_orders(), "oas")
        assert caught.value.pointer == "/asyncapi"
        assert "contractType 'asyncapi'" in str(caught.value)

    def test_an_openapi_document_sent_as_asyncapi_is_refused(self) -> None:
        with pytest.raises(ProviderContractError) as caught:
            validate_contract({"openapi": "3.1.0"}, "asyncapi")
        assert caught.value.pointer == "/openapi"

    def test_prepare_counts_messages_and_keeps_the_asyncapi_version(self) -> None:
        contract = prepare_contract(_orders(), content_type="application/yaml")
        assert (contract.oas_version, contract.operation_count) == ("3.0.0", 10)
        assert prepare_contract(_lights(), content_type="application/json").operation_count == 4

    def test_asyncapi_with_an_apiome_version_is_unsupported(self) -> None:
        body = PublishProviderContractRequest.model_validate({"contractType": "asyncapi", "apiomeVersion": "orders@1"})
        with pytest.raises(ProviderContractError) as caught:
            check_request(body)
        assert (caught.value.code, caught.value.pointer) == (CODE_UNSUPPORTED, "/apiomeVersion")

    @pytest.mark.parametrize("kind", ["asyncapi", "ASYNCAPI", "oas", None])
    def test_both_contract_types_are_accepted(self, kind: Any) -> None:
        payload: Dict[str, Any] = {"content": "e30="}
        if kind is not None:
            payload["contractType"] = kind
        check_request(PublishProviderContractRequest.model_validate(payload))

    def test_the_record_reads_its_contract_type_from_the_content(self) -> None:
        record = _record()
        assert record.contract_type == "asyncapi"
        assert _record(content={"openapi": "3.1.0"}).contract_type == "oas"


# =============================================================================================
# The routes
# =============================================================================================


def _record(**overrides: Any) -> ProviderContractRecord:
    payload: Dict[str, Any] = {
        "provider_slug": "orders-service",
        "provider_name": "Orders Service",
        "provider_version": "2.1.0",
        "sha": "cd" * 32,
        "content": _orders(),
        "oas_version": "3.0.0",
        "operation_count": 10,
        "content_type": "application/yaml",
        "created_at": "2026-11-25T10:00:00+00:00",
    }
    payload.update(overrides)
    return ProviderContractRecord(**payload)


@pytest.fixture(autouse=True)
def authenticated() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    _publish_limiter._windows.clear()
    yield
    app.dependency_overrides.clear()


def _deny(denied: str) -> Any:
    def enforce(_db: Any, _auth: Any, resource: str, action: str, **_kwargs: Any) -> str:
        if resource == denied:
            raise HTTPException(status_code=403, detail=f"Missing permission: {resource}:{action}")
        return "test-user-id"

    return enforce


def _yaml_body(**extra: Any) -> Dict[str, Any]:
    raw = (CORPUS / "providers" / "orders-3.0.yaml").read_bytes()
    return {"content": base64.b64encode(raw).decode(), "contentType": "application/yaml", **extra}


class TestRoutes:
    def test_publishing_an_asyncapi_contract_stores_it_for_the_callers_tenant(self) -> None:
        published = PublishedProviderContract(contract=_record(), created=True, new_content=True)
        with (
            patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce,
            patch(f"{_ROUTES}.publish_provider_contract", return_value=published) as publish,
            patch(f"{_ROUTES}.compare_provider_contract", return_value=ComparisonRun()) as compare,
        ):
            response = client.put(_URL, json=_yaml_body(contractType="asyncapi", branch="main"))
        assert response.status_code == 201, response.text
        assert enforce.call_args_list[0].args[2] == Resource.PACTS
        assert publish.call_args.args[1] == _TENANT
        contract = publish.call_args.kwargs["contract"]
        assert (contract.oas_version, contract.operation_count, contract.content_type) == (
            "3.0.0",
            10,
            "application/yaml",
        )
        assert compare.call_args.args[1] == _TENANT
        body = response.json()
        assert (body["contractType"], body["asyncapiVersion"], body["messageCount"]) == ("asyncapi", "3.0.0", 10)
        assert "oasVersion" not in body and "operationCount" not in body

    def test_the_contract_type_may_be_left_out(self) -> None:
        published = PublishedProviderContract(contract=_record(), created=True, new_content=True)
        with (
            patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id"),
            patch(f"{_ROUTES}.publish_provider_contract", return_value=published) as publish,
            patch(f"{_ROUTES}.compare_provider_contract", return_value=ComparisonRun()),
        ):
            response = client.put(_URL, json=_yaml_body())
        assert response.status_code == 201, response.text
        assert publish.call_args.kwargs["contract"].oas_version == "3.0.0"

    def test_publishing_without_pacts_create_is_403_before_anything_is_read(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.PACTS)),
            patch(f"{_ROUTES}.publish_provider_contract") as publish,
            patch(f"{_ROUTES}.compare_provider_contract") as compare,
        ):
            response = client.put(_URL, json=_yaml_body(contractType="asyncapi"))
        assert response.status_code == 403
        publish.assert_not_called()
        compare.assert_not_called()

    def test_an_invalid_asyncapi_document_is_422_with_its_pointer(self) -> None:
        document = {"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}, "operations": {"o": {"action": "x"}}}
        with (
            patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id"),
            patch(f"{_ROUTES}.publish_provider_contract") as publish,
        ):
            response = client.put(
                _URL, json={"content": base64.b64encode(json.dumps(document).encode()).decode()}
            )
        assert response.status_code == 422
        assert response.json()["detail"]["pointer"] == "/operations/o/action"
        publish.assert_not_called()

    def test_an_asyncapi_contract_named_by_apiome_version_is_422(self) -> None:
        with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id"):
            response = client.put(_URL, json={"contractType": "asyncapi", "apiomeVersion": "orders@1.0.0"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == CODE_UNSUPPORTED

    def test_reading_reports_an_asyncapi_contract(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id"),
            patch(f"{_ROUTES}.get_provider_contract", return_value=_record()) as read,
        ):
            response = client.get(_URL)
        assert response.status_code == 200
        assert read.call_args.args[1] == _TENANT
        body = response.json()
        assert (body["contractType"], body["asyncapiVersion"], body["messageCount"]) == ("asyncapi", "3.0.0", 10)
        assert body["content"]["asyncapi"] == "3.0.0"

    def test_reading_without_pacts_view_is_403(self) -> None:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=_deny(Resource.PACTS)),
            patch(f"{_ROUTES}.get_provider_contract") as read,
        ):
            response = client.get(_URL)
        assert response.status_code == 403
        read.assert_not_called()


# =============================================================================================
# The bi-directional store and the fidelity report
# =============================================================================================

_TARGET = ContractTarget(
    version_id="v-id", version_number="2.1.0", version_seq=1, contract_id="c-id", contract_sha="e" * 64
)


def test_an_asyncapi_contract_is_compared_with_the_pacts_messages() -> None:
    stored = store._compare(_corpus_pact("fail-06-body-schema"), _orders(), _TARGET)
    assert stored.payload["contractType"] == "asyncapi"
    assert stored.payload["providerContractSha"] == "e" * 64
    assert stored.success is False
    assert stored.test_results[0]["mismatches"][0]["attribute"] == "message.body.schema-mismatch"


def test_an_openapi_contract_still_reports_messages_as_not_http() -> None:
    oas = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
    stored = store._compare(_corpus_pact("pass-01-v3-topic-with-template"), oas, _TARGET)
    assert "contractType" not in stored.payload
    (interaction,) = stored.payload["interactions"]
    assert [note["code"] for note in interaction["fidelity"]] == ["interaction-not-http"]


def test_a_broken_asyncapi_contract_is_stored_as_not_comparable() -> None:
    stored = store._compare(_corpus_pact("pass-01-v3-topic-with-template"), {"asyncapi": "9.0.0"}, _TARGET)
    assert stored.success is False
    assert "AsyncAPI 2.x or 3.x" in stored.payload["error"]["message"]


@pytest.mark.parametrize("code", sorted(MESSAGE_FAILURE_CLASSES) + sorted(MESSAGE_WARNING_CLASSES))
def test_every_message_failure_and_warning_belongs_to_a_message_check(code: str) -> None:
    assert check_of_finding(code) in MESSAGE_CHECK_LABELS


def test_the_fidelity_report_lists_the_message_checks() -> None:
    stored = store._compare(_corpus_pact("partial-06-mixed-pact"), _orders(), _TARGET)
    report = build_fidelity_report(stored.payload)
    assert (report["contractType"], report["asyncapiVersion"]) == ("asyncapi", "3.0.0")
    assert "oasVersion" not in report
    http, sync, message = report["interactions"]
    assert [check["status"] for check in http["checks"]] == ["not-run"] * 4
    assert http["checks"][0]["reason"] == "the interaction has no message to compare"
    assert sync["couldNotCompare"][0]["code"] == "synchronous-message-not-compared"
    assert message["message"]["message"] == "OrderCreated"
    assert [(check["check"], check["status"]) for check in message["checks"]] == [
        ("message.channel", "compared"),
        ("message.content-type", "compared"),
        ("message.metadata", "compared"),
        ("message.body", "compared"),
    ]


def test_message_notes_are_attributed_to_their_check() -> None:
    stored = store._compare(_corpus_pact("partial-05-rules-and-generators"), _orders(), _TARGET)
    (interaction,) = build_fidelity_report(stored.payload)["interactions"]
    statuses = {check["check"]: check["status"] for check in interaction["checks"]}
    assert statuses["message.matching-rules"] == "partial"
    assert {note["check"] for note in interaction["unsupportedMatchingRules"]} == {"message.matching-rules"}


def test_a_report_with_no_message_says_so() -> None:
    pact = {"interactions": [{"description": "x", "request": {"method": "GET", "path": "/"}, "response": {}}]}
    stored = store._compare(pact, _orders(), _TARGET)
    report = build_fidelity_report(stored.payload)
    assert report["strength"] == "none"
    assert report["statement"] == (
        "Nothing was compared: no interaction is a message to compare with the AsyncAPI provider contract."
    )


def test_an_openapi_report_is_unchanged_by_message_support() -> None:
    oas = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
    report = build_fidelity_report(store._compare(_corpus_pact("pass-01-v3-topic-with-template"), oas, _TARGET).payload)
    assert report["oasVersion"] == "3.1.0"
    assert "contractType" not in report
    (interaction,) = report["interactions"]
    assert "message" not in interaction
    assert interaction["checks"][0]["check"] == "request.operation"

