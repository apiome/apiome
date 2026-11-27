"""Store rules of the pacticipant registry that need no database — PFX-1.1 (#6914).

``test_pacticipant_db`` runs the SQL against the real schema. Here the database is a double, and
what is asserted is what the store decides *before* or *around* a statement: a malformed request
never reaches the database, a reference is resolved inside the caller's tenant, a handle collision
becomes a stable refusal, and a patch writes only the fields that were sent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pacticipant import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_INVALID_BRANCH,
    CODE_INVALID_SLUG,
    CODE_INVALID_TAG,
    CODE_INVALID_URL,
    CODE_INVALID_VERSION,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    PacticipantInput,
    PacticipantPatch,
    PacticipantValidationError,
    PacticipantVersionInput,
    pacticipant_record_from_row,
)
from app.pacticipant_store import (
    add_tag,
    create_pacticipant,
    get_pacticipant,
    get_version,
    list_pacticipants,
    record_version,
    update_pacticipant,
)

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "55555555-5555-4555-8555-555555555555"
CONSUMER = "66666666-6666-4666-8666-666666666666"
USER = "77777777-7777-4777-8777-777777777777"
ACTOR = ConsumerActor(user_id=USER, label="dev@example.com")

ROW: Dict[str, Any] = {
    "id": "22222222-2222-4222-8222-222222222222",
    "tenant_id": TENANT,
    "slug": "billing-service",
    "name": "Billing Service",
    "repository_url": None,
    "main_branch": "main",
    "project_id": None,
    "consumer_id": None,
}
PACTICIPANT = pacticipant_record_from_row(ROW)


def _db(rows: Optional[List[Dict[str, Any]]] = None) -> MagicMock:
    """A database double whose every statement answers ``rows``."""
    db = MagicMock()
    db.execute_query.return_value = [ROW] if rows is None else rows
    db.get_project_core.return_value = {"id": PROJECT}
    db.get_project_by_slug.return_value = {"id": PROJECT}
    db.get_consumer_by_id.return_value = {"id": CONSUMER}
    return db


def _code(call, *args, **kwargs) -> str:
    with pytest.raises(PacticipantValidationError) as caught:
        call(*args, **kwargs)
    return caught.value.code


def _statement(db: MagicMock, index: int = -1) -> tuple:
    """``(sql, params)`` of a statement the double received."""
    sql, params = db.execute_query.call_args_list[index].args
    return " ".join(sql.split()), params


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


def test_a_reference_is_resolved_inside_the_callers_tenant() -> None:
    db = _db()
    assert get_pacticipant(db, TENANT, "Billing Service").slug == "billing-service"
    sql, params = _statement(db)
    assert "WHERE tenant_id = %s::uuid AND (slug = %s)" in sql
    assert params == (TENANT, "billing-service")


def test_an_id_shaped_reference_is_tried_as_id_and_as_handle() -> None:
    db = _db()
    get_pacticipant(db, TENANT, ROW["id"])
    sql, params = _statement(db)
    assert "(id = %s::uuid OR slug = %s)" in sql and params == (TENANT, ROW["id"], ROW["id"])


@pytest.mark.parametrize(
    ("tenant", "ref"), [(TENANT, ""), (TENANT, "   "), ("", "billing-service"), ("not-a-uuid", "x")]
)
def test_an_empty_reference_or_tenant_finds_nothing_without_a_query(tenant: str, ref: str) -> None:
    db = _db()
    assert _code(get_pacticipant, db, tenant, ref) == CODE_NOT_FOUND
    assert db.execute_query.call_count == 0


def test_nothing_matching_is_not_found() -> None:
    assert _code(get_pacticipant, _db([]), TENANT, "billing-service") == CODE_NOT_FOUND
    assert _code(get_version, _db([]), PACTICIPANT, "1.0.0") == CODE_VERSION_NOT_FOUND
    assert list_pacticipants(_db(), "not-a-uuid") == []


# ---------------------------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------------------------


def test_create_derives_the_handle_and_stores_the_actor() -> None:
    db = _db()
    create_pacticipant(db, TENANT, PacticipantInput(name=" Billing Service "), actor=ACTOR)
    _, params = _statement(db)
    assert params == (
        TENANT, "billing-service", "Billing Service", None, None, None, None, None, USER, USER,
        # The alias guard: no renamed pacticipant may still answer to the handle (PFX-8.10).
        TENANT, TENANT, "billing-service",
    )


def test_create_resolves_both_bindings_in_the_tenant() -> None:
    db = _db()
    create_pacticipant(
        db, TENANT, PacticipantInput(name="Billing", project="billing-api", consumer_id=CONSUMER), actor=ACTOR
    )
    db.get_project_by_slug.assert_called_once_with("billing-api", TENANT)
    db.get_consumer_by_id.assert_called_once_with(CONSUMER, TENANT)
    assert _statement(db)[1][6:8] == (PROJECT, CONSUMER)

    create_pacticipant(db, TENANT, PacticipantInput(name="Other", project=PROJECT), actor=ACTOR)
    db.get_project_core.assert_called_once_with(PROJECT, TENANT)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"name": "!!!"}, CODE_INVALID_SLUG),
        ({"name": "A", "slug": "Not A Slug"}, CODE_INVALID_SLUG),
        ({"name": "A", "repository_url": "git@github.com:a/b.git"}, CODE_INVALID_URL),
        ({"name": "A", "main_branch": " main"}, CODE_INVALID_BRANCH),
    ],
)
def test_a_malformed_pacticipant_never_reaches_the_database(body: Dict[str, Any], code: str) -> None:
    db = _db()
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(**body), actor=ACTOR) == code
    assert db.execute_query.call_count == 0


def test_an_unknown_binding_is_refused_before_the_insert() -> None:
    db = _db()
    db.get_project_by_slug.return_value = None
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(name="A", project="gone"), actor=ACTOR) == (
        CODE_PROJECT_NOT_FOUND
    )
    db.get_consumer_by_id.return_value = None
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(name="A", consumer_id=CONSUMER), actor=ACTOR) == (
        CODE_CONSUMER_NOT_FOUND
    )
    # A consumer reference that is not an id is not looked up at all.
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(name="A", consumer_id="billing"), actor=ACTOR) == (
        CODE_CONSUMER_NOT_FOUND
    )
    assert db.execute_query.call_count == 0


def test_a_handle_collision_is_a_stable_refusal() -> None:
    db = _db()
    db.execute_query.side_effect = psycopg2.errors.UniqueViolation("pacticipant_tenant_slug_key")
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(name="Billing Service"), actor=ACTOR) == (
        CODE_SLUG_TAKEN
    )


def test_an_unattributable_actor_is_stored_as_null() -> None:
    db = _db()
    create_pacticipant(db, TENANT, PacticipantInput(name="A"), actor=ConsumerActor(user_id="legacy-key"))
    assert _statement(db)[1][8:10] == (None, None)


# ---------------------------------------------------------------------------------------------
# Update and delete
# ---------------------------------------------------------------------------------------------


def test_an_empty_patch_writes_nothing() -> None:
    db = _db()
    assert update_pacticipant(db, TENANT, "billing-service", PacticipantPatch(), actor=ACTOR) == PACTICIPANT
    assert db.execute_query.call_count == 1  # the read


def test_a_patch_writes_only_the_fields_sent_and_null_clears() -> None:
    db = _db()
    update_pacticipant(
        db, TENANT, "billing-service", PacticipantPatch(repository_url=None, project=None), actor=ACTOR
    )
    sql, params = _statement(db)
    assert "SET repository_url = %s, project_id = %s::uuid, updated_at = CURRENT_TIMESTAMP" in sql
    assert "slug =" not in sql.split("WHERE")[0] and "name =" not in sql.split("WHERE")[0]
    assert params == (None, None, USER, ROW["id"], TENANT)


def test_a_patch_validates_what_it_writes() -> None:
    db = _db()
    for patch, code in (
        (PacticipantPatch(name=None), "pacticipant-invalid-name"),
        (PacticipantPatch(repository_url="ftp://x"), CODE_INVALID_URL),
        (PacticipantPatch(main_branch="main\n"), CODE_INVALID_BRANCH),
    ):
        assert _code(update_pacticipant, db, TENANT, "billing-service", patch, actor=ACTOR) == code
    db.get_project_by_slug.return_value = None
    assert _code(
        update_pacticipant, db, TENANT, "billing-service", PacticipantPatch(project="gone"), actor=ACTOR
    ) == CODE_PROJECT_NOT_FOUND
    assert all("UPDATE" not in call.args[0] for call in db.execute_query.call_args_list)


# ---------------------------------------------------------------------------------------------
# Versions and tags
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "details", "code"),
    [
        (" 1.0.0", {}, CODE_INVALID_VERSION),
        ("", {}, CODE_INVALID_VERSION),
        ("1.0.0", {"build_url": "not a url"}, CODE_INVALID_URL),
        ("1.0.0", {"branch": "main "}, CODE_INVALID_BRANCH),
        ("1.0.0", {"tags": ["ok", ""]}, CODE_INVALID_TAG),
    ],
)
def test_a_malformed_version_opens_no_transaction(number: str, details: Dict[str, Any], code: str) -> None:
    db = _db()
    assert _code(record_version, db, PACTICIPANT, number, PacticipantVersionInput(**details), actor=ACTOR) == code
    assert db._guarded_tx.call_count == 0


def test_recording_into_a_deleted_pacticipant_is_not_found() -> None:
    db = _db()
    db._guarded_tx.side_effect = psycopg2.errors.ForeignKeyViolation("pacticipant_version_pacticipant_id_fkey")
    assert _code(record_version, db, PACTICIPANT, "1.0.0", PacticipantVersionInput(), actor=ACTOR) == CODE_NOT_FOUND


def test_a_tag_is_validated_before_the_version_is_read() -> None:
    db = _db()
    assert _code(add_tag, db, PACTICIPANT, "1.0.0", " prod") == CODE_INVALID_TAG
    assert db.execute_query.call_count == 0
