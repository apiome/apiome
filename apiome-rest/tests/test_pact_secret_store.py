"""Workspace secrets with the database faked — PFX-6.5 (#6957).

* :mod:`app.pact_secret_store` seals a value with the vault's keys, opens it only for a send or a
  run, fails closed without a key, refuses a taken name, a rename and deleting a secret in use;
* a webhook that refers to a secret its workspace does not have is refused when saved, pointing at
  the reference; one whose secret disappeared fails its delivery with the reason, unsent;
* a referred secret reaches the request and never the execution log;
* a verification target may name a secret (``auth.kind: secret``): its reference is shape-checked,
  checked to exist when stored, and opened by :func:`app.target_credentials.target_auth_headers`.

The live schema, the usage query and tenant scoping are proved in ``test_pact_secret_db``.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.config import settings
from app.consumer_contract_store import ConsumerActor
from app.contract_runner import AuthResolutionError, materialize_auth_headers
from app.pact_publication import PactPublicationError
from app.pact_secret import (
    CODE_SECRET_IN_USE,
    CODE_SECRET_INVALID,
    CODE_SECRET_NAME_TAKEN,
    CODE_SECRET_NOT_FOUND,
    CODE_SECRET_VAULT_UNAVAILABLE,
    PactSecretError,
    SecretCreate,
    SecretUpdate,
)
from app.pact_secret_store import _CIPHER, create_secret, delete_secret, resolve_secrets, update_secret
from app.pact_webhook import CODE_WEBHOOK_INVALID, WebhookInput, WebhookRecord, template_parameters
from app.pact_webhook_delivery import deliver_pact_webhook_event
from app.pact_webhook_store import DeliveryWebhook, checked_references
from app.target_credentials import target_auth_headers
from app.verification_target import CODE_AUTH_INVALID, TargetAuthReference, TargetValidationError
from app.verification_target_store import _assert_secret_exists

_TENANT = "33333333-3333-4333-8333-333333333333"
_ID = "55555555-5555-4555-8555-555555555555"
_VALUE = "ci-token-value-0123456789"
_ACTOR = ConsumerActor(user_id=None, label="test")


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured master key, as a deployment that stores credentials has."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)


@pytest.fixture
def keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    """No master key."""
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)


def _sealed_row(name: str, value: str) -> Dict[str, Any]:
    ciphertext, version = _CIPHER.seal({"value": value})
    return {"name": name, "secret_ciphertext": ciphertext, "key_version": version}


class _Cursor:
    """A cursor whose ``fetchone`` answers come from a list, recording every statement."""

    def __init__(self, answers: List[Optional[Dict[str, Any]]], rowcount: int = 1) -> None:
        self.answers = list(answers)
        self.statements: List[tuple] = []
        self.rowcount = rowcount

    def execute(self, query: str, params: tuple = ()) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.answers.pop(0)

    def fetchall(self) -> List[Dict[str, Any]]:
        return []


def _db(rows: Any = None, cursor: Optional[_Cursor] = None) -> MagicMock:
    database = MagicMock()
    database.execute_query.return_value = rows if rows is not None else []
    database._guarded_tx.side_effect = lambda work: work(cursor or _Cursor([]))
    return database


# --- sealing and resolving -----------------------------------------------------------------------


def test_a_value_is_sealed_and_opened_only_by_resolve(keyed: None) -> None:
    row = _sealed_row("ciToken", _VALUE)
    assert _VALUE.encode() not in row["secret_ciphertext"]
    database = _db([row])
    assert resolve_secrets(database, _TENANT, ["ciToken", "ciToken"]) == {"ciToken": _VALUE}
    query, params = database.execute_query.call_args.args
    assert "tenant_id = %s::uuid" in query and params == (_TENANT, ["ciToken"])


def test_resolving_nothing_reads_nothing() -> None:
    database = _db()
    assert resolve_secrets(database, _TENANT, []) == {}
    database.execute_query.assert_not_called()


def test_a_missing_secret_is_named_and_an_unopenable_one_fails_closed(keyed: None) -> None:
    with pytest.raises(PactSecretError) as missing:
        resolve_secrets(_db([]), _TENANT, ["gone"])
    assert missing.value.code == CODE_SECRET_NOT_FOUND and "'gone'" in str(missing.value)
    tampered = {"name": "ciToken", "secret_ciphertext": b"OPSC-not-a-blob", "key_version": 1}
    with pytest.raises(PactSecretError) as unopened:
        resolve_secrets(_db([tampered]), _TENANT, ["ciToken"])
    assert unopened.value.code == CODE_SECRET_VAULT_UNAVAILABLE


def test_another_vaults_blob_does_not_open_as_a_secret(keyed: None) -> None:
    from app.pact_webhook_secrets import seal_webhook_secrets

    ciphertext, version = seal_webhook_secrets({"value": _VALUE})
    row = {"name": "ciToken", "secret_ciphertext": ciphertext, "key_version": version}
    with pytest.raises(PactSecretError) as caught:
        resolve_secrets(_db([row]), _TENANT, ["ciToken"])
    assert caught.value.code == CODE_SECRET_VAULT_UNAVAILABLE


def test_without_a_key_nothing_is_stored(keyless: None) -> None:
    database = _db()
    with pytest.raises(PactSecretError) as caught:
        create_secret(database, _TENANT, SecretCreate(name="ciToken", value=_VALUE), actor=_ACTOR)
    assert caught.value.code == CODE_SECRET_VAULT_UNAVAILABLE and _VALUE not in str(caught.value)
    database._guarded_tx.assert_not_called()


def test_a_taken_name_is_a_conflict(keyed: None) -> None:
    cursor = _Cursor([{"n": 3}, None])
    with pytest.raises(PactSecretError) as caught:
        create_secret(_db(cursor=cursor), _TENANT, SecretCreate(name="ciToken", value=_VALUE), actor=_ACTOR)
    assert caught.value.code == CODE_SECRET_NAME_TAKEN and caught.value.pointer == "/name"
    insert = cursor.statements[1]
    assert _VALUE not in json.dumps([str(param) for param in insert[1]])


def test_a_secret_cannot_be_renamed(keyed: None) -> None:
    database = _db([{"id": _ID, "name": "ciToken"}])
    with pytest.raises(PactSecretError) as caught:
        update_secret(database, _TENANT, _ID, SecretUpdate(name="other"), actor=_ACTOR)
    assert caught.value.code == CODE_SECRET_INVALID and caught.value.pointer == "/name"
    database._guarded_tx.assert_not_called()


def test_an_update_without_a_value_keeps_the_ciphertext(keyed: None) -> None:
    cursor = _Cursor([])
    database = _db([{"id": _ID, "name": "ciToken"}], cursor=cursor)
    with patch("app.pact_secret_store.get_secret", return_value="record"):
        assert update_secret(database, _TENANT, _ID, SecretUpdate(description="d"), actor=_ACTOR) == "record"
    assert "secret_ciphertext" not in cursor.statements[0][0]
    with patch("app.pact_secret_store.get_secret", return_value="record"):
        update_secret(database, _TENANT, _ID, SecretUpdate(value=_VALUE), actor=_ACTOR)
    assert "secret_ciphertext = %s" in cursor.statements[1][0] and _VALUE not in str(cursor.statements[1][1])
    # Setting a value clears the waiting flag and turns on the webhooks that were waiting (PFX-8.15).
    assert "awaiting_value = FALSE" in cursor.statements[1][0]
    assert "awaiting_secrets" in cursor.statements[2][0] and cursor.statements[2][1] == (_TENANT,)


def test_a_secret_in_use_is_not_deleted_and_the_refusal_names_the_users() -> None:
    database = _db()
    database.execute_query.side_effect = [
        [{"id": _ID, "name": "ciToken"}],
        [
            {
                "id": "w-1",
                "description": "Verify Ledger API",
                "request_method": "POST",
                "request_url": "",
                "name": "ciToken",
            }
        ],
        [{"id": "t-1", "slug": "ledger-staging", "name": "ciToken"}],
    ]
    with pytest.raises(PactSecretError) as caught:
        delete_secret(database, _TENANT, _ID)
    assert caught.value.code == CODE_SECRET_IN_USE
    assert "'Verify Ledger API' (w-1)" in str(caught.value) and "'ledger-staging'" in str(caught.value)
    database._guarded_tx.assert_not_called()


# --- webhooks ------------------------------------------------------------------------------------


def _input(**changes: Any) -> WebhookInput:
    fields: Dict[str, Any] = {"method": "POST", "url": "https://ci.example.com/hook", **changes}
    return WebhookInput(**fields)


def test_saving_a_webhook_checks_each_reference_and_points_at_the_first_missing_one() -> None:
    webhook = _input(headers={"X-Team": "${user.team}"}, body={"k": "${user.gone}"})
    database = _db([{"name": "team"}])
    with pytest.raises(PactPublicationError) as caught:
        checked_references(database, _TENANT, webhook, {})
    assert caught.value.code == CODE_WEBHOOK_INVALID and caught.value.pointer == "/request/body"
    assert "'gone'" in str(caught.value)
    assert database.execute_query.call_args.args[1] == (_TENANT, ["team", "gone"])


def test_a_kept_secret_value_is_searched_for_references_too() -> None:
    database = _db([{"name": "signing"}])
    names = checked_references(
        database, _TENANT, _input(signing_secret="**********"), {"signingSecret": "${user.signing}"}
    )
    assert names == ["signing"]


def test_a_webhook_without_references_reads_nothing() -> None:
    database = _db()
    assert checked_references(database, _TENANT, _input(), {}) == []
    database.execute_query.assert_not_called()


_PARAMETERS = template_parameters(event_name="contract_published", provider_name="Ledger API")


def _row() -> Dict[str, Any]:
    return {
        "event_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": _TENANT,
        "pact_webhook_id": "22222222-2222-4222-8222-222222222222",
        "event_type": "pact.contract_published",
        "payload": {"eventName": "contract_published", "parameters": _PARAMETERS},
        "attempt_count": 0,
    }


class _Client:
    """Records the request; answers with an echo of every header (a receiver that leaks)."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def request(self, method: str, url: str, *, content: bytes, headers: Dict[str, str]) -> Any:
        import httpx

        self.requests.append({"url": url, "headers": dict(headers), "content": content})
        return httpx.Response(200, text=json.dumps(headers) + url)


