"""The SQL-free logic of the badge reads — PFX-1.10 (#6923): what each read asks and refuses."""

from __future__ import annotations

from typing import Any, Dict, List

from app.pact_badge_store import find_public_project, pacticipant_badge, pair_badge, project_statuses

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
