"""One consumer model — a published pact refreshes the consumer's surface — PFX-7.1 (#6961).

What :mod:`app.pact_consumer_sync` decides without Postgres:

* a new pact becomes the consumer's next contract revision in the provider's project;
* a provider not bound to a project, or a project without a usable specification, is *skipped*
  with a reason code (nothing silently dropped);
* the consumer pacticipant is bound to the registry consumer the first time only;
* the same pact against the same specification revision stores nothing (``unchanged``);
* a re-published pact is not a refresh, and a fault is reported as ``error``, never raised;
* unresolved interactions are counted and carried into the notices.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from app import pact_consumer_sync as sync
from app.consumer_contract import (
    SOURCE_PACT,
    ConsumerContractRecord,
    ConsumerRecord,
    ConsumerValidationError,
)
from app.consumer_contract_store import ConsumerActor
from app.consumer_surface import SpecIndex
from app.pact_publication import PactRecord, PublishedPact
from app.pact_publication_store import PublishOutcome
from app.pacticipant import PacticipantRecord

ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SHA = "a" * 64
OAS = {
    "openapi": "3.0.3",
    "info": {"title": "Ledger", "version": "1"},
    "paths": {
        "/invoices/{id}": {
            "get": {
                "operationId": "getInvoice",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "properties": {"total": {"type": "integer"}}}
                            }
                        },
                    }
                },
            }
        }
    },
}
VERSION_ROW = {"id": "33333333-3333-4333-8333-333333333333", "version_id": "1.0.0"}


def _pacticipant(slug: str, name: str, **extra: Any) -> PacticipantRecord:
    return PacticipantRecord(id=f"{slug}-id", tenant_id=TENANT, slug=slug, name=name, **extra)


CONSUMER = _pacticipant("billing", "Billing")
CONSUMER_ROW = ConsumerRecord(id="c-1", tenant_id=TENANT, project_id=PROJECT, slug="billing", name="Billing")


def _pact(interactions: List[Dict[str, Any]] | None = None) -> PactRecord:
    return PactRecord(
        consumer_slug="billing",
        consumer_name="Billing",
        provider_slug="ledger",
        provider_name="Ledger",
        consumer_version="1.2.3",
        sha=SHA,
        content={
            "consumer": {"name": "Billing"},
            "provider": {"name": "Ledger"},
            "interactions": interactions
            if interactions is not None
            else [
                {
                    "description": "an invoice",
                    "request": {"method": "GET", "path": "/invoices/42"},
                    "response": {"status": 200, "body": {"total": 5}},
                }
            ],
        },
    )


def _outcome(pact: PactRecord, **flags: Any) -> PublishOutcome:
    published = PublishedPact(pact=pact, **{"created": True, **flags})
    return PublishOutcome(CONSUMER, MagicMock(), [published])


def _run(outcome: PublishOutcome, *, provider: PacticipantRecord, current: Any = None) -> sync.ConsumerRefreshRun:
    """Run the refresh with the stores stood in for; returns the run and exposes the mocks."""
    stored = MagicMock(side_effect=lambda *a, **k: MagicMock(revision=4))
    patches = {
        "get_pacticipant": MagicMock(return_value=provider),
        "resolve_version": MagicMock(return_value=VERSION_ROW),
        "_spec_index_for": MagicMock(side_effect=lambda *a: SpecIndex(OAS)),
        "ensure_consumer": MagicMock(return_value=CONSUMER_ROW),
        "update_pacticipant": MagicMock(),
        "current_contract": MagicMock(
            side_effect=current if isinstance(current, Exception) else None, return_value=current
        ),
        "record_contract": stored,
    }
    with patch.multiple(sync, **patches):
        run = sync.refresh_consumer_contracts(MagicMock(), TENANT, "acme", outcome, actor=ACTOR)
    run.mocks = patches  # type: ignore[attr-defined]
    return run


def _no_current() -> Exception:
    return ConsumerValidationError("consumer-contract-not-found", "none")


def test_new_pact_stores_next_revision_and_binds_consumer() -> None:
    run = _run(_outcome(_pact()), provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=_no_current())
    (entry,) = run.entries
    assert entry.status == sync.STATUS_REFRESHED
    assert entry.revision == 4
    assert entry.resolved_count == 1 and entry.unresolved_count == 0
    mocks = run.mocks  # type: ignore[attr-defined]
    kwargs = mocks["record_contract"].call_args.kwargs
    assert kwargs["source"] == SOURCE_PACT and kwargs["source_digest"] == f"sha256:{SHA}"
    assert kwargs["version_id"] == VERSION_ROW["id"]
    assert mocks["update_pacticipant"].call_count == 1  # first publish binds the pacticipant


def test_already_bound_consumer_is_not_rebound() -> None:
    bound = _pacticipant("billing", "Billing", consumer_id="c-1")
    outcome = PublishOutcome(bound, MagicMock(), [PublishedPact(pact=_pact(), created=True)])
    run = _run(outcome, provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=_no_current())
    assert run.mocks["update_pacticipant"].call_count == 0  # type: ignore[attr-defined]


def test_unbound_provider_is_skipped_with_reason() -> None:
    run = _run(_outcome(_pact()), provider=_pacticipant("ledger", "Ledger"))
    (entry,) = run.entries
    assert entry.status == sync.STATUS_SKIPPED
    assert entry.reason_code == sync.REASON_PROVIDER_NOT_BOUND
    assert run.mocks["record_contract"].call_count == 0  # type: ignore[attr-defined]
    (notice,) = sync.refresh_notices(run)
    assert notice["type"] == "warning" and "not bound to a project" in notice["text"]


def test_project_without_specification_is_skipped() -> None:
    provider = _pacticipant("ledger", "Ledger", project_id=PROJECT)
    with patch.multiple(
        sync,
        get_pacticipant=MagicMock(return_value=provider),
        resolve_version=MagicMock(side_effect=ConsumerValidationError("consumer-version-not-found", "no versions")),
    ):
        run = sync.refresh_consumer_contracts(MagicMock(), TENANT, "acme", _outcome(_pact()), actor=ACTOR)
    (entry,) = run.entries
    assert entry.status == sync.STATUS_SKIPPED and entry.reason_code == sync.REASON_NO_SPECIFICATION


def test_same_pact_and_specification_is_unchanged() -> None:
    current = ConsumerContractRecord(
        id="r",
        consumer_id="c-1",
        revision=3,
        source=SOURCE_PACT,
        version_id=VERSION_ROW["id"],
        source_digest=f"sha256:{SHA}",
        unresolved_count=1,
    )
    run = _run(_outcome(_pact()), provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=current)
    (entry,) = run.entries
    assert entry.status == sync.STATUS_UNCHANGED and entry.revision == 3
    assert run.mocks["record_contract"].call_count == 0  # type: ignore[attr-defined]
    assert sync.refresh_notices(run) == []


def test_new_specification_revision_refreshes_even_for_same_pact() -> None:
    current = ConsumerContractRecord(
        id="r", consumer_id="c-1", revision=3, source=SOURCE_PACT, version_id="older", source_digest=f"sha256:{SHA}"
    )
    run = _run(_outcome(_pact()), provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=current)
    assert run.entries[0].status == sync.STATUS_REFRESHED


def test_unresolved_interactions_are_counted_and_noticed() -> None:
    pact = _pact(
        [
            {
                "description": "a gone endpoint",
                "request": {"method": "GET", "path": "/retired"},
                "response": {"status": 200},
            }
        ]
    )
    run = _run(_outcome(pact), provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=_no_current())
    (entry,) = run.entries
    assert entry.unresolved_count >= 1
    assert sync.refresh_notices(run)[0]["type"] == "warning"
    assert entry.to_dict()["unresolvedCount"] == entry.unresolved_count


def test_republished_pact_is_not_a_refresh() -> None:
    outcome = _outcome(_pact(), created=False, replaced=False, new_content=False)
    run = _run(outcome, provider=_pacticipant("ledger", "Ledger", project_id=PROJECT), current=_no_current())
    assert run.entries == []


def test_fault_is_reported_not_raised() -> None:
    with patch.object(sync, "get_pacticipant", side_effect=RuntimeError("boom")):
        run = sync.refresh_consumer_contracts(MagicMock(), TENANT, "acme", _outcome(_pact()), actor=ACTOR)
    (entry,) = run.entries
    assert entry.status == sync.STATUS_ERROR and entry.reason_code == "refresh-failed"
    assert sync.refresh_notices(run)[0]["type"] == "error"


def test_skipped_entry_serialises_reason_without_counts() -> None:
    body = sync.ConsumerRefresh(
        consumer="billing", provider="ledger", status=sync.STATUS_SKIPPED, reason_code="x", reason="why"
    ).to_dict()
    assert body == {
        "consumer": "billing",
        "provider": "ledger",
        "status": "skipped",
        "reasonCode": "x",
        "reason": "why",
    }
