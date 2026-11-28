"""Secrets waiting for a value — PFX-8.15 (#7312).

``apiome pact migrate`` no longer refuses a webhook whose secret the source redacted: it creates a
placeholder secret without a value and imports the webhook turned off. Without a database
(``test_pact_contract_settings_db`` runs the SQL):

* a secret with no value is never resolved: the refusal names it and says where to set it;
* a secret's record says whether it has a value and where it came from, and never a value;
* a webhook referring to a waiting secret cannot be turned on — the refusal names the secret — and
  is stored as waiting when it is off;
* the migration import creates the placeholders, then the webhook turned off and waiting, and its
  note says what to set.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from app import pact_migration_store, pact_webhook_store
from app.consumer_contract_store import ConsumerActor
from app.pact_migration import WebhookImport
from app.pact_publication import PactPublicationError
from app.pact_secret import CODE_SECRET_LIMIT, CODE_SECRET_NO_VALUE, PactSecretError, SecretUsage
from app.pact_secret_store import (
    _record,
    create_placeholder_tx,
    enable_waiting_webhooks_tx,
    resolve_secrets,
    waiting_secret_names,
)
from app.pact_webhook import WebhookInput

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = ConsumerActor(user_id="33333333-3333-4333-8333-333333333333", label="ada@example.com")


class _Cursor:
    def __init__(self, ones: List[Optional[Dict[str, Any]]], alls: Optional[List[Dict[str, Any]]] = None) -> None:
        self.ones = list(ones)
        self.alls = alls or []
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.ones.pop(0)

    def fetchall(self) -> List[Dict[str, Any]]:
        return self.alls


def test_a_secret_with_no_value_is_never_resolved() -> None:
    database = MagicMock()
    database.execute_query.return_value = [
        {"name": "migrated_ab12cd34_password", "secret_ciphertext": None, "key_version": None, "awaiting_value": True}
    ]
    with pytest.raises(PactSecretError) as caught:
        resolve_secrets(database, TENANT, ["migrated_ab12cd34_password"])
    assert caught.value.code == CODE_SECRET_NO_VALUE
    assert "migrated_ab12cd34_password" in str(caught.value) and "Contracts → Settings → Secrets" in str(caught.value)


def test_the_record_says_whether_there_is_a_value_and_never_shows_one() -> None:
    row = {
        "id": "s-1",
        "name": "migrated_x_password",
        "awaiting_value": True,
        "origin": "migration",
        "value_updated_at": "2026-11-28T00:00:00+00:00",
    }
    record = _record(row, SecretUsage())
    assert record.has_value is False and record.origin == "migration" and record.value_updated_at is None
    assert "value" not in record.model_dump() or record.model_dump().get("value") is None
    live = _record({"id": "s-2", "name": "ci", "awaiting_value": False, "value_updated_at": "t"}, SecretUsage())
    assert live.has_value is True and live.origin is None and live.value_updated_at == "t"


def test_waiting_names_are_read_for_the_tenant_in_the_order_given() -> None:
    database = MagicMock()
    database.execute_query.return_value = [{"name": "b"}]
    assert waiting_secret_names(database, TENANT, ["a", "b"]) == ["b"]
    query, params = database.execute_query.call_args.args
    assert "awaiting_value" in query and params == (TENANT, ["a", "b"])
    database.reset_mock()
    assert waiting_secret_names(database, TENANT, []) == []
    database.execute_query.assert_not_called()


def test_a_placeholder_has_no_value_and_says_it_came_from_a_migration() -> None:
    cursor = _Cursor([{"n": 3}, {"id": "s-1"}])
    assert create_placeholder_tx(cursor, TENANT, "migrated_ab12cd34_password", "Waiting for a value", ACTOR)
    query, params = cursor.statements[1]
    assert "NULL, NULL, TRUE" in query and "ON CONFLICT (tenant_id, name) DO NOTHING" in query
    assert params[:4] == (TENANT, "migrated_ab12cd34_password", "Waiting for a value", "migration")
    # A name taken already is used as it is.
    assert not create_placeholder_tx(_Cursor([{"n": 3}, None]), TENANT, "x", "d", ACTOR)


def test_a_placeholder_over_the_limit_is_refused() -> None:
    with pytest.raises(PactSecretError) as caught:
        create_placeholder_tx(_Cursor([{"n": 200}]), TENANT, "x", "d", ACTOR)
    assert caught.value.code == CODE_SECRET_LIMIT


def test_setting_a_value_turns_on_only_webhooks_with_nothing_left_waiting() -> None:
    cursor = _Cursor([], alls=[{"id": "w-1"}])
    assert enable_waiting_webhooks_tx(cursor, TENANT) == ["w-1"]
    query, params = cursor.statements[0]
    assert "SET enabled = TRUE, awaiting_secrets = FALSE" in query
    assert "NOT EXISTS" in query and "s.awaiting_value" in query and params == (TENANT,)


def _webhook(**fields: Any) -> WebhookInput:
    return WebhookInput(method="POST", url="https://ci.example.com/h", **fields)


def test_a_webhook_waiting_for_a_secret_cannot_be_turned_on() -> None:
    with (
        patch.object(pact_webhook_store, "_scope_pacticipant", return_value=None),
        patch.object(pact_webhook_store, "checked_references", return_value=["migrated_x_password"]),
        patch.object(pact_webhook_store, "waiting_secret_names", return_value=["migrated_x_password"]),
    ):
        with pytest.raises(PactPublicationError) as caught:
            pact_webhook_store._write_values(MagicMock(), TENANT, _webhook(enabled=True), {})
        assert caught.value.pointer == "/enabled"
        assert "migrated_x_password has no value yet" in str(caught.value)
        values = pact_webhook_store._write_values(MagicMock(), TENANT, _webhook(enabled=False), {})
    assert values["awaiting_secrets"] is True and values["enabled"] is False


def test_a_webhook_with_its_secrets_set_is_not_waiting() -> None:
    with (
        patch.object(pact_webhook_store, "_scope_pacticipant", return_value=None),
        patch.object(pact_webhook_store, "checked_references", return_value=[]),
        patch.object(pact_webhook_store, "waiting_secret_names", return_value=[]),
    ):
        values = pact_webhook_store._write_values(MagicMock(), TENANT, _webhook(), {})
    assert values["awaiting_secrets"] is False and values["enabled"] is True


def test_the_import_creates_the_placeholders_then_the_webhook_turned_off() -> None:
    record = WebhookImport(
        index=0,
        uuid="3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
        webhook=_webhook(enabled=False, password="${user.migrated_ab12cd34_password}", username="ci"),
        created_at=None,
        placeholders=[("migrated_ab12cd34_password", "Waiting for a value")],
    )
    database = MagicMock()
    database._guarded_tx.side_effect = lambda work: work("cursor")
    with (
        patch.object(pact_migration_store, "_webhook_exists", return_value=False),
        patch.object(pact_migration_store, "create_placeholder_tx") as placeholder,
        patch.object(pact_migration_store, "create_webhook") as create,
    ):
        outcome, note = pact_migration_store._import_webhook(database, TENANT, record, ACTOR)
    assert outcome == "created"
    assert placeholder.call_args.args == ("cursor", TENANT, "migrated_ab12cd34_password", "Waiting for a value", ACTOR)
    assert create.call_args.kwargs["awaiting_secrets"] is True
    assert "turned off until its secrets have values: set migrated_ab12cd34_password" in note


def test_an_import_without_redacted_values_is_unchanged() -> None:
    record = WebhookImport(index=0, uuid=None, webhook=_webhook(), created_at=None)
    with (
        patch.object(pact_migration_store, "_webhook_exists", return_value=False),
        patch.object(pact_migration_store, "create_placeholder_tx") as placeholder,
        patch.object(pact_migration_store, "create_webhook") as create,
    ):
        assert pact_migration_store._import_webhook(MagicMock(), TENANT, record, ACTOR) == ("created", None)
    placeholder.assert_not_called()
    assert create.call_args.kwargs["awaiting_secrets"] is False
