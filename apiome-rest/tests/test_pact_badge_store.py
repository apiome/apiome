"""The SQL-free logic of the badge reads — PFX-1.10 (#6923): what each read asks and refuses."""

from __future__ import annotations

from typing import Any, Dict, List

from app.pact_badge_store import (
    MAX_PUBLIC_CONSUMERS,
    _statuses,
    consumers_of,
    find_public_project,
    pacticipant_badge,
    pair_badge,
    project_statuses,
)

_PROJECT = {"id": "proj-1", "tenant_id": "ten-1"}


class _Db:
    """Answers each statement by a fragment of its text; records the calls."""

    def __init__(self, answers: Dict[str, List[Dict[str, Any]]]) -> None:
        self.answers = answers
        self.calls: List[Any] = []

    def execute_query(self, sql: str, params: Any = ()) -> List[Dict[str, Any]]:
        self.calls.append((sql, params))
        for fragment, rows in self.answers.items():
            if fragment in sql:
                return rows
        return []


_LEDGER = {"id": "p1", "slug": "ledger-api", "name": "Ledger", "project_id": "proj-1"}
_WEB = {"id": "c1", "slug": "web", "name": "Web", "project_id": None}


def test_a_missing_public_project_is_none() -> None:
    assert find_public_project(_Db({}), "acme", "ledger") is None


def test_the_public_project_read_requires_a_published_public_version() -> None:
    db = _Db({"FROM apiome.projects": [_PROJECT]})
    assert find_public_project(db, "acme", "ledger") == _PROJECT
    sql, params = db.calls[0]
    assert "visibility = 'public'" in sql and "published IS TRUE" in sql and params == ("acme", "ledger")


def test_a_pacticipant_not_bound_to_the_project_is_none() -> None:
    db = _Db({"WHERE tenant_id = %s::uuid AND slug": [{**_LEDGER, "project_id": "other"}]})
    assert pacticipant_badge(db, _PROJECT, "ledger-api") is None
    assert pacticipant_badge(_Db({}), _PROJECT, "ghost") is None


def test_a_failing_pact_makes_the_pacticipant_failing() -> None:
    pairs = [
        {"consumer_slug": "web", "provider_slug": "ledger-api", "success": True},
        {"consumer_slug": "app", "provider_slug": "ledger-api", "success": False},
    ]
    db = _Db({"WHERE tenant_id = %s::uuid AND slug": [_LEDGER], "WITH latest": pairs})
    assert pacticipant_badge(db, _PROJECT, "ledger-api") == {
        "slug": "ledger-api",
        "name": "Ledger",
        "status": "failing",
        "pacts": 2,
    }


def test_a_pacticipant_without_pacts_is_unknown() -> None:
    db = _Db({"WHERE tenant_id = %s::uuid AND slug": [_LEDGER]})
    assert pacticipant_badge(db, _PROJECT, "ledger-api")["status"] == "unknown"


def test_a_pair_needs_one_side_bound_and_both_to_exist() -> None:
    pairs = [{"consumer_slug": "web", "provider_slug": "ledger-api", "success": True}]
    db = _Db({"WHERE tenant_id = %s::uuid AND slug": [_LEDGER], "WITH latest": pairs})
    # Both lookups return the (bound) ledger row here, so the pair is allowed.
    assert pair_badge(db, _PROJECT, "ledger-api", "web")["status"] == "verified"
    unbound = _Db({"WHERE tenant_id = %s::uuid AND slug": [_WEB]})
    assert pair_badge(unbound, _PROJECT, "ledger-api", "web") is None
    assert pair_badge(_Db({}), _PROJECT, "ledger-api", "web") is None


def test_a_pair_without_a_pact_is_unknown() -> None:
    db = _Db({"WHERE tenant_id = %s::uuid AND slug": [_LEDGER]})
    assert pair_badge(db, _PROJECT, "ledger-api", "web")["status"] == "unknown"


def test_project_statuses_covers_every_bound_pacticipant() -> None:
    db = _Db({"project_id = %s::uuid": [{"id": "p1", "slug": "ledger-api", "name": "Ledger"}]})
    [item] = project_statuses(db, _PROJECT)
    assert item["status"] == "unknown" and item["pacts"] == 0


def test_project_statuses_lists_the_consumers_of_a_provider_with_their_status() -> None:
    pairs = [
        {"consumer_slug": "web", "consumer_name": "Web app", "provider_slug": "ledger-api", "success": True},
        {"consumer_slug": "app", "consumer_name": "Mobile", "provider_slug": "ledger-api", "success": False},
        # Ledger is itself a consumer of billing: that pact is not one of its consumers.
        {"consumer_slug": "ledger-api", "consumer_name": "Ledger", "provider_slug": "billing", "success": None},
    ]
    db = _Db({"project_id = %s::uuid": [{"id": "p1", "slug": "ledger-api", "name": "Ledger"}], "WITH latest": pairs})
    [item] = project_statuses(db, _PROJECT)
    assert item["consumer_count"] == 2
    assert item["consumers"] == [
        {"slug": "app", "name": "Mobile", "status": "failing"},
        {"slug": "web", "name": "Web app", "status": "verified"},
    ]
    assert item["pacts"] == 3


def test_consumers_are_capped_but_counted() -> None:
    pairs = [
        {"consumer_slug": f"c{i:02d}", "consumer_name": f"C{i}", "provider_slug": "ledger-api", "success": True}
        for i in range(MAX_PUBLIC_CONSUMERS + 5)
    ]
    db = _Db({"project_id = %s::uuid": [{"id": "p1", "slug": "ledger-api", "name": "Ledger"}], "WITH latest": pairs})
    [item] = project_statuses(db, _PROJECT)
    assert item["consumer_count"] == MAX_PUBLIC_CONSUMERS + 5
    assert len(item["consumers"]) == MAX_PUBLIC_CONSUMERS


def test_a_consumer_without_a_name_falls_back_to_its_slug() -> None:
    pairs = [{"consumer_slug": "web", "provider_slug": "ledger-api", "success": None}]
    assert consumers_of("ledger-api", _statuses(_Db({"WITH latest": pairs}), "t", "p1")) == [
        {"slug": "web", "name": "web", "status": "unknown"}
    ]
