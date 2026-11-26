"""Pacticipant owners and the Pact findings routed to them — PFX-6.4 (#6956).

:mod:`app.pact_owner_routing` with owner routing faked:

* which owner a finding goes to: the pacticipant's own confirmed owner, else its consumer-registry
  entry's, else its project's, else the pacticipant itself (recorded as unowned);
* a failed verification tells the provider's and the consumer's owners once each, the same team
  once; a passing one tells nobody;
* nothing raises: a vanished pacticipant, a failed owner read or a failing router are reported in
  the outcome or the log, never to the caller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from app import pact_owner_routing as subject
from app.owner_routing import OwnerRecipients, OwnerTeam, RoutingOutcome
from app.pact_owner_routing import (
    KIND_PACTICIPANT,
    OwnerTarget,
    notify_failed_verification,
    resolve_owner_target,
    route_pacticipant_finding,
)
from app.pacticipant import CODE_NOT_FOUND, PacticipantRecord, PacticipantValidationError
from app.verification_result import VerificationResultRecord

TENANT = "11111111-1111-4111-8111-111111111111"
SHA = "b" * 64

PROVIDER = PacticipantRecord(
    id="p-1", tenant_id=TENANT, slug="ledger-api", name="Ledger API", project_id="proj-ledger"
)
CONSUMER = PacticipantRecord(
    id="c-1", tenant_id=TENANT, slug="billing-service", name="Billing Service", consumer_id="reg-billing"
)
LONE = PacticipantRecord(id="c-2", tenant_id=TENANT, slug="lone-app", name="Lone App")


def _result(*, success: bool = False, pending: Optional[bool] = None, consumer: PacticipantRecord = CONSUMER):
    return VerificationResultRecord(
        id="r-9",
        number=3,
        consumer_slug=consumer.slug,
        consumer_name=consumer.name,
        provider_slug=PROVIDER.slug,
        provider_name=PROVIDER.name,
        provider_version="4f1e2d0",
        consumer_version="1.4.0",
        sha=SHA,
        success=success,
        build_url="https://ci.example.com/build/7",
        pact_pending=pending,
    )


class _Routing:
    """Owner routing and the pacticipant registry, faked."""

    def __init__(
        self,
        owners: Optional[Dict[Tuple[str, str], str]] = None,
        *,
        status: str = "routed",
        pacticipants: Optional[Dict[str, PacticipantRecord]] = None,
        owner_error: Optional[Tuple[str, str]] = None,
    ) -> None:
        self.owners = owners or {}
        self.status = status
        self.pacticipants = pacticipants if pacticipants is not None else {
            p.slug: p for p in (PROVIDER, CONSUMER, LONE)
        }
        self.owner_error = owner_error
        self.findings: List[Any] = []
        self.owner_reads: List[Tuple[str, str]] = []

    def owner(self, _db: Any, _tenant: str, kind: str, entity_id: str) -> Optional[OwnerRecipients]:
        self.owner_reads.append((kind, entity_id))
        if self.owner_error == (kind, entity_id):
            raise RuntimeError("owner read failed")
        team = self.owners.get((kind, entity_id))
        return None if team is None else OwnerRecipients(team=OwnerTeam(id=team, slug=team, name=team.title()))

    def route(self, _db: Any, finding: Any) -> RoutingOutcome:
        self.findings.append(finding)
        return RoutingOutcome(status=self.status)

    def pacticipant(self, _db: Any, _tenant: str, ref: str) -> PacticipantRecord:
        if ref not in self.pacticipants:
            raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant {ref}")
        return self.pacticipants[ref]

    def __enter__(self) -> "_Routing":
        self._patches = [
            patch.object(subject, "owner_recipients", side_effect=self.owner),
            patch.object(subject, "route_owner_finding_safely", side_effect=self.route),
            patch.object(subject, "get_pacticipant", side_effect=self.pacticipant),
        ]
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        for item in self._patches:
            item.stop()


# ---------------------------------------------------------------------------
# Which owner
# ---------------------------------------------------------------------------


def test_the_pacticipants_own_owner_comes_first() -> None:
    with _Routing({("pacticipant", "c-1"): "checkout", ("consumer", "reg-billing"): "billing"}) as fake:
        target = resolve_owner_target(None, TENANT, CONSUMER)
    assert target == OwnerTarget(kind=KIND_PACTICIPANT, entity_id="c-1", team_id="checkout")
    assert fake.owner_reads == [("pacticipant", "c-1")]


def test_without_one_the_consumer_registry_entry_then_the_project_owns_it() -> None:
    with _Routing({("consumer", "reg-billing"): "billing"}):
        assert resolve_owner_target(None, TENANT, CONSUMER) == OwnerTarget("consumer", "reg-billing", "billing")
    with _Routing({("project", "proj-ledger"): "ledger"}) as fake:
        assert resolve_owner_target(None, TENANT, PROVIDER) == OwnerTarget("project", "proj-ledger", "ledger")
    assert fake.owner_reads == [("pacticipant", "p-1"), ("project", "proj-ledger")]


def test_with_no_owner_anywhere_the_pacticipant_itself_is_the_unowned_target() -> None:
    with _Routing() as fake:
        target = resolve_owner_target(None, TENANT, CONSUMER)
    assert target == OwnerTarget(kind=KIND_PACTICIPANT, entity_id="c-1", team_id=None)
    assert fake.owner_reads == [("pacticipant", "c-1"), ("consumer", "reg-billing")]


def test_a_failed_owner_read_moves_on_to_the_next_candidate() -> None:
    with _Routing({("consumer", "reg-billing"): "billing"}, owner_error=("pacticipant", "c-1")):
        assert resolve_owner_target(None, TENANT, CONSUMER).kind == "consumer"


def test_a_finding_carries_the_pacticipant_and_where_its_owner_was_found() -> None:
    with _Routing({("consumer", "reg-billing"): "billing"}) as fake:
        outcome = route_pacticipant_finding(
            None, TENANT, CONSUMER, summary="s", link="/x", finding_id="f-1", details={"kind": "k"}
        )
    assert outcome.status == "routed"
    (finding,) = fake.findings
    assert (finding.entity_kind, finding.entity_id) == ("consumer", "reg-billing")
    assert finding.entity_name == "Billing Service"
    assert finding.finding_type == "owner_verification_drift"
    assert finding.details == {"kind": "k", "pacticipant": "billing-service", "ownerSource": "consumer"}


# ---------------------------------------------------------------------------
# Failed verifications
# ---------------------------------------------------------------------------


def test_a_passing_result_tells_nobody() -> None:
    with _Routing({("pacticipant", "p-1"): "ledger"}) as fake:
        assert notify_failed_verification(None, TENANT, _result(success=True)) == {}
    assert fake.findings == [] and fake.owner_reads == []


def test_a_failed_result_tells_the_provider_and_the_consumer_owners() -> None:
    owners = {("pacticipant", "p-1"): "ledger", ("pacticipant", "c-1"): "billing"}
    with _Routing(owners) as fake:
        outcomes = notify_failed_verification(None, TENANT, _result())
    assert outcomes == {"provider": "routed", "consumer": "routed"}
    provider, consumer = fake.findings
    assert (provider.entity_kind, provider.entity_id) == ("pacticipant", "p-1")
    assert (consumer.entity_kind, consumer.entity_id) == ("pacticipant", "c-1")
    assert provider.details["role"] == "provider" and consumer.details["role"] == "consumer"
    assert provider.finding_id == "r-9"
    assert provider.link == "/ade/dashboard/pacts/pacticipants/ledger-api/verification/results/r-9"
    assert provider.summary == (
        "Verification failed: Ledger API 4f1e2d0 did not verify Billing Service's pact (version 1.4.0)"
    )
    assert provider.details["kind"] == "pact-verification-failed"
    assert provider.details["pactVersionSha"] == SHA and provider.details["verificationNumber"] == 3
    assert provider.details["pending"] is False


def test_a_pending_pacts_failure_says_it_does_not_block_deploys() -> None:
    with _Routing({("pacticipant", "p-1"): "ledger"}) as fake:
        notify_failed_verification(None, TENANT, _result(pending=True))
    assert fake.findings[0].summary.endswith("the pact is pending, so it does not block deploys")
    assert fake.findings[0].details["pending"] is True


def test_one_team_owning_both_parties_is_told_once() -> None:
    owners = {("pacticipant", "p-1"): "platform", ("pacticipant", "c-1"): "platform"}
    with _Routing(owners) as fake:
        outcomes = notify_failed_verification(None, TENANT, _result())
    assert outcomes == {"provider": "routed", "consumer": "same-team"}
    assert [f.entity_id for f in fake.findings] == ["p-1"]


def test_ownerless_parties_are_each_recorded_as_unowned() -> None:
    with _Routing(status="unowned") as fake:
        outcomes = notify_failed_verification(None, TENANT, _result(consumer=LONE))
    assert outcomes == {"provider": "unowned", "consumer": "unowned"}
    assert [(f.entity_kind, f.entity_id) for f in fake.findings] == [("pacticipant", "p-1"), ("pacticipant", "c-2")]


def test_a_party_deleted_since_is_reported_as_skipped() -> None:
    with _Routing({("pacticipant", "c-1"): "billing"}, pacticipants={CONSUMER.slug: CONSUMER}) as fake:
        outcomes = notify_failed_verification(None, TENANT, _result())
    assert outcomes == {"provider": "skipped", "consumer": "routed"}
    assert [f.entity_id for f in fake.findings] == ["c-1"]


def test_a_router_that_raises_never_reaches_the_caller(caplog: pytest.LogCaptureFixture) -> None:
    with _Routing({("pacticipant", "p-1"): "ledger"}) as fake:
        with patch.object(subject, "route_owner_finding_safely", side_effect=RuntimeError("boom")):
            outcomes = notify_failed_verification(None, TENANT, _result())
    assert outcomes == {}
    assert fake.findings == []
    assert "failed to notify owners of verification result r-9" in caplog.text
