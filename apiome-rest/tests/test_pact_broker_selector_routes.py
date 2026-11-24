"""HTTP contract tests for selectors and latest queries — PFX-1.3 (#6916).

The routes PFX-1.3 adds to ``/v1/tenants/{tenant_slug}/pact-broker``, with the store faked
(``test_pact_selectors_db`` runs them against the real schema):

* ``POST …/pacts/provider/{p}/for-verification`` answers in the Pact Broker's shape — compared
  with the golden ``tests/fixtures/pact_broker/for_verification.golden.json`` — and refuses an
  ambiguous selector or a malformed body with 400 ``pact-selector-invalid`` and a pointer;
* ``…/consumer/{c}/latest/{tag}`` and ``…/consumer/{c}/branch/{branch}/latest`` pass the tag or
  branch to the store (a branch may contain ``/``);
* ``…/pacts/provider/{p}/latest[/{tag}]`` lists the latest pact of each consumer;
* ``…/pact-version/{sha}/metadata/{m}`` is the pact version itself;
* every route is gated on ``pacts:view`` and the index links to them.

Set ``APIOME_UPDATE_PACT_GOLDEN=1`` to rewrite the golden after a deliberate change.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_pending import NO_EVIDENCE, PactSuccesses, PendingEvidence
from app.pact_publication import PactRecord
from app.pact_selectors import PactCandidate, decode_metadata
from app.pacticipant import CODE_NOT_FOUND, PacticipantRecord, PacticipantValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_PROVIDER_PATH = f"{_BASE}/pacts/provider/ledger-api"
_PAIR = f"{_PROVIDER_PATH}/consumer/billing-service"
_ROUTES = "app.pact_broker_routes"
_GOLDEN = Path(__file__).parent / "fixtures" / "pact_broker" / "for_verification.golden.json"

_PROVIDER = PacticipantRecord(id="p-1", tenant_id=_TENANT, slug="ledger-api", name="Ledger API")


def _candidate(consumer: str, name: str, seq: int, number: str, sha: str, branches=(), tags=()) -> PactCandidate:
    return PactCandidate(
        consumer_id=f"id-{consumer}",
        consumer_slug=consumer,
        consumer_name=name,
        consumer_main_branch="main",
        version_id=f"00000000-0000-4000-8000-00000000000{seq}",
        version_number=number,
        version_seq=seq,
        sha=sha,
        branches=tuple(branches),
        tags=tuple(tags),
    )


_CANDIDATES: List[PactCandidate] = [
    _candidate("billing-service", "Billing Service", 1, "1.0.0", "a" * 64, ["main"], ["prod"]),
    _candidate("billing-service", "Billing Service", 2, "1.1.0", "b" * 64, ["main"]),
    _candidate("checkout-web", "Checkout Web", 3, "2f4c1a9", "c" * 64, ["feat/new-invoice"]),
]


@pytest.fixture(autouse=True)
def evidence() -> Iterator[MagicMock]:
    """No verification history: every pact is pending (PFX-1.7 tests set their own)."""
    with patch(f"{_ROUTES}.load_pending_evidence", return_value=NO_EVIDENCE) as loaded:
        yield loaded


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


@pytest.fixture
def candidates() -> Iterator[MagicMock]:
    """The store's publications for Ledger API."""
    with patch(f"{_ROUTES}.list_pact_candidates", return_value=(_PROVIDER, _CANDIDATES)) as listed:
        yield listed


def _for_verification(body: Any = None, **kwargs: Any):
    if body is None:
        return client.post(f"{_PROVIDER_PATH}/for-verification", **kwargs)
    return client.post(f"{_PROVIDER_PATH}/for-verification", json=body, **kwargs)


# --- RBAC and discovery ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", f"{_PROVIDER_PATH}/for-verification"),
        ("get", f"{_PROVIDER_PATH}/latest"),
        ("get", f"{_PROVIDER_PATH}/latest/prod"),
        ("get", f"{_PAIR}/latest/prod"),
        ("get", f"{_PAIR}/branch/main/latest"),
        ("get", f"{_PAIR}/pact-version/{'a' * 64}/metadata/czpbXQ"),
        ("get", f"{_PROVIDER_PATH}/for-verification"),
    ],
)
def test_every_new_route_is_gated_on_pacts_view(method: str, path: str) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
        patch(f"{_ROUTES}.list_pact_candidates") as listed,
        patch(f"{_ROUTES}.get_latest_pact") as latest,
        patch(f"{_ROUTES}.get_pact_by_sha") as by_sha,
    ):
        response = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == ("pacts", "view")
    listed.assert_not_called()
    latest.assert_not_called()
    by_sha.assert_not_called()


