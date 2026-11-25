"""Running bi-directional comparisons, against a stand-in database — PFX-2.3 (#6927).

What :mod:`app.bidirectional_store` decides without Postgres (the live-database behaviour is
``test_bidirectional_db``):

* a pair already compared is reported, not compared again, and neither document is read;
* a comparison is stored with the bi-directional columns, its verdict and number reported;
* a pair the engine refuses is stored as a failure with the reason;
* a failure to store is logged and reported as ``error``, never raised into the publish;
* the provider-version and pact limits report what they leave out;
* the pacts a new contract is compared with: default selectors, the branch, and the re-run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app import bidirectional_store as store
from app.bidirectional_verification import ContractTarget
from app.consumer_contract_store import ConsumerActor
from app.pact_publication import PactRecord, PublishedPact
from app.pact_publication_store import PublishOutcome
from app.pact_selectors import PactCandidate
from app.pacticipant import PacticipantRecord

FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"
ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
TENANT = "11111111-1111-4111-8111-111111111111"
SHA = "a" * 64


def _oas() -> Dict[str, Any]:
    return json.loads((FIXTURES / "ledger-api-3.1.json").read_bytes())


def _pact(total: Any = 1999) -> Dict[str, Any]:
    return {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "request": {"method": "GET", "path": "/invoices/42"},
                "response": {"status": 200, "body": {"id": 42, "total": total}},
            }
        ],
    }


def _pacticipant(slug: str, name: str, pid: str) -> PacticipantRecord:
    return PacticipantRecord(id=pid, tenant_id=TENANT, slug=slug, name=name)


PROVIDER = _pacticipant("ledger-api", "Ledger API", "prov-id")
CONSUMER = _pacticipant("billing-service", "Billing Service", "cons-id")


def _target(version: str = "p-1", seq: int = 1, branches: tuple = ("main",)) -> ContractTarget:
    return ContractTarget(f"v-{version}", version, seq, f"c-{version}", "b" * 64, branches)


class _Cursor:
    def __init__(self, fake: "_FakeDb") -> None:
        self.fake = fake
        self._row: Optional[Dict[str, Any]] = None

    def execute(self, sql: str, params: Any = None) -> None:
        self.fake.statements.append(sql)
        self._row = None
        if "INSERT INTO apiome.verification_result" in sql:
            if self.fake.fail_insert:
                raise RuntimeError("boom")
            self.fake.inserted.append(params)
            self._row = None if self.fake.conflict else {"number": len(self.fake.inserted)}

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._row


class _FakeDb:
    """Answers the statements of :mod:`app.bidirectional_store` from fixed data."""

    def __init__(self, *, existing: Optional[Dict[str, Any]] = None, pact: Any = None, contract: Any = None) -> None:
        self.existing = existing
        self.pact = _pact() if pact is None else pact
        self.contract = _oas() if contract is None else contract
        self.has_pact_version = True
        self.history: List[Dict[str, Any]] = []
        self.targets: List[Dict[str, Any]] = []
        self.conflict = False
        self.fail_insert = False
        self.inserted: List[Any] = []
        self.statements: List[str] = []
        self.reads: List[str] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.statements.append(sql)
        if "FROM apiome.provider_contract_publication p" in sql:
            return self.targets
        if "SELECT id::text AS id FROM apiome.pact_version" in sql:
            return [{"id": "pv-id"}] if self.has_pact_version else []
        if "comparison->>'verdict'" in sql:
            return [self.existing] if self.existing else []
        if "SELECT content FROM apiome.pact_version" in sql:
            self.reads.append("pact")
            return [{"content": self.pact}]
        if "SELECT content FROM apiome.provider_contract" in sql:
            self.reads.append("contract")
            return [{"content": self.contract}]
        if "r.kind = 'bidirectional'" in sql:
            return self.history
        raise AssertionError(f"unexpected statement: {sql}")

    def _guarded_tx(self, work: Any) -> Any:
        return work(_Cursor(self))


def _pair(db: _FakeDb, target: Optional[ContractTarget] = None) -> Any:
    pact = store._Pact(CONSUMER.id, CONSUMER.name, "1.0.0", SHA)
    return store._compare_pair(db, store._Documents(db), TENANT, PROVIDER, pact, target or _target(), ACTOR)


# --- one pair ----------------------------------------------------------------------------------


def test_a_pair_is_compared_and_stored_as_a_bidirectional_result() -> None:
    db = _FakeDb()
    entry = _pair(db)
    assert (entry.status, entry.verdict, entry.number) == ("compared", "pass", 1)
    assert (entry.consumer, entry.consumer_version, entry.provider_version) == ("Billing Service", "1.0.0", "p-1")
    [params] = db.inserted
    assert params[0:5] == (TENANT, CONSUMER.id, PROVIDER.id, "pv-id", "v-p-1")
    assert params[6] is True  # success
    assert params[10:13] == ("Apiome bi-directional comparison", "bidirectional", "c-p-1")
    assert params[12 + 1].adapted["verdict"] == "pass"
    assert params[12 + 1].adapted["providerContractSha"] == "b" * 64
    assert any("FOR UPDATE" in sql for sql in db.statements)


def test_a_failing_pair_is_stored_as_a_failed_result() -> None:
    db = _FakeDb(pact=_pact(total="lots"))
    entry = _pair(db)
    assert (entry.status, entry.verdict) == ("compared", "fail")
    assert db.inserted[0][6] is False


def test_a_pair_already_compared_reads_neither_document() -> None:
    db = _FakeDb(existing={"number": 3, "verdict": "partial"})
    entry = _pair(db)
    assert (entry.status, entry.verdict, entry.number) == ("already-compared", "partial", 3)
    assert db.reads == [] and db.inserted == []


def test_a_race_lost_to_another_publish_is_reported_as_already_compared() -> None:
    db = _FakeDb()
    db.conflict = True
    assert _pair(db).status == "already-compared"


def test_inputs_the_engine_refuses_are_stored_as_a_failure_with_the_reason() -> None:
    db = _FakeDb(contract={"openapi": "2.0"})
    entry = _pair(db)
    assert (entry.status, entry.verdict) == ("compared", "fail")
    payload = db.inserted[0][13].adapted
    assert payload["error"]["code"] == "comparison-not-possible"
    assert "OpenAPI 3.x" in payload["error"]["message"]


def test_a_failure_to_store_is_reported_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    db = _FakeDb()
    db.fail_insert = True
    entry = _pair(db)
    assert entry.status == "error"
    assert entry.reason == "the result could not be stored (RuntimeError)"
    assert "could not store pact" in caplog.text


def test_a_pact_version_that_is_gone_is_reported() -> None:
    db = _FakeDb()
    db.has_pact_version = False
    entry = _pair(db)
    assert (entry.status, entry.reason) == ("error", "the pact version no longer exists")


def test_each_document_is_read_once_per_run() -> None:
    db = _FakeDb()
    documents = store._Documents(db)
    pact = store._Pact(CONSUMER.id, CONSUMER.name, "1.0.0", SHA)
    for version in ("p-1", "p-2"):
        target = ContractTarget(f"v-{version}", version, 1, "same-contract", "b" * 64)
        store._compare_pair(db, documents, TENANT, PROVIDER, pact, target, ACTOR)
    assert db.reads == ["pact", "contract"]


# --- a pact is published -----------------------------------------------------------------------


def _outcome() -> PublishOutcome:
    record = PactRecord(
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        provider_slug="ledger-api",
        provider_name="Ledger API",
        consumer_version="1.0.0",
        sha=SHA,
        content=_pact(),
    )
    return PublishOutcome(CONSUMER, None, [PublishedPact(pact=record, created=True)])  # type: ignore[arg-type]


def _target_row(version: str, seq: int, branches: List[str]) -> Dict[str, Any]:
    return {
        "version_id": f"v-{version}",
        "version_number": version,
        "version_seq": seq,
        "contract_id": f"c-{version}",
        "sha": "b" * 64,
        "branches": branches,
        "environments": [],
    }


def test_a_published_pact_is_compared_with_each_selected_provider_version() -> None:
    db = _FakeDb()
    db.targets = [_target_row("p-1", 1, ["main"]), _target_row("p-2", 2, ["feat/x"])]
    with patch.object(store, "get_pacticipant", return_value=PROVIDER):
        run = store.compare_published_pacts(db, TENANT, _outcome(), actor=ACTOR)
    assert [(e.provider_version, e.status) for e in run.entries] == [("p-2", "compared"), ("p-1", "compared")]


def test_a_provider_without_contracts_gives_an_empty_run() -> None:
    db = _FakeDb()
    with patch.object(store, "get_pacticipant", return_value=PROVIDER):
        assert store.compare_published_pacts(db, TENANT, _outcome(), actor=ACTOR).entries == []


def test_provider_versions_over_the_limit_are_reported_as_skipped() -> None:
    db = _FakeDb()
    db.targets = [_target_row(f"p-{i}", i, [f"b{i}"]) for i in range(1, 24)]
    with (
        patch.object(store, "get_pacticipant", return_value=PROVIDER),
        patch.object(store, "MAX_CONTRACTS_PER_PACT", 2),
    ):
        run = store.compare_published_pacts(db, TENANT, _outcome(), actor=ACTOR)
    assert [e.status for e in run.entries[:2]] == ["compared", "compared"]
    assert {e.status for e in run.entries[2:]} == {"skipped"}
    assert len(run.entries) == 23
    assert run.entries[2].reason == "over the limit of 2 provider versions compared per publish"


def test_an_unreadable_provider_is_logged_and_the_publish_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    with patch.object(store, "get_pacticipant", side_effect=RuntimeError("db down")):
        run = store.compare_published_pacts(_FakeDb(), TENANT, _outcome(), actor=ACTOR)
    assert run.entries == []
    assert "could not read the contracts" in caplog.text


# --- a provider contract is published ----------------------------------------------------------


def _candidate(
    consumer: str, version: str, seq: int, sha: str, branches: tuple = (), main: str = "main"
) -> PactCandidate:
    return PactCandidate(
        consumer_id=f"id-{consumer}",
        consumer_slug=consumer.lower(),
        consumer_name=consumer,
        consumer_main_branch=main,
        version_id=f"cv-{consumer}-{version}",
        version_number=version,
        version_seq=seq,
        sha=sha,
        branches=branches,
    )


def test_a_contract_is_compared_with_main_the_matching_branch_and_the_branch_history() -> None:
    db = _FakeDb()
    candidates = [
        _candidate("Billing", "1.0.0", 1, "1" * 64, ("main",)),
        _candidate("Billing", "1.1.0", 2, "2" * 64, ("feat/x",)),
        _candidate("Billing", "1.2.0", 3, "3" * 64, ("feat/y",)),
        _candidate("Audit", "0.1.0", 4, "4" * 64, ("feat/old",)),
        _candidate("Audit", "0.2.0", 5, "5" * 64, ("feat/new",)),
    ]
    # Audit 0.1.0's pact was compared with an earlier feat/x contract: the new one re-runs it.
    db.history = [{"consumer_id": "id-Audit", "sha": "4" * 64}]
    pacts = store._pacts_for_contract(db, TENANT, PROVIDER, _target("p-9", 9, ("feat/x",)), candidates)
    # Defaults: Audit's latest (0.2.0) and Billing's main (1.0.0); branch: Billing 1.1.0; history: Audit 0.1.0.
    assert [(p.consumer_name, p.consumer_version) for p in pacts] == [
        ("Audit", "0.2.0"),
        ("Audit", "0.1.0"),
        ("Billing", "1.1.0"),
        ("Billing", "1.0.0"),
    ]


def test_without_a_branch_only_the_default_selectors_apply() -> None:
    db = _FakeDb()
    candidates = [_candidate("Billing", "1.0.0", 1, "1" * 64, ("main",)), _candidate("Billing", "1.1.0", 2, "2" * 64)]
    pacts = store._pacts_for_contract(db, TENANT, PROVIDER, _target("p-1", 1, ()), candidates)
    assert [p.consumer_version for p in pacts] == ["1.0.0"]
    assert not any("r.kind = 'bidirectional'" in sql for sql in db.statements)


def test_a_published_contract_is_compared_and_over_the_limit_is_skipped() -> None:
    db = _FakeDb()
    db.targets = [_target_row("p-1", 1, ["main"])]
    candidates = [_candidate(f"C{i}", "1.0.0", i, f"{i:064x}", ("main",)) for i in range(1, 5)]
    with (
        patch.object(store, "get_pacticipant", return_value=PROVIDER),
        patch.object(store, "list_pact_candidates", return_value=(PROVIDER, candidates)),
        patch.object(store, "MAX_PACTS_PER_CONTRACT", 3),
    ):
        run = store.compare_provider_contract(db, TENANT, "ledger-api", "p-1", actor=ACTOR)
    assert [e.status for e in run.entries] == ["compared", "compared", "compared", "skipped"]
    assert run.entries[3].reason == "over the limit of 3 pacts compared per publish"


def test_a_version_without_a_contract_compares_nothing() -> None:
    db = _FakeDb()
    db.targets = [_target_row("p-1", 1, ["main"])]
    with patch.object(store, "get_pacticipant", return_value=PROVIDER):
        assert store.compare_provider_contract(db, TENANT, "ledger-api", "p-2", actor=ACTOR).entries == []


def test_a_failure_to_select_is_logged_and_gives_an_empty_run(caplog: pytest.LogCaptureFixture) -> None:
    with patch.object(store, "get_pacticipant", side_effect=RuntimeError("db down")):
        assert store.compare_provider_contract(_FakeDb(), TENANT, "ledger-api", "p-1", actor=ACTOR).entries == []
    assert "could not select the pacts" in caplog.text
