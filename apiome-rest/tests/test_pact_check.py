"""The pre-publish pact check — PFX-8.4 (#7301), without a database.

* the request and its selectors are read strictly: an unknown field, an unknown selector kind, an
  empty value or too many selectors is a ``422`` naming where;
* each interaction is ``match``, ``differs`` or ``not-in-spec``, and a row that does not match
  carries what the pact expects beside what the contract declares (``$ref`` s inlined, bounded);
* the store resolves ``main``, ``deployed:``, ``version:`` and ``draft:`` against the provider's
  versions, compares a version two selectors name once, reports every selector that names nothing
  and every version over the limit, and reads only inside the caller's tenant;
* its verdict is :func:`app.bidirectional_store.compare_with_target`'s — what a publish stores;
* the route needs ``pacts:view`` (and ``versions:view`` for a draft), is budgeted, and refuses a
  document that is not a pact with a pointer into ``/pact``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.bidirectional_store import compare_with_target
from app.bidirectional_verification import MAX_CONTRACTS_PER_PACT, ContractTarget
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_check import (
    MAX_DETAIL_BYTES,
    MAX_SELECTORS,
    OUTCOME_DIFFERS,
    OUTCOME_MATCH,
    OUTCOME_NOT_IN_SPEC,
    CheckRequest,
    PactCheckError,
    TargetResult,
    check_summary,
    declared_part,
    expected_part,
    interaction_outcome,
    parse_check_request,
    parse_selectors,
)
from app.pact_check_store import run_check
from app.pacticipant import CODE_NOT_FOUND, PacticipantRecord, PacticipantValidationError
from app.provider_contract import CODE_SOURCE_NOT_FOUND, ProviderContractError, prepare_contract
from app.provider_contract_evidence import STATUS_VERIFIED, Evidence
from app.provider_contract_source import ResolvedSource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "u", "auth_method": "api_key"}
_URL = "/v1/tenants/acme/pact-broker/pacts/check"
_STORE = "app.pact_check_store"
_OAS = json.loads((Path(__file__).parent / "fixtures" / "provider_contracts" / "ledger-api-3.1.json").read_text())


def _pact(total: Any = 1999, *extra: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "providerState": "an invoice exists",
                "request": {"method": "GET", "path": "/invoices/42"},
                "response": {"status": 200, "body": {"id": 42, "total": total}},
            },
            *extra,
        ],
        "metadata": {"pactSpecification": {"version": "2.0.0"}},
    }


_UNKNOWN = {
    "description": "a request for a PDF",
    "request": {"method": "GET", "path": "/invoices/42/pdf"},
    "response": {"status": 200},
}


def _provider(**overrides: Any) -> PacticipantRecord:
    fields: Dict[str, Any] = {
        "id": "33333333-3333-4333-8333-333333333333",
        "tenant_id": _TENANT,
        "slug": "ledger-api",
        "name": "Ledger API",
        "main_branch": "main",
        "project_id": None,
    }
    fields.update(overrides)
    return PacticipantRecord(**fields)


def _target(number: str, seq: int, branches=("main",), environments=(), evidence=True) -> ContractTarget:
    verified = Evidence(status=STATUS_VERIFIED, kind="report", tool="dredd")
    return ContractTarget(
        version_id=f"v-{number}",
        version_number=number,
        version_seq=seq,
        contract_id=f"c-{number}",
        contract_sha=f"sha-{number}",
        branches=tuple(branches),
        environments=tuple(environments),
        evidence=verified if evidence else None,
    )


class _FakeDb:
    """Answers the store's two reads; records every statement so a test can see none writes."""

    def __init__(self, contract: Any = None, sources: Optional[List[Dict[str, Any]]] = None) -> None:
        self.contract = _OAS if contract is None else contract
        self.sources = sources or []
        self.statements: List[str] = []
        self.params: List[Any] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.statements.append(sql)
        self.params.append(params)
        if "provider_contract_publication" in sql:
            return self.sources
        if "FROM apiome.provider_contract" in sql:
            return [{"content": self.contract}]
        raise AssertionError(f"unexpected statement: {sql}")


def _run(db: _FakeDb, against: List[str], targets: List[ContractTarget], provider=None, pact=None):
    request = CheckRequest(pact=pact or _pact(), selectors=parse_selectors(against))
    with (
        patch(f"{_STORE}.get_pacticipant", return_value=provider or _provider()) as lookup,
        patch(f"{_STORE}.list_contract_targets", return_value=targets),
    ):
        outcome = run_check(db, _TENANT, request, interactions=len(request.pact["interactions"]))
    lookup.assert_called_once_with(db, _TENANT, "Ledger API")
    return outcome


# --- the request ------------------------------------------------------------------------------


