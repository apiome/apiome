"""The hosted Pact verifier end to end, with every store faked — PFX-3.2 (#6932).

:func:`app.pact_verifier_service.verify_provider_pacts` against pacts in the shapes pact-js,
pact-jvm and pact-go write, replayed on the real runner over a fake transport:

* pacts are chosen by the for-verification selectors, pending and WIP included;
* a conformant provider yields one successful verification result per pact, tagged with the
  provider version and branch, carrying Pact-shaped test results — what can-i-deploy reads;
* a drifted provider yields a failed result whose mismatches name interaction, field and rule;
* an incomplete run publishes nothing; ``publish: false`` publishes nothing;
* a run cannot widen the target policy;
* a run that cannot start is refused before a single request is sent.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest

from app.consumer_contract_store import ConsumerActor
from app.contract_runner import AuthResolutionError
from app.pact_pending import NO_EVIDENCE
from app.pact_provider_state import ProviderStateRecord, StateParameter, StateSetup
from app.pact_publication import PactPublicationError, PactRecord, pact_content_sha
from app.pact_selectors import CODE_SELECTOR_INVALID, PactCandidate
from app.pact_verifier import PactVerificationOptions
from app.pact_verifier_service import (
    CODE_TARGET_AUTH_UNAVAILABLE,
    CODE_TOO_MANY_PACTS,
    NOT_PUBLISHED_DISABLED,
    NOT_PUBLISHED_INCOMPLETE,
    PactVerifierError,
    PactVerifyRequest,
    PactVerifyResponse,
    provider_state_handler,
    verify_provider_pacts,
)
from app.pacticipant import PacticipantRecord, PacticipantValidationError
from app.verification_result import VerificationResultRecord
from app.verification_target import CODE_NOT_FOUND, TargetValidationError
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM, LedgerApi, load_pact, target

_TENANT = "11111111-1111-4111-8111-111111111111"
_SERVICE = "app.pact_verifier_service"
_BASE = "https://api.example.test/v1/tenants/acme/pact-broker"
_ACTOR = ConsumerActor(user_id="33333333-3333-4333-8333-333333333333", label="ci@example.test", kind="api_key")
_PROVIDER = PacticipantRecord(
    id="p-ledger", tenant_id=_TENANT, slug="ledger-api", name="Ledger API", main_branch="main"
)
_EVERYTHING = PactVerificationOptions(allow_mutating=True, replay_without_state_setup=True)


class _Broker:
    """The stores the verifier reads and writes, in memory."""

    def __init__(self, names: List[str], *, branches: Optional[Dict[str, tuple]] = None) -> None:
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.candidates: List[PactCandidate] = []
        self.published: List[Dict[str, Any]] = []
        self.branch_versions: List[tuple] = []
        self.evidence: List[Any] = []
        self.webhooks: List[VerificationResultRecord] = []
        for seq, name in enumerate(names, start=1):
            document = load_pact(name)
            sha = pact_content_sha(document)
            consumer = document["consumer"]["name"]
            slug = consumer.lower().replace(" ", "-")
            self.documents[sha] = document
            self.candidates.append(
                PactCandidate(
                    consumer_id=f"c-{seq}",
                    consumer_slug=slug,
                    consumer_name=consumer,
                    consumer_main_branch="main",
                    version_id=f"v-{seq}",
                    version_number=f"{seq}.0.0",
                    version_seq=seq,
                    sha=sha,
                    branches=(branches or {}).get(name, ("main",)),
                )
            )

    # -- fakes of the store functions ---------------------------------------------------------

    def list_pact_candidates(self, _db: Any, tenant_id: str, provider_ref: str):
        assert tenant_id == _TENANT
        if provider_ref != "ledger-api":
            raise PacticipantValidationError("pacticipant-not-found", f"no pacticipant '{provider_ref}'")
        return _PROVIDER, list(self.candidates)

    def get_pact_by_sha(self, _db: Any, tenant_id: str, provider: str, consumer: str, sha: str) -> PactRecord:
        assert (tenant_id, provider) == (_TENANT, "ledger-api")
        candidate = next(c for c in self.candidates if c.sha == sha and c.consumer_slug == consumer)
        document = self.documents[sha]
        return PactRecord(
            consumer_slug=candidate.consumer_slug,
            consumer_name=candidate.consumer_name,
            provider_slug="ledger-api",
            provider_name="Ledger API",
            consumer_version=candidate.version_number,
            sha=sha,
            content=document,
            specification_version=document["metadata"]["pactSpecification"]["version"],
            interaction_count=len(document["interactions"]),
        )

    def publish(self, _db: Any, tenant_id: str, provider: str, consumer: str, sha: str, request: Any, **kwargs: Any):
        number = 1 + sum(1 for item in self.published if item["sha"] == sha)
        self.published.append(
            {"tenant": tenant_id, "provider": provider, "consumer": consumer, "sha": sha, "request": request, **kwargs}
        )
        return VerificationResultRecord(
            id=f"r-{len(self.published)}",
            number=number,
            consumer_slug=consumer,
            consumer_name=consumer,
            provider_slug=provider,
            provider_name="Ledger API",
            provider_version=request.provider_version,
            sha=sha,
            success=request.success,
            test_results=request.test_results,
            verified_by=request.verified_by,
        )

    def record_run(self, tenant_id: str, run: Any, *, actor: Any):
        self.evidence.append(run)

        class _Recorded:
            created = True
            record = type("Record", (), {"id": f"run-{len(self.evidence)}"})()

        return _Recorded()

    def fire(self, _db: Any, _tenant: str, base: str, result: VerificationResultRecord) -> List[str]:
        assert base == _BASE
        self.webhooks.append(result)
        return ["fired-1"]

    def record_branch(self, _db: Any, tenant_id: str, provider: str, version: str, *, actor: Any, branch: str):
        self.branch_versions.append((provider, version, branch))


def _verify(
    broker: _Broker,
    api: LedgerApi,
    *,
    allow_mutating_target: bool = True,
    resolve: Any = None,
    states: Any = (),
    **request: Any,
) -> PactVerifyResponse:
    """Run the service with the stores faked and the transport pointed at ``api``."""
    body = PactVerifyRequest(
        **{"target_ref": "ledger-staging", "provider_version": "4f1e2d0", "verification": _EVERYTHING, **request}
    )
    client = api.client()
    with ExitStack() as stack:
        for name, fake in (
            ("list_pact_candidates", broker.list_pact_candidates),
            ("get_pact_by_sha", broker.get_pact_by_sha),
            ("publish_verification_result", broker.publish),
            ("record_run", broker.record_run),
            ("fire_verification_events", broker.fire),
            ("record_broker_version", broker.record_branch),
        ):
            stack.enter_context(patch(f"{_SERVICE}.{name}", side_effect=fake))
        stack.enter_context(patch(f"{_SERVICE}.load_pending_evidence", return_value=NO_EVIDENCE))
        stack.enter_context(patch(f"{_SERVICE}.list_states", return_value=list(states)))
        stack.enter_context(
            patch(
                f"{_SERVICE}.resolve_target",
                side_effect=resolve or (lambda *a, **k: target(allow_mutating=allow_mutating_target)),
            )
        )
        stack.enter_context(patch("app.contract_runner.build_guarded_client", side_effect=lambda **_k: api.client()))
        stack.enter_context(
            patch("app.pact_provider_state_handler.build_guarded_client", side_effect=lambda **_k: api.client())
        )
        try:
            return verify_provider_pacts(None, _TENANT, "ledger-api", body, actor=_ACTOR, broker_base=_BASE)
        finally:
            client.close()


# ---------------------------------------------------------------------------
# A conformant provider
# ---------------------------------------------------------------------------


def test_fixtures_from_pact_js_jvm_and_go_verify_and_publish_success() -> None:
    broker, api = _Broker([PACT_JS, PACT_JVM, PACT_GO]), LedgerApi()
    response = _verify(broker, api, provider_branch="main", build_url="https://ci.example.test/builds/77")

    assert (response.success, response.outcome, response.provider) == (True, "passed", "ledger-api")
    assert (response.provider_version, response.provider_branch) == ("4f1e2d0", "main")
    assert response.target.slug == "ledger-staging" and response.target.allow_mutating_methods is True
    assert {pact.consumer: pact.outcome for pact in response.pacts} == {
        "billing-service": "passed",
        "orders-ui": "passed",
        "reporting-job": "passed",
    }
    assert sorted(api.sent) == sorted(
        ["GET /invoices/1042", "GET /invoices/9999", "GET /invoices", "POST /invoices", "GET /summary"]
    )
    # One result per pact, as a native verifier would publish it.
    assert len(broker.published) == 3
    for stored in broker.published:
        request = stored["request"]
        assert (stored["tenant"], stored["provider"]) == (_TENANT, "ledger-api")
        assert request.success is True and request.provider_version == "4f1e2d0"
        assert request.build_url == "https://ci.example.test/builds/77"
        assert request.verified_by == {"implementation": "apiome-pact-verifier", "version": "1"}
        assert all(entry["success"] for entry in request.test_results)
        assert stored["actor"] is _ACTOR
    assert broker.branch_versions == [("ledger-api", "4f1e2d0", "main")]
    for pact in response.pacts:
        assert pact.published and pact.not_published_reason is None
        assert pact.result is not None and pact.result.number == 1 and pact.result.triggered_webhooks == 1
        assert pact.result.url == (
            f"{_BASE}/pacts/provider/ledger-api/consumer/{pact.consumer}/pact-version/"
            f"{pact.pact_version_sha}/verification-results/1"
        )
        assert pact.suite_digest.startswith("sha256:")
        assert pact.evidence_run_id is not None
    assert len(broker.webhooks) == 3


def test_evidence_is_recorded_per_pact_against_the_suite_digest() -> None:
    broker = _Broker([PACT_JS])
    response = _verify(broker, LedgerApi(), context={"commit": "4f1e2d0"})
    (run,) = broker.evidence
    assert run.suite_digest == response.pacts[0].suite_digest
    assert (run.target_ref, run.runner_name) == ("ledger-staging", "apiome-pact-verifier")
    assert run.source["kind"] == "pact"
    assert run.context["commit"] == "4f1e2d0" and run.context["pact_consumer"] == "billing-service"
    assert len(run.operations) == 2


# ---------------------------------------------------------------------------
# A drifted provider
# ---------------------------------------------------------------------------


def test_a_drifted_provider_publishes_a_failure_that_names_what_drifted() -> None:
    drifted = LedgerApi(
        {
            "GET /summary": lambda _request: httpx.Response(
                200,
                json={"year": "2026", "entries": [{"account": "40", "balance": 1.5}], "currency": "USD"},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        }
    )
    broker = _Broker([PACT_JS, PACT_GO])
    response = _verify(broker, drifted)

    assert (response.success, response.outcome) == (False, "failed")
    failed = next(pact for pact in response.pacts if pact.consumer == "reporting-job")
    assert failed.outcome == "failed" and failed.counts.failed == 1
    (interaction,) = failed.interactions
    assert interaction.description == "a request for the ledger summary"
    assert {(m.field, m.rule) for m in interaction.mismatches} == {
        ("/year", "type"),
        ("/entries/0/account", "regex"),
        ("/currency", "equality"),
    }
    stored = next(item for item in broker.published if item["consumer"] == "reporting-job")
    assert stored["request"].success is False
    (entry,) = stored["request"].test_results
    assert entry["success"] is False
    assert {m["identifier"] for m in entry["mismatches"]} == {"/year", "/entries/0/account", "/currency"}
    # The other pact is unaffected and still published as verified.
    assert next(item for item in broker.published if item["consumer"] == "billing-service")["request"].success is True


def test_a_pending_pact_that_fails_is_published_as_failed_but_does_not_fail_the_run() -> None:
    drifted = LedgerApi({"GET /invoices/9999": lambda _request: httpx.Response(200, json={})})
    broker = _Broker([PACT_JS])
    response = _verify(broker, drifted, selection={"includePendingStatus": True})
    (pact,) = response.pacts
    assert (pact.pending, pact.outcome) == (True, "failed")
    assert (response.success, response.outcome) == (True, "passed")
    assert broker.published[0]["pact_pending"] is True and broker.published[0]["request"].success is False


# ---------------------------------------------------------------------------
# Runs that prove nothing publish nothing
# ---------------------------------------------------------------------------


def test_an_interaction_with_a_state_is_skipped_by_default_and_nothing_is_published() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    response = _verify(broker, api, verification=PactVerificationOptions())
    (pact,) = response.pacts
    assert (pact.outcome, pact.published, pact.not_published_reason) == ("incomplete", False, NOT_PUBLISHED_INCOMPLETE)
    assert (pact.counts.passed, pact.counts.skipped) == (1, 1)
    assert pact.interactions[0].code == "provider-state-not-set-up"
    assert api.sent == ["GET /invoices/9999"]
    assert broker.published == [] and broker.webhooks == []
    assert (response.success, response.outcome) == (False, "incomplete")
    assert len(broker.evidence) == 1  # the run is still evidence


def test_an_unreachable_target_is_incomplete_not_failed() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    broker = _Broker([PACT_GO])
    response = _verify(broker, LedgerApi({"GET /summary": down}))
    (pact,) = response.pacts
    assert (pact.outcome, pact.counts.errored, pact.published) == ("incomplete", 1, False)
    assert pact.interactions[0].code == "transport-error"
    assert broker.published == []


def test_a_dry_run_replays_everything_and_publishes_nothing() -> None:
    broker, api = _Broker([PACT_JVM]), LedgerApi()
    response = _verify(broker, api, publish=False, provider_branch="main")
    (pact,) = response.pacts
    assert (pact.outcome, pact.published, pact.not_published_reason) == ("passed", False, NOT_PUBLISHED_DISABLED)
    assert response.success is True
    assert broker.published == [] and broker.branch_versions == []
    assert len(api.sent) == 2


def test_no_selected_pacts_is_not_a_success() -> None:
    broker, api = _Broker([]), LedgerApi()
    response = _verify(broker, api, provider_branch="main")
    assert (response.success, response.outcome, response.pacts) == (False, "no-pacts", [])
    assert api.sent == [] and broker.branch_versions == []


# ---------------------------------------------------------------------------
# The target policy
# ---------------------------------------------------------------------------


def test_a_run_cannot_widen_the_target_policy() -> None:
    broker, api = _Broker([PACT_JVM]), LedgerApi()
    response = _verify(broker, api, allow_mutating_target=False)
    (pact,) = response.pacts
    create = pact.interactions[1]
    assert (create.outcome, create.code) == ("skipped", "mutating-method-blocked")
    assert "a run cannot override" in (create.message or "")
    assert "POST /invoices" not in api.sent
    assert (pact.outcome, pact.published) == ("incomplete", False)
    assert response.target.allow_mutating_methods is False


def test_a_mutating_interaction_needs_the_runs_opt_in_too() -> None:
    broker, api = _Broker([PACT_JVM]), LedgerApi()
    response = _verify(broker, api, verification=PactVerificationOptions())
    assert response.pacts[0].interactions[1].code == "mutating-method-blocked"
    assert api.sent == ["GET /invoices"]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_selectors_choose_the_pacts() -> None:
    broker = _Broker([PACT_JS, PACT_JVM, PACT_GO], branches={PACT_JVM: ("feat-x",)})
    response = _verify(broker, LedgerApi(), selection={"consumerVersionSelectors": [{"branch": "feat-x"}]})
    assert [pact.consumer for pact in response.pacts] == ["orders-ui"]
    assert "feat-x" in response.pacts[0].short_description


def test_the_provider_branch_feeds_matching_branch_selectors() -> None:
    broker = _Broker([PACT_JS, PACT_GO], branches={PACT_GO: ("release-9",)})
    response = _verify(
        broker,
        LedgerApi(),
        provider_branch="release-9",
        selection={"consumerVersionSelectors": [{"matchingBranch": True}]},
    )
    assert [pact.consumer for pact in response.pacts] == ["reporting-job"]


def test_a_malformed_selector_is_refused_before_anything_is_sent() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    with pytest.raises(PactPublicationError) as refused:
        _verify(broker, api, selection={"consumerVersionSelectors": [{"tag": "a", "branch": "b"}]})
    assert refused.value.code == CODE_SELECTOR_INVALID
    assert api.sent == []


def test_more_pacts_than_one_run_takes_is_refused_with_advice() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    with patch(f"{_SERVICE}.MAX_PACTS_PER_RUN", 0), pytest.raises(PactVerifierError) as refused:
        _verify(broker, api)
    assert refused.value.code == CODE_TOO_MANY_PACTS
    assert "Narrow the selection" in str(refused.value)
    assert api.sent == [] and broker.published == []


# ---------------------------------------------------------------------------
# Runs that cannot start
# ---------------------------------------------------------------------------


def test_an_unknown_provider_is_the_stores_refusal() -> None:
    broker = _Broker([PACT_JS])
    body = PactVerifyRequest(target_ref="t", provider_version="1")
    with (
        patch(f"{_SERVICE}.list_pact_candidates", side_effect=broker.list_pact_candidates),
        pytest.raises(PacticipantValidationError) as refused,
    ):
        verify_provider_pacts(None, _TENANT, "nobody", body, actor=_ACTOR, broker_base=_BASE)
    assert refused.value.code == "pacticipant-not-found"


def test_an_unresolvable_target_stops_the_run() -> None:
    def refuse(*_args: Any, **_kwargs: Any):
        raise TargetValidationError(CODE_NOT_FOUND, "no target 'ledger-staging'")

    broker, api = _Broker([PACT_JS]), LedgerApi()
    with pytest.raises(TargetValidationError):
        _verify(broker, api, resolve=refuse)
    assert api.sent == [] and broker.published == [] and broker.branch_versions == []


def test_the_target_is_resolved_for_http_by_the_acting_principal() -> None:
    seen: Dict[str, Any] = {}

    def resolve(tenant_id: str, ref: str, *, actor: Any, protocol: str, **_kwargs: Any):
        seen.update(tenant=tenant_id, ref=ref, actor=actor, protocol=protocol)
        return target(allow_mutating=True)

    _verify(_Broker([PACT_GO]), LedgerApi(), resolve=resolve)
    assert (seen["tenant"], seen["ref"], seen["protocol"]) == (_TENANT, "ledger-staging", "http")
    assert (seen["actor"].user_id, seen["actor"].kind) == (_ACTOR.user_id, "api_key")


def test_an_unusable_credential_refuses_before_a_single_request() -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    with patch(f"{_SERVICE}.materialize_auth_headers", side_effect=AuthResolutionError("variable unset")):
        with pytest.raises(PactVerifierError) as refused:
            _verify(broker, api)
    assert refused.value.code == CODE_TARGET_AUTH_UNAVAILABLE
    assert api.sent == []


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("provider_version", "   ", "pacticipant-invalid-version"),
        ("provider_branch", "bad\nbranch", "pacticipant-invalid-branch"),
        ("build_url", "ftp://ci.example.test/1", "pacticipant-invalid-url"),
    ],
)
def test_a_malformed_version_branch_or_build_url_is_refused(field: str, value: str, code: str) -> None:
    broker, api = _Broker([PACT_JS]), LedgerApi()
    with pytest.raises(PacticipantValidationError) as refused:
        _verify(broker, api, **{field: value})
    assert refused.value.code == code
    assert api.sent == []


def test_a_storage_fault_in_evidence_does_not_lose_the_verification() -> None:
    broker, api = _Broker([PACT_GO]), LedgerApi()

    def broken(*_args: Any, **_kwargs: Any):
        raise RuntimeError("evidence store down")

    broker.record_run = broken  # type: ignore[method-assign]
    response = _verify(broker, api)
    (pact,) = response.pacts
    assert pact.evidence_run_id is None
    assert pact.outcome == "passed" and pact.published


def test_no_provider_state_handler_without_registered_states() -> None:
    with patch(f"{_SERVICE}.list_states", return_value=[]):
        assert provider_state_handler(None, _TENANT, _PROVIDER, target()) is None


# ---------------------------------------------------------------------------
# The provider-state registry (PFX-3.3)
# ---------------------------------------------------------------------------

_STATE_CHANGE = "POST /_pact/states"


def _registered(name: str = "invoice 1042 exists", **fields: Any) -> ProviderStateRecord:
    moment = target().resolved_at
    return ProviderStateRecord(
        id="33333333-3333-4333-8333-333333333333",
        provider="ledger-api",
        name=name,
        parameters=[
            StateParameter.model_validate(p) for p in fields.pop("parameters", [{"name": "id", "required": True}])
        ],
        setup=StateSetup.model_validate(fields.pop("setup", {"kind": "state_change", "url": "/_pact/states"})),
        created_at=moment,
        updated_at=moment,
    )


def _state_api(teardown_status: int = 200, setup_status: int = 200) -> LedgerApi:
    def state_change(request: httpx.Request) -> httpx.Response:
        action = json.loads(request.content)["action"]
        return httpx.Response(setup_status if action == "setup" else teardown_status)

    return LedgerApi({_STATE_CHANGE: state_change})


def test_a_registered_state_is_set_up_around_its_interaction_and_the_pact_publishes() -> None:
    broker, api = _Broker([PACT_JS]), _state_api()
    response = _verify(broker, api, verification=PactVerificationOptions(), states=[_registered()])
    (pact,) = response.pacts
    assert (pact.outcome, pact.published) == ("passed", True)
    assert api.sent == [_STATE_CHANGE, "GET /invoices/1042", _STATE_CHANGE, "GET /invoices/9999"]
    assert [json.loads(r.content) for r in api.requests if r.method == "POST"] == [
        {"state": "invoice 1042 exists", "params": {"id": 1042}, "action": "setup"},
        {"state": "invoice 1042 exists", "params": {"id": 1042}, "action": "teardown"},
    ]
    assert pact.interactions[0].states_set_up is True
    assert pact.state_teardown_failures == []


def test_an_unregistered_state_is_held_back_before_anything_is_sent() -> None:
    broker, api = _Broker([PACT_JS]), _state_api()
    response = _verify(
        broker, api, verification=PactVerificationOptions(), states=[_registered("some other state")]
    )
    (pact,) = response.pacts
    assert pact.outcome == "incomplete" and not pact.published
    assert pact.interactions[0].code == "provider-state-not-registered"
    assert "'invoice 1042 exists'" in (pact.interactions[0].message or "")
    assert api.sent == ["GET /invoices/9999"]


def test_an_unregistered_state_can_still_be_replayed_without_setup_when_asked() -> None:
    broker, api = _Broker([PACT_JS]), _state_api()
    options = PactVerificationOptions(replay_without_state_setup=True)
    response = _verify(broker, api, verification=options, states=[_registered("some other state")])
    (pact,) = response.pacts
    assert pact.outcome == "passed"
    assert pact.interactions[0].states_set_up is False
    assert _STATE_CHANGE not in api.sent


def test_a_missing_required_parameter_holds_the_interaction_back() -> None:
    broker, api = _Broker([PACT_JS]), _state_api()
    state = _registered(parameters=[{"name": "id", "required": True}, {"name": "customer", "required": True}])
    response = _verify(broker, api, verification=PactVerificationOptions(), states=[state])
    (pact,) = response.pacts
    assert pact.interactions[0].code == "provider-state-param-missing"
    assert _STATE_CHANGE not in api.sent


def test_a_failed_setup_skips_the_interaction_with_the_call_named() -> None:
    broker, api = _Broker([PACT_JS]), _state_api(setup_status=500)
    response = _verify(broker, api, verification=PactVerificationOptions(), states=[_registered()])
    (pact,) = response.pacts
    assert pact.outcome == "incomplete"
    assert pact.interactions[0].code == "provider-state-setup-failed"
    assert "POST /_pact/states answered 500" in (pact.interactions[0].message or "")
    assert "GET /invoices/1042" not in api.sent


def test_a_failed_teardown_is_reported_and_the_result_stands() -> None:
    broker, api = _Broker([PACT_JS]), _state_api(teardown_status=503)
    response = _verify(broker, api, verification=PactVerificationOptions(), states=[_registered()])
    (pact,) = response.pacts
    assert (pact.outcome, pact.published) == ("passed", True)
    assert pact.state_teardown_failures == [
        "teardown of 'invoice 1042 exists' failed: POST /_pact/states answered 503"
    ]


def test_a_state_change_on_a_target_that_forbids_mutating_is_held_back() -> None:
    broker, api = _Broker([PACT_JS]), _state_api()
    response = _verify(
        broker, api, verification=PactVerificationOptions(), states=[_registered()], allow_mutating_target=False
    )
    (pact,) = response.pacts
    assert pact.interactions[0].code == "provider-state-setup-blocked"
    assert _STATE_CHANGE not in api.sent


def test_the_registry_handler_is_built_from_the_provider_s_states() -> None:
    with patch(f"{_SERVICE}.list_states", return_value=[_registered()]):
        handler = provider_state_handler(None, _TENANT, _PROVIDER, target(), {"Authorization": "x"})
    assert handler is not None and set(handler.registry) == {"invoice 1042 exists"}
    assert handler.auth_headers == {"Authorization": "x"}