def _deliver(record: WebhookRecord, secrets: Dict[str, Any], resolved: Any) -> tuple:
    database = MagicMock()
    client = _Client()
    resolver = patch("app.pact_webhook_delivery.resolve_secrets")
    with (
        patch(
            "app.pact_webhook_delivery.load_for_delivery", return_value=DeliveryWebhook(record=record, secrets=secrets)
        ),
        patch("app.pact_webhook_delivery.build_guarded_client", return_value=client),
        resolver as resolve,
    ):
        if isinstance(resolved, Exception):
            resolve.side_effect = resolved
        else:
            resolve.return_value = resolved
        deliver_pact_webhook_event(database, _row())
    return database.finalize_push_webhook_delivery_attempt.call_args.kwargs, client, resolve


def _referring_record() -> WebhookRecord:
    return WebhookRecord(
        id="22222222-2222-4222-8222-222222222222",
        url="https://ci.example.com/hook?key=${user.ciToken}",
        headers={"X-Api-Key": "${user.ciToken}"},
        body={"token": "${user.ciToken}"},
        secret_fields=["signingSecret"],
        secret_refs=["ciToken", "signing"],
    )


def test_a_delivery_resolves_its_references_in_its_own_tenant_and_logs_none() -> None:
    signing = "signing-value-0123456789"
    finalized, client, resolve = _deliver(
        _referring_record(), {"signingSecret": "${user.signing}"}, {"ciToken": _VALUE, "signing": signing}
    )
    assert resolve.call_args.args[1:] == (_TENANT, ["ciToken", "signing"])
    sent = client.requests[0]
    assert sent["headers"]["X-Api-Key"] == _VALUE and _VALUE in sent["url"] and _VALUE.encode() in sent["content"]
    assert sent["headers"]["X-Apiome-Signature"].startswith("sha256=")
    assert finalized["new_status"] == "delivered"
    stored = json.dumps(finalized, default=str)
    assert _VALUE not in stored and signing not in stored


