"""Store rules for entity owners — CDG-2.2 (#5961).

:mod:`app.entity_owner_store` runs every write in one transaction through ``db._guarded_tx``; here a
scripted cursor stands in for it (reads answer from a queue, statements are recorded), so the rules
are pinned without a database:

* confirming a suggestion makes it the owner and audits **who** confirmed it;
* importers only ever write ``suggested`` rows, a slug naming no team is returned rather than
  stored, and no notification is written;
* an assignment replaces the confirmed owner, a bulk assignment is all or nothing;
* every change appends its ``owner.*`` row on the transaction's own cursor.

V285's SQL (indexes, CODEOWNERS triggers) was exercised against Postgres when the ticket was built;
``test_entity_owners_migration`` pins the schema.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app import entity_owner_store as store
from app.consumer_contract_store import ConsumerActor
from app.entity_owners import (
    CODE_ENTITY_NOT_FOUND,
    CODE_INVALID,
    CODE_NO_SUGGESTION,
    CODE_TEAM_NOT_FOUND,
    EntityRef,
    OwnerValidationError,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_ITEM_2 = "44444444-4444-4444-8444-444444444444"
_PAYMENTS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PLATFORM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_USER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_ACTOR = ConsumerActor(user_id=_USER, label="lead@example.com")


def _row(slug: str, status: str = "suggested", source: str = "gateway_tag", **extra: Any) -> Dict[str, Any]:
    """An owner row as ``_OWNER_COLUMNS`` selects it."""
    team_id = _PAYMENTS if slug == "payments" else _PLATFORM
    row = {
        "id": f"row-{slug}-{status}",
        "status": status,
        "source": source,
        "source_ref": f"owner:{slug}" if source == "gateway_tag" else None,
        "team_id": team_id,
        "confirmed_by": _USER if status == "confirmed" else None,
        "confirmed_at": "2026-10-18T00:00:00+00:00" if status == "confirmed" else None,
        "created_at": None,
        "team_slug": slug,
        "team_name": slug.title(),
    }
    row.update(extra)
    return row


_FOUND = {"found": 1}
_TEAM_PLATFORM = {"id": _PLATFORM, "slug": "platform", "name": "Platform"}


class _ScriptedCursor:
    """Reads answer from a queue; statements are recorded."""

    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[str] = []
        self.rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))

    def _next(self) -> Any:
        assert self.answers, f"no scripted answer left after: {self.statements[-1]}"
        return self.answers.pop(0)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._next()

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._next()

    def ran(self, fragment: str) -> bool:
        return any(fragment in s for s in self.statements)


@pytest.fixture
def audits():
    recorded: List[Dict[str, Any]] = []
    with patch.object(
        store.db, "_append_access_audit",
        side_effect=lambda cursor, **kw: recorded.append({"cursor": cursor, **kw}),
    ):
        yield recorded


def _tx(cursor: _ScriptedCursor):
    return patch.object(store.db, "_guarded_tx", side_effect=lambda work: work(cursor))


# ---------------------------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------------------------


def test_read_splits_the_owner_from_the_suggestions() -> None:
    cursor = _ScriptedCursor(
        [_FOUND, [_row("platform", "confirmed", "manual"), _row("payments")]]
    )
    with _tx(cursor):
        result = store.read_owners(_TENANT, "catalog_item", _ITEM)
    assert result.owner is not None and result.owner.team.slug == "platform"
    assert [(s.team.slug, s.source, s.source_ref) for s in result.suggestions] == [
        ("payments", "gateway_tag", "owner:payments")
    ]
    assert cursor.ran("NOT e.publishable AND e.deleted_at IS NULL")


def test_an_entity_of_another_kind_or_tenant_is_not_found() -> None:
    cursor = _ScriptedCursor([None])
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.read_owners(_TENANT, "project", _ITEM)
    assert caught.value.code == CODE_ENTITY_NOT_FOUND


def test_a_malformed_id_is_not_found_without_a_query() -> None:
    cursor = _ScriptedCursor([])
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.read_owners(_TENANT, "consumer", "not-a-uuid")
    assert caught.value.code == CODE_ENTITY_NOT_FOUND
    assert cursor.statements == []


# ---------------------------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------------------------


def test_confirming_the_only_suggestion_makes_it_the_owner_and_audits_who(audits) -> None:
    after = [_row("payments", "confirmed")]
    cursor = _ScriptedCursor([_FOUND, [_row("payments")], after])
    with _tx(cursor):
        result = store.confirm_owner(_TENANT, "catalog_item", _ITEM, None, actor=_ACTOR)
    assert result.owner is not None and result.owner.team.slug == "payments"
    assert result.owner.source == "gateway_tag" and result.owner.confirmed_by == _USER
    assert cursor.ran("SET status = 'confirmed', confirmed_by = %s::uuid")
    assert len(audits) == 1 and audits[0]["cursor"] is cursor
    assert audits[0]["action"] == "owner.confirm"
    assert audits[0]["actor_id"] == _USER
    assert audits[0]["detail"]["confirmed_by"] == _USER
    assert audits[0]["detail"]["source"] == "gateway_tag"
    assert audits[0]["detail"]["to"] == "payments"


def test_confirm_with_several_teams_suggested_must_name_one() -> None:
    cursor = _ScriptedCursor([_FOUND, [_row("payments"), _row("platform")]])
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.confirm_owner(_TENANT, "catalog_item", _ITEM, None, actor=_ACTOR)
    assert caught.value.code == CODE_INVALID


def test_confirm_names_a_team_among_several(audits) -> None:
    cursor = _ScriptedCursor(
        [_FOUND, [_row("payments"), _row("platform")], [_row("platform", "confirmed")]]
    )
    with _tx(cursor):
        result = store.confirm_owner(_TENANT, "catalog_item", _ITEM, "Platform", actor=_ACTOR)
    assert result.owner is not None and result.owner.team.slug == "platform"


def test_confirming_with_no_suggestion_is_refused() -> None:
    cursor = _ScriptedCursor([_FOUND, [_row("platform", "confirmed", "manual")]])
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.confirm_owner(_TENANT, "catalog_item", _ITEM, None, actor=_ACTOR)
    assert caught.value.code == CODE_NO_SUGGESTION
    assert not cursor.ran("SET status = 'confirmed'")


# ---------------------------------------------------------------------------------------------
# assign / remove
# ---------------------------------------------------------------------------------------------


def test_assign_replaces_the_confirmed_owner_and_audits_from_and_to(audits) -> None:
    before = [_row("payments", "confirmed")]
    after = [_row("platform", "confirmed", "manual"), _row("payments")]
    cursor = _ScriptedCursor([_FOUND, _TEAM_PLATFORM, before, after])
    with _tx(cursor):
        result = store.assign_owner(_TENANT, "project", _ITEM, "platform", actor=_ACTOR)
    assert result.owner is not None and result.owner.source == "manual"
    # The previous owner came from a gateway tag, so it goes back to being a suggestion.
    assert cursor.ran("SET status = 'suggested', confirmed_by = NULL")
    assert cursor.ran("'confirmed', %s, %s::uuid, CURRENT_TIMESTAMP")
    assert audits[0]["action"] == "owner.assign"
    assert audits[0]["detail"] == {
        "kind": "project", "entity_id": _ITEM, "from": "payments", "to": "platform"
    }
    assert audits[0]["target"] == f"project:{_ITEM}"


def test_assigning_an_unknown_team_is_refused() -> None:
    cursor = _ScriptedCursor([_FOUND, None])
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.assign_owner(_TENANT, "project", _ITEM, "ghost", actor=_ACTOR)
    assert caught.value.code == CODE_TEAM_NOT_FOUND


def test_remove_audits_only_when_there_was_an_owner(audits) -> None:
    cursor = _ScriptedCursor([_FOUND, [_row("payments")], [_row("payments")]])
    with _tx(cursor):
        store.remove_owner(_TENANT, "connector", _ITEM, actor=_ACTOR)
    assert audits == [] and not cursor.ran("DELETE FROM apiome.entity_owners")

    cursor = _ScriptedCursor([_FOUND, [_row("platform", "confirmed", "manual")], []])
    with _tx(cursor):
        result = store.remove_owner(_TENANT, "connector", _ITEM, actor=_ACTOR)
    assert result.owner is None
    assert [a["action"] for a in audits] == ["owner.remove"]


# ---------------------------------------------------------------------------------------------
# bulk
# ---------------------------------------------------------------------------------------------


def test_bulk_assign_is_one_transaction_with_one_audit_row(audits) -> None:
    owned = [_row("platform", "confirmed", "manual")]
    cursor = _ScriptedCursor(
        [_TEAM_PLATFORM, _FOUND, _FOUND, [], owned, [_row("payments", "confirmed")], owned]
    )
    refs = [
        EntityRef(kind="catalog_item", id=_ITEM),
        EntityRef(kind="consumer", id=_ITEM_2),
        EntityRef(kind="catalog_item", id=_ITEM.upper()),
    ]
    with _tx(cursor):
        results = store.bulk_assign_owner(_TENANT, "platform", refs, actor=_ACTOR)
    assert [r.kind for r in results] == ["catalog_item", "consumer"]
    assert len(audits) == 1 and audits[0]["action"] == "owner.bulk_assign"
    assert audits[0]["detail"]["entities"] == [
        {"kind": "catalog_item", "entity_id": _ITEM, "from": None},
        {"kind": "consumer", "entity_id": _ITEM_2, "from": "payments"},
    ]


def test_bulk_assign_checks_every_entity_before_writing(audits) -> None:
    cursor = _ScriptedCursor([_TEAM_PLATFORM, _FOUND, None])
    refs = [EntityRef(kind="catalog_item", id=_ITEM), EntityRef(kind="consumer", id=_ITEM_2)]
    with _tx(cursor), pytest.raises(OwnerValidationError) as caught:
        store.bulk_assign_owner(_TENANT, "platform", refs, actor=_ACTOR)
    assert caught.value.code == CODE_ENTITY_NOT_FOUND
    assert not cursor.ran("INSERT INTO apiome.entity_owners")
    assert audits == []


# ---------------------------------------------------------------------------------------------
# importer suggestions
# ---------------------------------------------------------------------------------------------


def _suggest(cursor: _ScriptedCursor, *teams: str):
    with _tx(cursor):
        return store.record_suggestions(
            _TENANT, "catalog_item", _ITEM, "gateway_tag",
            [{"team": team, "sourceRef": f"owner:{team}"} for team in teams],
        )


def test_a_known_team_is_suggested_and_an_unknown_one_is_returned(audits) -> None:
    cursor = _ScriptedCursor(
        [[{"slug": "payments", "id": _PAYMENTS}], [], [{"slug": "payments"}]]
    )
    unknown = _suggest(cursor, "payments", "ghost")
    assert unknown == ["ghost"]
    inserts = [s for s in cursor.statements if s.startswith("INSERT INTO apiome.entity_owners")]
    assert len(inserts) == 1 and "'suggested'" in inserts[0]
    # It is never written as the owner: a team already confirmed is skipped, not overwritten.
    assert "WHERE NOT EXISTS" in inserts[0] and "c.status = 'confirmed'" in inserts[0]
    # Nothing is notified: no statement touches the inbox.
    assert not cursor.ran("apiome.notifications")
    assert audits[0]["action"] == "owner.suggestions"
    assert audits[0]["actor_id"] is None
    assert audits[0]["detail"]["to"] == ["payments"] and audits[0]["detail"]["unknown"] == ["ghost"]


def test_an_unchanged_suggestion_set_is_not_audited(audits) -> None:
    cursor = _ScriptedCursor(
        [[{"slug": "payments", "id": _PAYMENTS}], [{"slug": "payments"}], [{"slug": "payments"}]]
    )
    _suggest(cursor, "payments")
    assert audits == []


def test_an_empty_set_removes_the_sources_suggestions(audits) -> None:
    cursor = _ScriptedCursor([[{"slug": "payments"}], []])
    assert _suggest(cursor) == []
    delete = next(s for s in cursor.statements if s.startswith("DELETE FROM apiome.entity_owners"))
    assert "status = 'suggested'" in delete and "source = %s" in delete
    assert audits[0]["detail"]["from"] == ["payments"] and audits[0]["detail"]["to"] == []


def test_manual_is_not_a_suggestion_source() -> None:
    with pytest.raises(OwnerValidationError):
        store.record_suggestions(_TENANT, "catalog_item", _ITEM, "manual", [])


def test_non_uuid_ids_short_circuit() -> None:
    assert store.record_suggestions("t1", "catalog_item", "proj-1", "gateway_tag", [{"team": "x"}]) == []