def test_selectors_are_read_and_repeats_kept_once() -> None:
    selectors = parse_selectors(["main", " deployed:production ", "VERSION:2.7.0", "draft:latest", "main"])
    assert [(s.kind, s.value) for s in selectors] == [
        ("main", None),
        ("deployed", "production"),
        ("version", "2.7.0"),
        ("draft", "latest"),
    ]


@pytest.mark.parametrize(
    "against, pointer, words",
    [
        ("main", "/against", "list"),
        ([], "/against", "1 to"),
        (["main"] * (MAX_SELECTORS + 1), "/against", "1 to"),
        (["tag:prod"], "/against/0", "not a selector"),
        (["main", "deployed:"], "/against/1", "needs a value"),
        (["main:x"], "/against/0", "not a selector"),
        ([3], "/against/0", "non-empty string"),
        (["x" * 301], "/against/0", "300"),
    ],
)
def test_a_bad_selector_is_refused_where_it_is(against: Any, pointer: str, words: str) -> None:
    with pytest.raises(PactCheckError) as caught:
        parse_selectors(against)
    assert caught.value.pointer == pointer
    assert words in str(caught.value)


def test_an_unknown_field_is_refused_not_ignored() -> None:
    with pytest.raises(PactCheckError) as caught:
        parse_check_request({"pact": _pact(), "against": ["main"], "branch": "main"})
    assert caught.value.pointer == "/branch"
    with pytest.raises(PactCheckError):
        parse_check_request({"against": ["main"]})
    with pytest.raises(PactCheckError):
        parse_check_request([])


# --- per interaction --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interaction, outcome",
    [
        ({"verdict": "pass", "failures": []}, OUTCOME_MATCH),
        ({"verdict": "partial", "failures": []}, OUTCOME_MATCH),
        ({"verdict": "fail", "failures": [{"code": "response.body.schema-mismatch"}]}, OUTCOME_DIFFERS),
        ({"verdict": "fail", "failures": [{"code": "request.operation.unknown"}]}, OUTCOME_NOT_IN_SPEC),
        ({"verdict": "fail", "failures": [{"code": "request.method.undeclared"}]}, OUTCOME_NOT_IN_SPEC),
        ({"verdict": "fail", "failures": [{"code": "message.unknown"}]}, OUTCOME_NOT_IN_SPEC),
    ],
)
def test_each_interaction_has_an_outcome(interaction: Dict[str, Any], outcome: str) -> None:
    assert interaction_outcome(interaction) == outcome


def test_the_drawer_shows_the_pact_beside_the_inlined_contract() -> None:
    pact = _pact(total="x")
    interaction = {
        "pointer": "/interactions/0",
        "operation": {"method": "GET", "path": "/invoices/{id}", "pointer": "#/paths/~1invoices~1{id}/get"},
    }
    assert expected_part(pact, interaction) == {"value": pact["interactions"][0]["response"]}
    declared = declared_part(_OAS, pact, interaction)
    assert declared["pointer"] == "#/paths/~1invoices~1{id}/get/responses/200"
    schema = declared["value"]["content"]["application/json"]["schema"]
    assert "$ref" not in json.dumps(schema)
    assert schema == _OAS["components"]["schemas"]["Invoice"]


def test_a_large_excerpt_is_truncated_not_sent() -> None:
    pact = _pact()
    pact["interactions"][0]["response"]["body"] = {"blob": "x" * (MAX_DETAIL_BYTES + 10)}
    part = expected_part(pact, {"pointer": "/interactions/0"})
    assert part["truncated"] is True and part["bytes"] > MAX_DETAIL_BYTES


def test_a_cyclic_ref_stops() -> None:
    contract = {
        "paths": {"/a": {"get": {"responses": {"200": {"$ref": "#/components/responses/R"}}}}},
        "components": {
            "responses": {"R": {"content": {"application/json": {"schema": {"$ref": "#/components/responses/R"}}}}}
        },
    }
    pact = {"interactions": [{"request": {"method": "GET", "path": "/a"}, "response": {"status": 200}}]}
    declared = declared_part(
        contract, pact, {"pointer": "/interactions/0", "operation": {"pointer": "#/paths/~1a/get"}}
    )
    assert "value" in declared


def test_the_summary_passes_only_when_everything_was_compared_and_passed() -> None:
    ok = TargetResult(selectors=["main"], reasons=[], provider_version="1", success=True)
    bad = TargetResult(selectors=["main"], reasons=[], provider_version="2", success=False)
    assert check_summary([ok], [], [])["success"] is True
    assert check_summary([ok, bad], [], [])["success"] is False
    assert check_summary([ok], [{"selector": "x", "reason": "y"}], [])["success"] is False
    assert check_summary([], [], [])["success"] is False