def test_a_delivery_whose_secret_is_gone_fails_with_the_reason_unsent() -> None:
    gone = PactSecretError(CODE_SECRET_NOT_FOUND, "no secret 'ciToken' in this workspace")
    finalized, client, _resolve = _deliver(_referring_record(), {}, gone)
    assert client.requests == []
    assert finalized["new_status"] == "retrying" and "no secret 'ciToken'" in finalized["error_message"]
    assert "not sent" in finalized["execution_log"]


def test_a_delivery_whose_signing_secret_is_too_short_fails_unsent() -> None:
    finalized, client, _resolve = _deliver(
        _referring_record(), {"signingSecret": "${user.signing}"}, {"ciToken": _VALUE, "signing": "short"}
    )
    assert client.requests == [] and "at least 16 characters" in finalized["error_message"]


# --- verification targets ------------------------------------------------------------------------


def test_a_target_may_name_a_secret_and_only_by_a_name() -> None:
    auth = TargetAuthReference(kind="secret", scheme="bearer", ref="ciToken")
    assert auth.ref == "ciToken"
    for ref in ("ci-token", "Bearer abc.def", "1token"):
        with pytest.raises(ValidationError):
            TargetAuthReference(kind="secret", scheme="bearer", ref=ref)
    with pytest.raises(ValidationError):
        TargetAuthReference(kind="secret", ref="ciToken")


