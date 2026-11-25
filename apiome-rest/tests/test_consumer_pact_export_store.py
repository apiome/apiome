"""Which names an exported pact carries — PFX-2.6 (#6930).

:func:`app.consumer_pact_export_store.resolve_pact_names` against a fake database: a bound
pacticipant's name wins, the handle is the fallback, the caller's provider choice wins over a
binding, several bound providers is a refusal, and every query is scoped by the tenant id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from app.consumer_contract import ConsumerRecord, ConsumerValidationError
from app.consumer_pact_export_store import CODE_PROVIDER_AMBIGUOUS, resolve_pact_names

_TENANT = "tenant-a"
_PROJECT = {"id": "project-1", "slug": "pets"}


class _FakeDb:
    """Answers the two binding queries from canned rows, recording the parameters."""

    def __init__(self, consumer_rows: List[Dict[str, Any]], project_rows: List[Dict[str, Any]]) -> None:
        self.consumer_rows = consumer_rows
        self.project_rows = project_rows
        self.calls: List[Tuple[str, tuple]] = []

    def execute_query(self, query: str, params: tuple) -> List[Dict[str, Any]]:
        self.calls.append((query, params))
        return self.consumer_rows if "consumer_id" in query else self.project_rows


def _consumer() -> ConsumerRecord:
    return ConsumerRecord(id="consumer-1", tenant_id=_TENANT, project_id="project-1", slug="web-app", name="Web App")


def test_unbound_names_fall_back_to_the_handles() -> None:
    names = resolve_pact_names(_FakeDb([], []), _TENANT, _PROJECT, _consumer())
    assert (names.consumer, names.provider, names.consumer_bound, names.provider_bound) == (
        "web-app",
        "pets",
        False,
        False,
    )


def test_bound_pacticipants_name_both_sides() -> None:
    db = _FakeDb([{"slug": "web", "name": "Web Frontend"}], [{"slug": "pets-api", "name": "Pets API"}])
    names = resolve_pact_names(db, _TENANT, _PROJECT, _consumer())
    assert (names.consumer, names.provider, names.consumer_bound, names.provider_bound) == (
        "Web Frontend",
        "Pets API",
        True,
        True,
    )


def test_every_query_is_scoped_by_the_tenant() -> None:
    db = _FakeDb([], [])
    resolve_pact_names(db, _TENANT, _PROJECT, _consumer())
    assert [params for _q, params in db.calls] == [(_TENANT, "consumer-1"), (_TENANT, "project-1")]
    assert all("tenant_id = %s::uuid" in query and "deleted_at IS NULL" in query for query, _p in db.calls)


def test_the_callers_provider_wins_and_skips_the_project_lookup() -> None:
    db = _FakeDb([], [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}])
    names = resolve_pact_names(db, _TENANT, _PROJECT, _consumer(), provider="  Pets V2 ")
    assert (names.provider, names.provider_bound) == ("Pets V2", False)
    assert len(db.calls) == 1


def test_several_bound_providers_without_a_choice_is_refused() -> None:
    db = _FakeDb([], [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}])
    with pytest.raises(ConsumerValidationError) as raised:
        resolve_pact_names(db, _TENANT, _PROJECT, _consumer())
    assert raised.value.code == CODE_PROVIDER_AMBIGUOUS
    assert "a, b" in str(raised.value)