# --- the store --------------------------------------------------------------------------------


def test_the_verdict_is_what_a_publish_stores() -> None:
    target = _target("2.7.0", 2)
    for total in (1999, "not a number"):
        outcome = _run(_FakeDb(), ["version:2.7.0"], [target], pact=_pact(total))
        stored = compare_with_target(_pact(total), _OAS, target)
        [result] = outcome.results
        assert (result.verdict, result.success) == (stored.verdict, stored.success)
    assert result.success is False
    assert result.interactions[0]["outcome"] == OUTCOME_DIFFERS
    assert result.interactions[0]["providerStates"] == ["an invoice exists"]
    assert "expected" in result.interactions[0] and "declared" in result.interactions[0]


def test_an_unverified_contract_reads_as_a_publish_would() -> None:
    target = _target("2.7.0", 2, evidence=False)
    [result] = _run(_FakeDb(), ["version:2.7.0"], [target]).results
    assert result.verdict == compare_with_target(_pact(), _OAS, target).verdict == "unverified"
    assert result.comparison_verdict == "pass"
    assert result.evidence == "missing"


def test_selectors_resolve_to_the_right_versions() -> None:
    targets = [
        _target("2.6.1", 1, environments=("production",)),
        _target("2.7.0", 2, environments=("staging",)),
        _target("3.0.0-beta", 3, branches=("feature/x",)),
    ]
    outcome = _run(_FakeDb(), ["main", "deployed:Production", "deployed:staging"], targets)
    assert [(r.provider_version, r.selectors) for r in outcome.results] == [
        ("2.7.0", ["main", "deployed:staging"]),
        ("2.6.1", ["deployed:Production"]),
    ]
    assert outcome.results[0].reasons == ["main branch main", "deployed to staging"]
    assert outcome.unresolved == []


def test_a_not_in_spec_interaction_is_reported() -> None:
    [result] = _run(_FakeDb(), ["version:2.7.0"], [_target("2.7.0", 2)], pact=_pact(1999, _UNKNOWN)).results
    assert result.counts() == {"match": 1, "differs": 0, "notInSpec": 1}


def test_selectors_that_name_nothing_are_reported_with_reasons() -> None:
    outcome = _run(
        _FakeDb(),
        ["main", "deployed:qa", "version:9.9.9", "draft:latest"],
        [_target("1.0.0", 1, branches=("develop",))],
    )
    assert outcome.results == []
    reasons = {entry["selector"]: entry["reason"] for entry in outcome.unresolved}
    assert "main branch 'main'" in reasons["main"]
    assert "'qa'" in reasons["deployed:qa"]
    assert "'9.9.9'" in reasons["version:9.9.9"]
    assert "not bound" in reasons["draft:latest"]


def test_a_provider_without_a_main_branch_says_so() -> None:
    outcome = _run(_FakeDb(), ["main"], [_target("1.0.0", 1)], provider=_provider(main_branch=None))
    assert "no main branch recorded" in outcome.unresolved[0]["reason"]


def test_an_unregistered_provider_resolves_nothing() -> None:
    request = CheckRequest(pact=_pact(), selectors=parse_selectors(["main", "version:1"]))
    with patch(f"{_STORE}.get_pacticipant", side_effect=PacticipantValidationError(CODE_NOT_FOUND, "no")):
        outcome = run_check(_FakeDb(), _TENANT, request, interactions=1)
    assert outcome.provider_slug is None
    assert [entry["selector"] for entry in outcome.unresolved] == ["main", "version:1"]
    assert outcome.to_dict()["provider"]["registered"] is False


def test_versions_over_the_limit_are_skipped_not_dropped() -> None:
    targets = [_target(f"1.{i}", i, environments=("production",)) for i in range(MAX_CONTRACTS_PER_PACT + 2)]
    outcome = _run(_FakeDb(), ["deployed:production"], targets)
    assert len(outcome.results) == MAX_CONTRACTS_PER_PACT
    assert len(outcome.skipped) == 2
    assert "limit" in outcome.skipped[0]["reason"]


def test_a_draft_renders_the_bound_project_revision() -> None:
    source = ResolvedSource(project_id="p", project_slug="ledger", version_id="rev-1", version_label="2.8.0-rc1")
    contract = prepare_contract(_OAS, content_type="application/json")
    with (
        patch(f"{_STORE}.resolve_apiome_source", return_value=source) as resolve,
        patch(f"{_STORE}.render_apiome_contract", return_value=contract),
    ):
        outcome = _run(_FakeDb(), ["draft:2.8.0-rc1"], [], provider=_provider(project_id="p"))
    assert resolve.call_args.args[3].version == "2.8.0-rc1"
    [result] = outcome.results
    assert result.draft is True
    assert result.source == {"projectId": "p", "projectSlug": "ledger", "versionLabel": "2.8.0-rc1"}
    assert result.verdict == "unverified"  # a draft has no self-verification evidence yet