@pytest.mark.parametrize(
    ("scheme", "header_name", "expected"),
    [
        ("bearer", None, {"Authorization": f"Bearer {_VALUE}"}),
        ("header", "X-Api-Key", {"X-Api-Key": _VALUE}),
        ("basic", None, {"Authorization": "Basic " + base64.b64encode(b"ci:pw").decode()}),
    ],
)
def test_a_secret_value_is_presented_with_the_targets_scheme(scheme: str, header_name: Any, expected: dict) -> None:
    value = "ci:pw" if scheme == "basic" else _VALUE
    auth = TargetAuthReference(kind="secret", scheme=scheme, ref="ciToken", header_name=header_name)
    assert materialize_auth_headers(auth, secret_value=value) == expected
    with pytest.raises(AuthResolutionError) as caught:
        materialize_auth_headers(auth, secret_value=None)
    assert "'ciToken'" in str(caught.value)


def test_a_run_opens_the_targets_secret_in_the_targets_tenant() -> None:
    auth = TargetAuthReference(kind="secret", scheme="bearer", ref="ciToken")
    with patch("app.target_credentials.resolve_secrets", return_value={"ciToken": _VALUE}) as resolve:
        assert target_auth_headers(_TENANT, auth) == {"Authorization": f"Bearer {_VALUE}"}
    assert resolve.call_args.args[1:] == (_TENANT, ["ciToken"])
    gone = PactSecretError(CODE_SECRET_NOT_FOUND, "no secret 'ciToken' in this workspace")
    with (
        patch("app.target_credentials.resolve_secrets", side_effect=gone),
        pytest.raises(AuthResolutionError) as caught,
    ):
        target_auth_headers(_TENANT, auth)
    assert "no secret 'ciToken'" in str(caught.value)


def test_a_run_still_reads_env_and_stored_references() -> None:
    env = TargetAuthReference(kind="env", scheme="bearer", ref="CI_TOKEN")
    with patch.dict(os.environ, {"CI_TOKEN": _VALUE}):
        assert target_auth_headers(_TENANT, env) == {"Authorization": f"Bearer {_VALUE}"}
    stored = TargetAuthReference(kind="stored", scheme="bearer", ref=_ID)
    with patch("app.target_credentials.load_endpoint_auth_headers", return_value={"Authorization": "Bearer s"}):
        assert target_auth_headers(_TENANT, stored) == {"Authorization": "Bearer s"}


def test_storing_a_target_checks_its_secret_exists_in_its_workspace() -> None:
    auth = TargetAuthReference(kind="secret", scheme="bearer", ref="ciToken")
    with patch("app.verification_target_store.missing_secret_names", return_value=[]) as missing:
        _assert_secret_exists(_TENANT, auth)
    assert missing.call_args.args[1:] == (_TENANT, ["ciToken"])
    with patch("app.verification_target_store.missing_secret_names", return_value=["ciToken"]):
        with pytest.raises(TargetValidationError) as caught:
            _assert_secret_exists(_TENANT, auth)
    assert caught.value.code == CODE_AUTH_INVALID and "'ciToken'" in str(caught.value)
    with patch("app.verification_target_store.missing_secret_names") as untouched:
        _assert_secret_exists(_TENANT, TargetAuthReference(kind="env", scheme="bearer", ref="CI_TOKEN"))
        _assert_secret_exists(_TENANT, None)
    untouched.assert_not_called()