def test_the_index_links_to_the_selector_and_latest_routes(allowed: MagicMock) -> None:
    links = client.get(_BASE).json()["_links"]
    for_verification = f"{_ROOT}/pacts/provider/{{provider}}/for-verification"
    assert links["pb:provider-pacts-for-verification"] == {
        "href": for_verification,
        "title": "Pact versions to be verified for the specified provider",
        "templated": True,
    }
    assert links["beta:provider-pacts-for-verification"]["href"] == for_verification
    assert links["pb:latest-provider-pacts"]["href"] == f"{_ROOT}/pacts/provider/{{provider}}/latest"
    assert links["pb:latest-provider-pacts-with-tag"]["href"] == f"{_ROOT}/pacts/provider/{{provider}}/latest/{{tag}}"


# --- for-verification --------------------------------------------------------------------------


_GOLDEN_REQUEST = {
    "consumerVersionSelectors": [
        {"mainBranch": True},
        {"tag": "prod", "latest": True},
        {"branch": "feat/new-invoice", "consumer": "Checkout Web"},
        {"deployedOrReleased": True},
    ],
    "providerVersionBranch": "main",
    "includePendingStatus": True,
}


def test_for_verification_matches_the_pact_broker_golden(allowed: MagicMock, candidates: MagicMock) -> None:
    response = _for_verification(_GOLDEN_REQUEST)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/hal+json")
    body = response.json()
    if os.environ.get("APIOME_UPDATE_PACT_GOLDEN") == "1":
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    assert body == json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert candidates.call_args.args[1:] == (_TENANT, "ledger-api")


def test_for_verification_has_the_brokers_shape_without_pending_status(
    allowed: MagicMock, candidates: MagicMock
) -> None:
    body = _for_verification({"consumerVersionSelectors": [{"latest": True}]}).json()
    assert body["_links"]["self"] == {
        "href": f"{_ROOT}/pacts/provider/ledger-api/for-verification",
        "title": "Pacts to be verified",
    }
    pacts = body["_embedded"]["pacts"]
    assert [pact["_links"]["self"]["name"] for pact in pacts] == [
        "Pact between Billing Service (1.1.0) and Ledger API",
        "Pact between Checkout Web (2f4c1a9) and Ledger API",
    ]
    for pact in pacts:
        assert set(pact) == {"shortDescription", "verificationProperties", "_links"}
        assert set(pact["verificationProperties"]) == {"notices"}
        assert [notice["when"] for notice in pact["verificationProperties"]["notices"]] == ["before_verification"]
        assert "/pact-version/" in pact["_links"]["self"]["href"] and "/metadata/" in pact["_links"]["self"]["href"]


def test_an_empty_body_uses_the_default_selectors(allowed: MagicMock, candidates: MagicMock) -> None:
    pacts = _for_verification().json()["_embedded"]["pacts"]
    # Billing Service has a pact from its main branch; Checkout Web does not, so its latest is used.
    assert [pact["shortDescription"] for pact in pacts] == ["latest from main branch", "latest"]


def test_an_ambiguous_selector_is_a_400_with_its_pointer(allowed: MagicMock, candidates: MagicMock) -> None:
    response = _for_verification({"consumerVersionSelectors": [{"mainBranch": True}, {"tag": "x", "branch": "y"}]})
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "pact-selector-invalid",
        "message": "/consumerVersionSelectors/1: cannot specify both a tag and a branch",
        "pointer": "/consumerVersionSelectors/1",
    }
    candidates.assert_not_called()