def test_a_draft_that_does_not_resolve_is_reported() -> None:
    error = ProviderContractError(CODE_SOURCE_NOT_FOUND, "no version 'x' in project 'ledger'")
    with patch(f"{_STORE}.resolve_apiome_source", side_effect=error):
        outcome = _run(_FakeDb(), ["draft:x"], [], provider=_provider(project_id="p"))
    assert outcome.unresolved == [{"selector": "draft:x", "reason": "no version 'x' in project 'ledger'"}]


def test_the_store_only_reads_and_stays_in_the_provider() -> None:
    db = _FakeDb(
        sources=[
            {
                "version_id": "v-2.7.0",
                "source_project_id": "p",
                "source_project_slug": "ledger",
                "source_version_label": "2.7.0",
            }
        ]
    )
    outcome = _run(db, ["version:2.7.0"], [_target("2.7.0", 2)])
    assert outcome.results[0].source == {"projectId": "p", "projectSlug": "ledger", "versionLabel": "2.7.0"}
    for sql in db.statements:
        assert sql.strip().upper().startswith("SELECT")
    assert all(_provider().id in params for params in db.params)


# --- the route --------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch("app.pact_check_routes.enforce_permission", return_value="u") as enforce:
        yield enforce


def test_the_route_answers_with_the_store_outcome(allowed: MagicMock) -> None:
    with (
        patch("app.pact_check_store.get_pacticipant", return_value=_provider()),
        patch("app.pact_check_store.list_contract_targets", return_value=[_target("2.7.0", 2)]),
        patch("app.pact_check_routes.db", _FakeDb()),
    ):
        response = client.post(_URL, json={"pact": _pact(), "against": ["version:2.7.0", "deployed:prod"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {"versions": 1, "passed": 1, "failed": 0, "unresolved": 1, "skipped": 0, "success": False}
    assert body["results"][0]["counts"] == {"match": 1, "differs": 0, "notInSpec": 0}
    assert allowed.call_args.args[2:] == ("pacts", "view")


def test_the_route_needs_pacts_view() -> None:
    with (
        patch("app.pact_check_routes.enforce_permission", side_effect=HTTPException(status_code=403, detail="no")),
        patch("app.pact_check_store.run_check") as run,
    ):
        response = client.post(_URL, json={"pact": _pact(), "against": ["main"]})
    assert response.status_code == 403
    run.assert_not_called()


def test_a_draft_also_needs_versions_view(allowed: MagicMock) -> None:
    def guard(_db: Any, _auth: Any, resource: str, action: str) -> str:
        if resource == "versions":
            raise HTTPException(status_code=403, detail="no")
        return "u"

    allowed.side_effect = guard
    response = client.post(_URL, json={"pact": _pact(), "against": ["draft:latest"]})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "body, pointer",
    [
        ({"pact": _pact(), "against": ["tag:x"]}, "/against/0"),
        ({"pact": _pact(), "against": ["main"], "dryRun": True}, "/dryRun"),
        ({"pact": {"consumer": {"name": "A"}}, "against": ["main"]}, "/pact"),
        (
            {"pact": {"interactions": [{"request": {}, "response": {}}]}, "against": ["main"]},
            "/pact/interactions/0/request/method",
        ),
        ({"pact": {"interactions": []}, "against": ["main"]}, "/pact/provider/name"),
    ],
)
def test_a_bad_request_is_a_located_422(allowed: MagicMock, body: Dict[str, Any], pointer: str) -> None:
    response = client.post(_URL, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["pointer"] == pointer


def test_a_body_that_is_not_json_is_a_422(allowed: MagicMock) -> None:
    response = client.post(_URL, content=b"{nope", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-check-invalid"


def test_checks_are_budgeted(allowed: MagicMock) -> None:
    from app import pact_check_routes

    with (
        patch.object(pact_check_routes.settings, "rate_limit_enabled", True),
        patch.object(pact_check_routes.settings, "pact_check_rate_limit_per_minute", 1),
        patch.object(pact_check_routes, "_check_limiter", pact_check_routes.FixedWindowRateLimiter()),
        patch("app.pact_check_routes.run_check") as run,
    ):
        run.return_value.to_dict.return_value = {}
        first = client.post(_URL, json={"pact": _pact(), "against": ["main"]})
        second = client.post(_URL, json={"pact": _pact(), "against": ["main"]})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "pact-check-rate-limited"
    assert "Retry-After" in second.headers
