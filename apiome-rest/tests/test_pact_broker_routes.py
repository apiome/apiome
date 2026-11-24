"""HTTP contract tests for the Pact Broker surface — PFX-1.2 (#6915).

``/v1/tenants/{tenant_slug}/pact-broker``: the index, publishing and retrieval. The store is faked
(``test_pact_publication_db`` runs it against the real schema); what is asserted here is the
endpoint's own contract:

* reads are gated on ``pacts:view`` and publishing on ``pacts:create``, and a denial is a 403
  before the store is touched;
* a refusal becomes the HTTP status that matches its kind — 422 with a pointer for an invalid
  pact or request, 409 for changed content, 413 over the size limit, 429 over the publish budget,
  404 for anything unknown — and always carries the stable code;
* the HAL shapes Pact clients parse, with links that lead back to the base URL the client used
  (the path form, ``APIOME_API_PUBLIC_URL``, or the tenant-host alias).
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_routes import _publish_limiter
from app.pact_publication import (
    CODE_PACT_CONFLICT,
    CODE_PACT_NOT_FOUND,
    PactPublicationError,
    PactRecord,
    PublishedPact,
)
from app.pact_publication_store import PublishOutcome
from app.pacticipant import (
    CODE_INVALID_VERSION,
    CODE_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_PAIR = f"{_BASE}/pacts/provider/ledger-api/consumer/billing-service"
_ROUTES = "app.pact_broker_routes"
_SHA = "ab" * 32

_DOCUMENT: Dict[str, Any] = {
    "consumer": {"name": "Billing Service"},
    "provider": {"name": "Ledger API"},
    "interactions": [
        {
            "description": "a request for an invoice",
            "request": {"method": "GET", "path": "/invoices/42"},
            "response": {"status": 200},
        }
    ],
    "metadata": {"pactSpecification": {"version": "2.0.0"}},
}


def _record(**overrides: Any) -> PactRecord:
    """A stored pact as the store returns one."""
    payload: Dict[str, Any] = {
        "consumer_slug": "billing-service",
        "consumer_name": "Billing Service",
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "consumer_version": "1.0.0",
        "sha": _SHA,
        "content": _DOCUMENT,
        "specification_version": "2.0.0",
        "interaction_count": 1,
        "created_at": "2026-11-23T10:00:00+00:00",
    }
    payload.update(overrides)
    return PactRecord(**payload)


def _consumer() -> PacticipantRecord:
    return PacticipantRecord(
        id="22222222-2222-4222-8222-222222222222", tenant_id=_TENANT, slug="billing-service", name="Billing Service"
    )


def _version(**overrides: Any) -> PacticipantVersionRecord:
    payload: Dict[str, Any] = {
        "id": "33333333-3333-4333-8333-333333333333",
        "pacticipant_id": "22222222-2222-4222-8222-222222222222",
        "number": "1.0.0",
        "seq": 1,
        "branches": ["main"],
        "tags": ["rc"],
        "build_url": "https://ci.example.com/1",
    }
    payload.update(overrides)
    return PacticipantVersionRecord(**payload)


def _outcome(*published: PublishedPact, created: bool = True) -> PublishOutcome:
    return PublishOutcome(
        _consumer(),
        RecordedPacticipantVersion(version=_version(), created=created, head_moved=created),
        list(published) or [PublishedPact(pact=_record(), created=True, new_content=True)],
    )


def _bulk(*, contracts: Any = None, **extra: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "pacticipantName": "Billing Service",
        "pacticipantVersionNumber": "1.0.0",
        "branch": "main",
        "tags": ["rc"],
        "buildUrl": "https://ci.example.com/1",
        "contracts": [
            {
                "consumerName": "Billing Service",
                "providerName": "Ledger API",
                "specification": "pact",
                "contentType": "application/json",
                "content": base64.b64encode(json.dumps(_DOCUMENT).encode()).decode(),
            }
        ],
    }
    if contracts is not None:
        body["contracts"] = contracts
    body.update(extra)
    return body


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    """Every permission granted; yields the ``enforce_permission`` mock."""
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


# --- RBAC --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "action"),
    [
        ("get", _BASE, "view"),
        ("get", f"{_BASE}/", "view"),
        ("get", f"{_PAIR}/version/1.0.0", "view"),
        ("get", f"{_PAIR}/latest", "view"),
        ("get", f"{_PAIR}/pact-version/{_SHA}", "view"),
        ("get", f"{_BASE}/pacticipants/billing-service", "view"),
        ("get", f"{_BASE}/pacticipants/billing-service/versions/1.0.0", "view"),
        ("put", f"{_PAIR}/version/1.0.0", "create"),
        ("post", f"{_BASE}/contracts/publish", "create"),
    ],
)
def test_every_route_is_gated_on_pacts(method: str, path: str, action: str) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
        patch(f"{_ROUTES}.publish_pacts") as publish,
        patch(f"{_ROUTES}.get_pact") as read,
    ):
        kwargs = {"json": _DOCUMENT} if method == "put" else {"json": _bulk()} if method == "post" else {}
        response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == ("pacts", action)
    publish.assert_not_called()
    read.assert_not_called()


# --- index -------------------------------------------------------------------------------------


def test_the_index_links_to_every_route(allowed: MagicMock) -> None:
    response = client.get(_BASE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/hal+json")
    links = response.json()["_links"]
    assert links["self"]["href"] == _ROOT
    assert links["pb:publish-contracts"] == {
        "href": f"{_ROOT}/contracts/publish",
        "title": "Publish contracts",
        "templated": False,
    }
    assert links["pb:publish-pact"]["href"] == (
        f"{_ROOT}/pacts/provider/{{provider}}/consumer/{{consumer}}/version/{{consumerApplicationVersion}}"
    )
    assert links["pb:latest-pact-version"]["href"].endswith("/consumer/{consumer}/latest")
    assert links["pb:pact-version"]["href"].endswith("/pact-version/{pactVersion}")
    assert links["pb:pacticipant-version"]["href"] == f"{_ROOT}/pacticipants/{{pacticipant}}/versions/{{version}}"
    assert all(link["templated"] for name, link in links.items() if "{" in link["href"])


def test_links_follow_the_public_url_when_one_is_configured(
    allowed: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_public_url", "https://api.example.com/")
    assert client.get(_BASE).json()["_links"]["self"]["href"] == "https://api.example.com/v1/tenants/acme/pact-broker"


def test_the_alias_host_serves_the_index_and_links_back_to_itself(
    allowed: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "pact_broker_host_suffix", "pact.example.com")
    monkeypatch.setattr(settings, "api_public_url", "https://api.example.com")
    response = client.get("/", headers={"host": "acme.pact.example.com"})
    assert response.status_code == 200
    links = response.json()["_links"]
    assert links["self"]["href"] == "http://acme.pact.example.com"
    assert links["pb:publish-contracts"]["href"] == "http://acme.pact.example.com/contracts/publish"

    with patch(f"{_ROUTES}.get_latest_pact", return_value=_record()) as read:
        pact = client.get(
            "/pacts/provider/ledger-api/consumer/billing-service/latest", headers={"host": "acme.pact.example.com"}
        )
    assert pact.status_code == 200
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service")
    assert pact.json()["_links"]["self"]["href"] == (
        "http://acme.pact.example.com/pacts/provider/ledger-api/consumer/billing-service/version/1.0.0"
    )


# --- reading -----------------------------------------------------------------------------------


def test_a_pact_reads_back_as_published_with_links(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact", return_value=_record()) as read:
        response = client.get(f"{_PAIR}/version/1.0.0")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/hal+json")
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", "1.0.0")
    body = response.json()
    assert {key: body[key] for key in _DOCUMENT} == _DOCUMENT
    assert body["createdAt"] == "2026-11-23T10:00:00+00:00"
    assert body["_links"] == {
        "self": {
            "title": "Pact",
            "name": "Pact between Billing Service (1.0.0) and Ledger API",
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/version/1.0.0",
        },
        "pb:consumer": {
            "title": "Consumer",
            "name": "Billing Service",
            "href": f"{_ROOT}/pacticipants/billing-service",
        },
        "pb:consumer-version": {
            "title": "Consumer version",
            "name": "1.0.0",
            "href": f"{_ROOT}/pacticipants/billing-service/versions/1.0.0",
        },
        "pb:provider": {"title": "Provider", "name": "Ledger API", "href": f"{_ROOT}/pacticipants/ledger-api"},
        "pb:pact-version": {
            "title": "Pact content version permalink",
            "name": _SHA,
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}",
        },
        "pb:latest-pact-version": {
            "title": "Latest version of this pact",
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/latest",
        },
        "pb:publish-verification-results": {
            "title": "Publish verification results",
            "href": (
                f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}"
                "/verification-results"
            ),
        },
        "pb:latest-verification-results": {
            "title": "Latest verification results",
            "href": (
                f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}"
                "/verification-results/latest"
            ),
        },
        "pb:latest-tagged-pact-version": {
            "title": "Latest version of this pact for a tag",
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/latest/{{tag}}",
            "templated": True,
        },
    }


def test_names_are_filled_in_and_urls_escaped(allowed: MagicMock) -> None:
    record = _record(content={"interactions": []}, consumer_version="feat x#1")
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=record) as read:
        response = client.get(f"{_PAIR}/pact-version/{_SHA}")
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", _SHA)
    body = response.json()
    assert body["consumer"] == {"name": "Billing Service"}
    assert body["provider"] == {"name": "Ledger API"}
    assert body["_links"]["self"]["href"].endswith("/version/feat%20x%231")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PactPublicationError(CODE_PACT_NOT_FOUND, "no pact"), CODE_PACT_NOT_FOUND),
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant"), CODE_NOT_FOUND),
    ],
)
def test_an_unknown_pact_or_pacticipant_is_a_404(allowed: MagicMock, error: Exception, code: str) -> None:
    with patch(f"{_ROUTES}.get_latest_pact", side_effect=error):
        response = client.get(f"{_PAIR}/latest")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == code
    assert "pointer" not in response.json()["detail"]


def test_a_pacticipant_and_its_version_read_in_the_broker_shape(allowed: MagicMock) -> None:
    with (
        patch(f"{_ROUTES}.get_pacticipant", return_value=_consumer()) as find,
        patch(f"{_ROUTES}.get_version", return_value=_version()),
    ):
        pacticipant = client.get(f"{_BASE}/pacticipants/Billing%20Service")
        version = client.get(f"{_BASE}/pacticipants/billing-service/versions/1.0.0")
    assert find.call_args_list[0].args[1:] == (_TENANT, "Billing Service")
    assert pacticipant.json()["name"] == "Billing Service"
    assert pacticipant.json()["_links"]["self"]["href"] == f"{_ROOT}/pacticipants/billing-service"
    body = version.json()
    assert (body["number"], body["buildUrl"]) == ("1.0.0", "https://ci.example.com/1")
    assert body["_embedded"] == {"branchVersions": [{"name": "main"}], "tags": [{"name": "rc"}]}
    assert body["_links"]["pb:pacticipant"]["href"] == f"{_ROOT}/pacticipants/billing-service"


def test_an_unknown_version_is_a_404(allowed: MagicMock) -> None:
    missing = PacticipantValidationError(CODE_VERSION_NOT_FOUND, "no version")
    with (
        patch(f"{_ROUTES}.get_pacticipant", return_value=_consumer()),
        patch(f"{_ROUTES}.get_version", side_effect=missing),
    ):
        response = client.get(f"{_BASE}/pacticipants/billing-service/versions/9")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, CODE_VERSION_NOT_FOUND)


# --- publishing one pact -----------------------------------------------------------------------


def test_put_publishes_the_document_under_its_own_names(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.publish_pacts", return_value=_outcome()) as publish:
        response = client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT)
    assert response.status_code == 201
    kwargs = publish.call_args.kwargs
    assert publish.call_args.args[1] == _TENANT
    assert (kwargs["consumer_name"], kwargs["version_number"]) == ("Billing Service", "1.0.0")
    assert kwargs["allow_modification"] is False
    (pact,) = kwargs["pacts"]
    assert (pact.provider_name, pact.document, pact.interaction_count) == ("Ledger API", _DOCUMENT, 1)
    assert response.json()["_links"]["pb:pact-version"]["name"] == _SHA
    assert allowed.call_args.kwargs == {"target": "billing-service"}


def test_put_of_an_unchanged_pact_is_a_200(allowed: MagicMock) -> None:
    unchanged = _outcome(PublishedPact(pact=_record(), created=False), created=False)
    with patch(f"{_ROUTES}.publish_pacts", return_value=unchanged):
        assert client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT).status_code == 200


def test_the_deployment_can_allow_replacing_a_pact(allowed: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "pact_allow_contract_modification", True)
    with patch(f"{_ROUTES}.publish_pacts", return_value=_outcome()) as publish:
        client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT)
    assert publish.call_args.kwargs["allow_modification"] is True


def test_an_invalid_pact_is_a_422_with_the_located_problem(allowed: MagicMock) -> None:
    broken = json.loads(json.dumps(_DOCUMENT))
    del broken["interactions"][0]["request"]["method"]
    with patch(f"{_ROUTES}.publish_pacts") as publish:
        response = client.put(f"{_PAIR}/version/1.0.0", json=broken)
        not_json = client.put(f"{_PAIR}/version/1.0.0", content=b"{nope")
        wrong_names = client.put(f"{_BASE}/pacts/provider/tax-api/consumer/billing-service/version/1", json=_DOCUMENT)
    publish.assert_not_called()
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "pact-invalid",
        "message": "/interactions/0/request/method: the request method must be a non-empty string",
        "pointer": "/interactions/0/request/method",
    }
    assert (not_json.status_code, not_json.json()["detail"]["pointer"]) == (422, "")
    assert (wrong_names.status_code, wrong_names.json()["detail"]["pointer"]) == (422, "/provider/name")


def test_changed_content_is_a_409(allowed: MagicMock) -> None:
    conflict = PactPublicationError(CODE_PACT_CONFLICT, "Cannot change the content of the pact")
    with patch(f"{_ROUTES}.publish_pacts", side_effect=conflict):
        response = client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_PACT_CONFLICT


def test_a_malformed_version_is_a_400(allowed: MagicMock) -> None:
    refusal = PacticipantValidationError(CODE_INVALID_VERSION, "a version number is 1-255 characters")
    with patch(f"{_ROUTES}.publish_pacts", side_effect=refusal):
        response = client.put(f"{_PAIR}/version/%20bad", json=_DOCUMENT)
    assert (response.status_code, response.json()["detail"]["code"]) == (400, CODE_INVALID_VERSION)


def test_an_oversized_pact_is_a_413_declared_or_not(allowed: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "pact_max_bytes", 64)
    with patch(f"{_ROUTES}.publish_pacts") as publish:
        declared = client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT)

        def chunks() -> Iterator[bytes]:
            yield b"{" + b" " * 40
            yield b" " * 40 + b"}"

        streamed = client.put(f"{_PAIR}/version/1.0.0", content=chunks())
    publish.assert_not_called()
    for response in (declared, streamed):
        assert (response.status_code, response.json()["detail"]["code"]) == (413, "pact-too-large")


def test_publishing_is_budgeted_per_workspace(allowed: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_authenticated_per_minute", 10_000)
    monkeypatch.setattr(settings, "pact_publish_rate_limit_per_minute", 2)
    _publish_limiter._windows.clear()
    with (
        patch(f"{_ROUTES}.publish_pacts", return_value=_outcome()),
        patch(f"{_ROUTES}.get_latest_pact", return_value=_record()),
    ):
        statuses: List[int] = [client.put(f"{_PAIR}/version/1.0.0", json=_DOCUMENT).status_code for _ in range(2)]
        over = client.post(f"{_BASE}/contracts/publish", json=_bulk())
        read = client.get(f"{_PAIR}/latest")
    _publish_limiter._windows.clear()
    assert statuses == [201, 201]
    assert (over.status_code, over.json()["detail"]["code"]) == (429, "pact-publish-rate-limited")
    assert int(over.headers["retry-after"]) >= 0
    # Reading is not publishing.
    assert read.status_code == 200


# --- publishing in bulk ------------------------------------------------------------------------


def test_bulk_publish_passes_the_version_details_and_answers_in_the_broker_shape(allowed: MagicMock) -> None:
    second = _record(provider_slug="tax-api", provider_name="Tax API", sha="cd" * 32)
    outcome = _outcome(
        PublishedPact(pact=_record(), created=True, new_content=True),
        PublishedPact(pact=second, created=False),
    )
    tax = {**_DOCUMENT, "provider": {"name": "Tax API"}}
    contracts = _bulk()["contracts"] + [
        {
            "consumerName": "billing-service",
            "providerName": "Tax API",
            "content": base64.b64encode(json.dumps(tax).encode()).decode(),
        }
    ]
    with patch(f"{_ROUTES}.publish_pacts", return_value=outcome) as publish:
        response = client.post(f"{_BASE}/contracts/publish", json=_bulk(contracts=contracts))
    assert response.status_code == 200, response.text
    kwargs = publish.call_args.kwargs
    assert (kwargs["consumer_name"], kwargs["version_number"]) == ("Billing Service", "1.0.0")
    assert (kwargs["branch"], kwargs["tags"], kwargs["build_url"]) == ("main", ["rc"], "https://ci.example.com/1")
    assert [pact.provider_name for pact in kwargs["pacts"]] == ["Ledger API", "Tax API"]

    body = response.json()
    assert [notice["text"] for notice in body["notices"]] == [
        "Created Billing Service version 1.0.0 with branch main and tags rc",
        "Pact successfully published for Billing Service version 1.0.0 and provider Ledger API.",
        f"  View the published pact at {_ROOT}/pacts/provider/ledger-api/consumer/billing-service/version/1.0.0",
        "Pact successfully republished for Billing Service version 1.0.0 and provider Tax API with no content changes.",
        f"  View the published pact at {_ROOT}/pacts/provider/tax-api/consumer/billing-service/version/1.0.0",
    ]
    assert [notice["type"] for notice in body["notices"]] == ["debug", "success", "debug", "success", "debug"]
    # The older `logs` spelling carries the same lines, with all three fields Pact clients require.
    assert [log["message"] for log in body["logs"]] == [notice["text"] for notice in body["notices"]]
    assert {tuple(sorted(log)) for log in body["logs"]} == {("deprecationWarning", "level", "message")}
    assert body["_embedded"]["pacticipant"]["name"] == "Billing Service"
    assert body["_embedded"]["pacticipant"]["_links"]["self"]["href"] == f"{_ROOT}/pacticipants/billing-service"
    assert body["_embedded"]["version"]["number"] == "1.0.0"
    assert (
        body["_embedded"]["version"]["_links"]["self"]["href"] == f"{_ROOT}/pacticipants/billing-service/versions/1.0.0"
    )
    links = body["_links"]
    assert links["pb:pacticipant"]["name"] == "Billing Service"
    assert links["pb:pacticipant-version"]["name"] == "1.0.0"
    assert [tag["name"] for tag in links["pb:pacticipant-version-tags"]] == ["rc"]
    assert [(contract["name"], contract["pactVersionSha"]) for contract in links["pb:contracts"]] == [
        ("Pact between Billing Service (1.0.0) and Ledger API", _SHA),
        ("Pact between Billing Service (1.0.0) and Tax API", "cd" * 32),
    ]


def test_a_replaced_pact_is_reported_as_a_warning(allowed: MagicMock) -> None:
    outcome = _outcome(PublishedPact(pact=_record(revision=2), created=False, replaced=True), created=False)
    with patch(f"{_ROUTES}.publish_pacts", return_value=outcome):
        body = client.post(f"{_BASE}/contracts/publish", json=_bulk()).json()
    assert body["notices"][0]["text"].startswith("Updated Billing Service version 1.0.0")
    assert body["notices"][1] == {
        "type": "warning",
        "text": "Pact with changed content published for Billing Service version 1.0.0 and provider Ledger API.",
    }
    assert body["logs"][1]["level"] == "warn"


def _contract(**overrides: Any) -> Dict[str, Any]:
    return {**_bulk()["contracts"][0], **overrides}


@pytest.mark.parametrize(
    ("body", "code", "pointer"),
    [
        ({"pacticipantName": "Billing Service", "contracts": []}, "pact-publish-invalid", "/pacticipantVersionNumber"),
        (_bulk(contracts=[]), "pact-publish-invalid", "/contracts"),
        (_bulk(contracts=[{"consumerName": "Billing Service"}]), "pact-publish-invalid", "/contracts/0/providerName"),
        (_bulk(contracts=[_contract(consumerName="Web")]), "pact-publish-invalid", "/contracts/0/consumerName"),
        (
            _bulk(contracts=[_contract(), _contract(providerName="ledger api")]),
            "pact-publish-invalid",
            "/contracts/1/providerName",
        ),
        (_bulk(contracts=[_contract(content="***")]), "pact-publish-invalid", "/contracts/0/content"),
        (_bulk(contracts=[_contract(onConflict="merge")]), "pact-publish-unsupported", "/contracts/0/onConflict"),
        (_bulk(contracts=[_contract(specification="oas")]), "pact-publish-unsupported", "/contracts/0/specification"),
        (
            _bulk(contracts=[_contract(content=base64.b64encode(b'{"interactions": [5]}').decode())]),
            "pact-invalid",
            "/interactions/0",
        ),
    ],
)
def test_a_malformed_bulk_request_is_a_located_422(
    allowed: MagicMock, body: Dict[str, Any], code: str, pointer: str
) -> None:
    with patch(f"{_ROUTES}.publish_pacts") as publish:
        response = client.post(f"{_BASE}/contracts/publish", json=body)
    publish.assert_not_called()
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert (detail["code"], detail["pointer"]) == (code, pointer)


def test_an_invalid_pact_in_a_bulk_request_names_its_contract(allowed: MagicMock) -> None:
    broken = base64.b64encode(b'{"interactions": [5]}').decode()
    response = client.post(f"{_BASE}/contracts/publish", json=_bulk(contracts=[_contract(content=broken)]))
    assert response.json()["detail"]["message"].startswith("contract 0 (Ledger API): /interactions/0")


def test_a_bulk_request_that_is_not_json_is_a_422(allowed: MagicMock) -> None:
    response = client.post(f"{_BASE}/contracts/publish", content=b"nope")
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "pact-publish-invalid")


def test_a_bulk_conflict_is_a_409(allowed: MagicMock) -> None:
    conflict = PactPublicationError(CODE_PACT_CONFLICT, "Cannot change the content of the pact")
    with patch(f"{_ROUTES}.publish_pacts", side_effect=conflict):
        response = client.post(f"{_BASE}/contracts/publish", json=_bulk())
    assert (response.status_code, response.json()["detail"]["code"]) == (409, CODE_PACT_CONFLICT)


def test_a_credential_without_a_tenant_is_refused(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"auth_method": "jwt"}
    with patch(f"{_ROUTES}.get_latest_pact") as read:
        assert client.get(f"{_PAIR}/latest").status_code == 403
    read.assert_not_called()