def test_a_body_that_is_not_json_is_a_400(allowed: MagicMock, candidates: MagicMock) -> None:
    response = _for_verification(content=b"{not json", headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pact-selector-invalid"


def test_an_unknown_provider_is_a_404(allowed: MagicMock) -> None:
    missing = PacticipantValidationError(CODE_NOT_FOUND, "pacticipant 'ledger-api' not found")
    with patch(f"{_ROUTES}.list_pact_candidates", side_effect=missing):
        response = _for_verification({})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_a_provider_without_pacts_has_nothing_to_verify(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_pact_candidates", return_value=(_PROVIDER, [])):
        body = _for_verification({"consumerVersionSelectors": [{"mainBranch": True}]}).json()
    assert body["_embedded"]["pacts"] == []


# --- latest queries ----------------------------------------------------------------------------


def _record(**overrides: Any) -> PactRecord:
    payload: Dict[str, Any] = {
        "consumer_slug": "billing-service",
        "consumer_name": "Billing Service",
        "provider_slug": "ledger-api",
        "provider_name": "Ledger API",
        "consumer_version": "1.0.0",
        "sha": "a" * 64,
        "content": {"interactions": []},
        "created_at": "2026-11-24T10:00:00+00:00",
    }
    payload.update(overrides)
    return PactRecord(**payload)


def test_latest_for_a_tag_passes_the_tag(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_latest_pact", return_value=_record()) as latest:
        response = client.get(f"{_PAIR}/latest/prod")
    assert response.status_code == 200
    assert latest.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service")
    assert latest.call_args.kwargs == {"tag": "prod"}
    links = response.json()["_links"]
    assert links["pb:latest-tagged-pact-version"] == {
        "title": "Latest version of this pact for a tag",
        "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/latest/{{tag}}",
        "templated": True,
    }


@pytest.mark.parametrize("branch_in_path", ["feat/new-invoice", "feat%2Fnew-invoice"])
def test_latest_for_a_branch_accepts_a_slash_in_the_branch(allowed: MagicMock, branch_in_path: str) -> None:
    with patch(f"{_ROUTES}.get_latest_pact", return_value=_record()) as latest:
        response = client.get(f"{_PAIR}/branch/{branch_in_path}/latest")
    assert response.status_code == 200
    assert latest.call_args.kwargs == {"branch": "feat/new-invoice"}


def test_the_latest_pact_of_every_consumer(allowed: MagicMock, candidates: MagicMock) -> None:
    response = client.get(f"{_PROVIDER_PATH}/latest")
    assert response.status_code == 200
    links = response.json()["_links"]
    assert links["self"] == {
        "href": f"{_ROOT}/pacts/provider/ledger-api/latest",
        "title": "Latest pact versions for the provider Ledger API",
    }
    assert links["pb:provider"] == {"href": f"{_ROOT}/pacticipants/ledger-api", "name": "Ledger API"}
    assert links["pb:pacts"] == [
        {
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/version/1.1.0",
            "title": "Pact between Billing Service (1.1.0) and Ledger API",
            "name": "Billing Service",
        },
        {
            "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/checkout-web/version/2f4c1a9",
            "title": "Pact between Checkout Web (2f4c1a9) and Ledger API",
            "name": "Checkout Web",
        },
    ]
    assert links["provider"]["name"] == "DEPRECATED - please use the pb:provider relation"
    assert links["pacts"][0]["title"].startswith("DEPRECATED - please use the pb:pacts relation. Pact between")


def test_the_latest_tagged_pact_of_every_consumer(allowed: MagicMock, candidates: MagicMock) -> None:
    links = client.get(f"{_PROVIDER_PATH}/latest/prod").json()["_links"]
    assert links["self"]["title"] == "Latest pact versions for the provider Ledger API with consumer version tag 'prod'"
    assert links["self"]["href"] == f"{_ROOT}/pacts/provider/ledger-api/latest/prod"
    assert [link["href"].rsplit("/", 1)[1] for link in links["pb:pacts"]] == ["1.0.0"]


def test_the_metadata_link_reads_the_pact_version(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record()) as by_sha:
        response = client.get(f"{_PAIR}/pact-version/{'a' * 64}/metadata/czpbXVtiXT1tYWlu")
    assert response.status_code == 200
    assert by_sha.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", "a" * 64)
    assert response.json()["_links"]["self"]["href"].endswith("/consumer/billing-service/version/1.0.0")


# --- Pending and work-in-progress pacts (PFX-1.7, #6920) ----------------------------------------

_NOV = datetime.datetime(2026, 11, 10, 9, 0, tzinfo=datetime.timezone.utc)


def test_for_verification_reads_the_history_of_the_verifying_branch(
    allowed: MagicMock, candidates: MagicMock, evidence: MagicMock
) -> None:
    _for_verification({"providerVersionBranch": "feat/p", "includePendingStatus": True})
    assert evidence.call_args.args[1:] == (_TENANT, "p-1", "feat/p")


def test_a_verified_pact_is_no_longer_pending(allowed: MagicMock, candidates: MagicMock, evidence: MagicMock) -> None:
    evidence.return_value = PendingEvidence(
        successes={"b" * 64: PactSuccesses(branches=frozenset({"main"}), first_success_at=_NOV)},
        branch_created_at=_NOV - datetime.timedelta(days=1),
    )
    body = {"consumerVersionSelectors": [{"mainBranch": True}], "providerVersionBranch": "main"}
    (pact,) = _for_verification({**body, "includePendingStatus": True}).json()["_embedded"]["pacts"]
    assert pact["verificationProperties"]["pending"] is False
    assert pact["verificationProperties"]["notices"][1]["text"].startswith("This pact has previously been")


def test_wip_pacts_follow_the_selected_ones(allowed: MagicMock, evidence: MagicMock) -> None:
    dated = [replace(candidate, published_at=_NOV) for candidate in _CANDIDATES]
    with patch(f"{_ROUTES}.list_pact_candidates", return_value=(_PROVIDER, dated)):
        response = _for_verification(
            {
                "consumerVersionSelectors": [{"mainBranch": True}],
                "providerVersionBranch": "main",
                "includeWipPactsSince": "2026-11-01",
            }
        )
    assert response.status_code == 200
    pacts = response.json()["_embedded"]["pacts"]
    assert [pact["_links"]["self"]["name"] for pact in pacts] == [
        "Pact between Billing Service (1.1.0) and Ledger API",
        "Pact between Billing Service (1.0.0) and Ledger API",
        "Pact between Checkout Web (2f4c1a9) and Ledger API",
    ]
    selected, tagged, wip = pacts
    assert "wip" not in selected["verificationProperties"]
    assert "pending" not in selected["verificationProperties"]
    assert tagged["shortDescription"] == "latest with tag prod"
    assert wip["verificationProperties"]["wip"] is True
    assert wip["verificationProperties"]["pending"] is True
    assert "'work in progress' pact" in wip["verificationProperties"]["notices"][0]["text"]
    assert wip["shortDescription"] == "latest from branch feat/new-invoice"
    # The link records the pact as WIP, so the result the verifier publishes says so.
    metadata = wip["_links"]["self"]["href"].rsplit("/metadata/", 1)[1]
    assert decode_metadata(metadata) == {"pending": True, "wip": True}


# --- GET for-verification (PFX-1.8, #6921) ----------------------------------------------------


def test_get_for_verification_answers_as_the_post_does(allowed: MagicMock, candidates: MagicMock) -> None:
    """The Rust verifier fetches the resource with GET before it posts its selectors."""
    query = (
        "provider_version_branch=main&include_pending_status=true"
        "&consumer_version_selectors[0][tag]=prod&consumer_version_selectors[0][latest]=true"
        "&consumer_version_selectors[1][main_branch]=true"
    )
    by_get = client.get(f"{_PROVIDER_PATH}/for-verification?{query}")
    by_post = _for_verification(
        {
            "providerVersionBranch": "main",
            "includePendingStatus": True,
            "consumerVersionSelectors": [{"tag": "prod", "latest": True}, {"mainBranch": True}],
        }
    )
    assert by_get.status_code == 200 and by_get.headers["content-type"].startswith("application/hal+json")
    assert by_get.json() == by_post.json()


def test_get_for_verification_without_parameters_uses_the_defaults(allowed: MagicMock, candidates: MagicMock) -> None:
    assert client.get(f"{_PROVIDER_PATH}/for-verification").json() == _for_verification().json()


def test_get_for_verification_refuses_an_ambiguous_selector(allowed: MagicMock, candidates: MagicMock) -> None:
    query = "consumer_version_selectors[][tag]=x&consumer_version_selectors[][branch]=y"
    response = client.get(f"{_PROVIDER_PATH}/for-verification?{query}")
    assert response.status_code == 400
    assert response.json()["detail"]["pointer"] == "/consumerVersionSelectors/0"
